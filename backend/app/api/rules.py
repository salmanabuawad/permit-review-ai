"""API: rules, sources, knowledge base and the regulatory registry."""
import re

from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


@router.get("/api/knowledge/candidates")
def candidate_search(q: str = "", p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    from ..models import CandidatePassage, SourceSnapshot
    stmt = select(CandidatePassage, SourceDocument, SourceSnapshot).join(SourceDocument, CandidatePassage.document_id == SourceDocument.id).join(SourceSnapshot, CandidatePassage.snapshot_id == SourceSnapshot.id).where(CandidatePassage.tenant_id == p.tenant_id, SourceDocument.tenant_id == p.tenant_id, SourceSnapshot.tenant_id == p.tenant_id, SourceDocument.sha256 == SourceSnapshot.sha256)
    if q.strip(): stmt = stmt.where(CandidatePassage.text_he.contains(q.strip()[:200], autoescape=True))
    rows = s.execute(stmt.order_by(CandidatePassage.id.desc()).limit(100))
    return [{"id": x.id,"document_id":d.id,"snapshot_id":v.id,"title":d.title,"page":x.page,"text_he":x.text_he[:4000],"sha256":v.sha256,"verification":"UNVERIFIED"} for x,d,v in rows]


# ------------------------------------------------------------------ rules / knowledge

@router.get("/api/rules")
def rules(include_deleted: bool = False, p: Principal = Depends(require("case.read")),
          s: Session = Depends(get_session)):
    rs = services.rules_for_tenant(s, p.tenant_id, include_deleted=include_deleted)
    sources = load_sources()
    out = []
    for r in rs:
        raw = dict(r.raw)
        raw["sources_resolved"] = [{**c, "source": sources.get(c.get("source_id"), {})} for c in raw.get("sources", [])]
        out.append(raw)
    return out


@router.post("/api/rules/{rule_id}/approval")
def approve_rule(rule_id: str, body: ApproveIn, p: Principal = Depends(require("rule.approve")),
                 s: Session = Depends(get_session)):
    rs = {r.id: r for r in services.rules_for_tenant(s, p.tenant_id)}
    r = rs.get(rule_id)
    if not r:
        raise HTTPException(404)
    if r.raw.get("yaml_review_state") in ("DEMO_FIXTURE", "SOURCE_MISSING", "RETIRED", "DRAFT"):
        raise HTTPException(409, "לא ניתן לאשר כלל ללא מקור מאומת")
    if len(body.note.strip()) < 5:
        raise HTTPException(422, "נדרש נימוק לאישור")
    s.add(RuleApproval(tenant_id=p.tenant_id, rule_id=rule_id, rule_version=str(r.raw.get("version")),
                       decision=body.decision, approved_by=p.id, note=body.note))
    audit.record(s, p.tenant_id, p.id, f"rule.{body.decision.lower()}", "rule", rule_id,
                 {"version": r.raw.get("version"), "note": body.note})
    s.commit()
    return {"ok": True}


@router.get("/api/rules/{rule_id}/versions")
def rule_versions(rule_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """Every saved version of a rule edited in this authority (oldest first); catalogue-only rules have none."""
    from ..models import RuleVersion
    rows = s.scalars(select(RuleVersion).where(RuleVersion.tenant_id == p.tenant_id, RuleVersion.rule_id == rule_id)
                     .order_by(RuleVersion.id))
    return [{"version": v.version, "deleted": v.deleted, "saved_by": v.saved_by, "saved_at": v.saved_at.isoformat(),
             "data": v.data} for v in rows]


@router.get("/api/rules/meta")
def rules_meta(p: Principal = Depends(require("case.read"))):
    return {"legal_levels": list(LEGAL_LEVEL_RANK), "reports": list(REPORTS), "severities": list(SEVERITIES),
            "check_kinds": {k: list(v) for k, v in CHECK_FIELDS.items()}, "operators": list(OPERATORS),
            "condition_ops": list(CONDITION_OPS), "review_states": list(AUTHOR_REVIEW_STATES),
            "permit_types": PERMIT_TYPES, "can_edit": p.can("rule.edit")}


@router.post("/api/rules")
def create_rule(body: RuleIn, p: Principal = Depends(require("rule.edit")), s: Session = Depends(get_session)):
    data = _clean_rule(body.rule)
    data["version"] = str(data.get("version") or "0.1")
    data.setdefault("review_state", "DRAFT")
    rid = str(data.get("id") or "")
    existing = {r.id for r in services.rules_for_tenant(s, p.tenant_id, include_deleted=True)}
    if rid in existing:
        raise HTTPException(409, f"כלל {rid} כבר קיים" + (" (נמחק — ניתן לשחזר)" if _rule_def(s, p.tenant_id, rid) else ""))
    _check_rule(s, p, data)
    note = _note(body.note)
    s.add(RuleDefinition(tenant_id=p.tenant_id, rule_id=rid, version=data["version"], data=data,
                         created_by=p.id, updated_by=p.id))
    audit.record(s, p.tenant_id, p.id, "rule.create", "rule", rid, {"version": data["version"], "after": data, "note": note})
    s.commit()
    return {"ok": True, "id": rid, "version": data["version"]}


@router.put("/api/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleIn, p: Principal = Depends(require("rule.edit")),
                s: Session = Depends(get_session)):
    current = {r.id: r for r in services.rules_for_tenant(s, p.tenant_id)}.get(rule_id)
    if not current:
        raise HTTPException(404, "כלל לא נמצא")
    before = _clean_rule(current.raw)
    before["review_state"] = current.raw.get("yaml_review_state", before.get("review_state"))
    data = {**_clean_rule(body.rule), "id": rule_id}
    if data.get("review_state") in (None, "PROFESSIONALLY_APPROVED"):   # approval is per version: keep the base state
        data["review_state"] = before.get("review_state") or "DRAFT"
    if {k: v for k, v in data.items() if k != "version"} == {k: v for k, v in before.items() if k != "version"}:
        raise HTTPException(422, "לא בוצע שינוי")
    data["version"] = bump_version(before.get("version"))     # a new version needs a new professional approval
    _check_rule(s, p, data)
    note = _note(body.note)
    d = _rule_def(s, p.tenant_id, rule_id)
    if d is None:
        s.add(RuleDefinition(tenant_id=p.tenant_id, rule_id=rule_id, version=data["version"], data=data,
                             created_by=p.id, updated_by=p.id))
    else:
        d.data, d.version, d.deleted, d.updated_by, d.updated_at = data, data["version"], False, p.id, dt.datetime.now(dt.timezone.utc)
    audit.record(s, p.tenant_id, p.id, "rule.update", "rule", rule_id,
                 {"version": data["version"], "before": before, "after": data, "note": note})
    s.commit()
    return {"ok": True, "id": rule_id, "version": data["version"]}


@router.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: str, note: str = "", p: Principal = Depends(require("rule.edit")),
                s: Session = Depends(get_session)):
    current = {r.id: r for r in services.rules_for_tenant(s, p.tenant_id)}.get(rule_id)
    if not current:
        raise HTTPException(404, "כלל לא נמצא")
    note = _note(note)
    d = _rule_def(s, p.tenant_id, rule_id)
    now = dt.datetime.now(dt.timezone.utc)
    if d is None:      # a catalogue (file) rule: a tombstone hides it; restore brings the file version back
        s.add(RuleDefinition(tenant_id=p.tenant_id, rule_id=rule_id, version=str(current.raw.get("version")),
                             data=_clean_rule(current.raw), deleted=True, created_by=p.id, updated_by=p.id))
    else:
        d.deleted, d.updated_by, d.updated_at = True, p.id, now
    audit.record(s, p.tenant_id, p.id, "rule.delete", "rule", rule_id,
                 {"version": current.raw.get("version"), "before": _clean_rule(current.raw), "note": note})
    s.commit()
    return {"ok": True}


@router.post("/api/rules/{rule_id}/restore")
def restore_rule(rule_id: str, body: RuleIn | None = None, p: Principal = Depends(require("rule.edit")),
                 s: Session = Depends(get_session)):
    """File rule: drop the edit/deletion and go back to the catalogue text. Custom rule: undelete."""
    d = _rule_def(s, p.tenant_id, rule_id)
    if d is None:
        raise HTTPException(404, "אין שינוי לשחזר")
    note = _note(body.note if body else "")
    is_file = rule_id in {r.id for r in services.file_rules(p.tenant_id)}
    if is_file:
        s.delete(d)
        action = "rule.restore_file"
    elif d.deleted:
        d.deleted, d.version = False, bump_version(d.version)
        d.data = {**d.data, "version": d.version}
        d.updated_by, d.updated_at = p.id, dt.datetime.now(dt.timezone.utc)
        action = "rule.undelete"
    else:
        raise HTTPException(409, "הכלל פעיל ואינו כלל מהקטלוג")
    audit.record(s, p.tenant_id, p.id, action, "rule", rule_id, {"note": note})
    s.commit()
    return {"ok": True}


@router.get("/api/sources")
def sources(p: Principal = Depends(current_user), s: Session = Depends(get_session)):
    tenant = s.get(Municipality, p.tenant_id)
    show_demo = bool(tenant and tenant.is_demo)   # the fictitious DEMO/1 plan is listed only in a demo tenant
    return [src for src in sources_for_tenant(p.tenant_id).values() if show_demo or src.get("category") != "DEMO"]


@router.get("/api/kb/search")
def kb_search(q: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    res = _gateway_for(s, p.tenant_id).route("Retrieval", "PUBLIC_REGULATION", {"query": q, "k": 6, "tenant_id": p.tenant_id},
                            log=services.gateway_logger(s, p.tenant_id, None, p.id))
    s.commit()
    return {"outcome": res.outcome, "provider": res.provider_id,
            "hits": (res.output or {}).get("hits", []),
            "note_he": "אחזור לקסיקלי (BM25). רכיב הווקטורים מושבת עד לבדיקת מודל embedding מקומי."}


@router.get("/api/regulatory/candidate-conflicts")
def regulatory_candidate_conflicts(p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    """Drafts from different documents worded alike but with different numbers. A lead to verify, not a finding."""
    return reg.candidate_conflicts(s, p.tenant_id)


@router.get("/api/regulatory/entries")
def regulatory_entries(p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    return [reg.serial(r) for r in s.scalars(select(RegulatoryEntry).where(RegulatoryEntry.tenant_id == p.tenant_id))]


@router.post("/api/regulatory/entries", status_code=201)
def regulatory_entry(body: reg.EntryIn, p: Principal = Depends(require("rule.approve")), s: Session = Depends(get_session)):
    """A professional approves a scope or limit quoted exactly from an ingested official source. Not an executable rule."""
    try:
        r = reg.save_entry(s, p.tenant_id, p.id, body)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    audit.record(s, p.tenant_id, p.id, "regulatory.entry.approve", "regulatory_entry", r.id, {"source_sha256": r.data["source_sha256"]})
    s.commit()
    return reg.serial(r)


# ------------------------------------------------------------------ hierarchy, terminology, clauses (Permit360 1.4)

class TermIn(BaseModel):
    concept: str
    term: str
    note_he: str | None = None


@router.get("/api/knowledge/clauses")
def knowledge_clauses(q: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """Clauses in the current authority's chain (authority → committee → district → national), query expanded with
    the synonyms of the concepts it names. Unverified knowledge; never a rule by itself."""
    from .. import hierarchy
    if len((q or "").strip()) < 2:
        raise HTTPException(422, "יש להזין לפחות 2 תווים")
    if s.get(hierarchy.Jurisdiction, f"authority:{p.tenant_id}") is None:
        hierarchy.build(s)
        s.commit()
    return hierarchy.search(s, p.tenant_id, q)


@router.get("/api/knowledge/hierarchy")
def knowledge_hierarchy(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from .. import hierarchy
    from ..models import RegulatoryClause
    scope = hierarchy.chain(s, p.tenant_id)
    counts = dict(s.execute(select(RegulatoryClause.jurisdiction_id, func.count()).where(RegulatoryClause.jurisdiction_id.in_(scope),
                  RegulatoryClause.verification != "EMPTY").group_by(RegulatoryClause.jurisdiction_id)).all())
    return [{"id": j.id, "kind": j.kind, "name_he": j.name_he, "clauses": counts.get(j.id, 0)}
            for j in (s.get(hierarchy.Jurisdiction, x) for x in scope) if j]


@router.get("/api/terminology")
def terminology(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from ..models import Term
    out: dict = {}
    for t in s.scalars(select(Term).order_by(Term.concept, Term.id)):
        c = out.setdefault(t.concept, {"concept": t.concept, "label_he": None, "terms": []})
        c["label_he"] = c["label_he"] or t.label_he
        c["terms"].append(t.term)
    return list(out.values())


@router.post("/api/terminology", status_code=201)
def terminology_add(body: TermIn, p: Principal = Depends(require("rule.edit")), s: Session = Depends(get_session)):
    """Add a surface form to a concept (or a new concept). Shared vocabulary for search and topic tagging."""
    from ..models import Term
    concept, term = body.concept.strip(), body.term.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,59}", concept) or not (1 < len(term) <= 120):
        raise HTTPException(422, "מושג: אותיות לטיניות קטנות וקו תחתון; מונח: 2–120 תווים")
    if s.scalars(select(Term).where(Term.concept == concept, Term.term == term)).first():
        raise HTTPException(409, "המונח כבר קיים")
    first = not s.scalars(select(Term).where(Term.concept == concept)).first()
    s.add(Term(concept=concept, term=term, label_he=term if first else None, note_he=body.note_he, created_by=p.id))
    audit.record(s, p.tenant_id, p.id, "terminology.add", "term", concept, {"term": term})
    s.commit()
    return {"concept": concept, "term": term}
