"""API: source monitor, learning from decisions and the national committee register."""
from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


@router.get("/api/source-monitor")
def source_monitor(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    docs = list(s.scalars(select(SourceDocument).where(SourceDocument.tenant_id == p.tenant_id)))
    drafts: dict[int, dict] = {}
    for doc_id, status, n in s.execute(select(RuleDraft.document_id, RuleDraft.status, func.count())
                                       .where(RuleDraft.tenant_id == p.tenant_id)
                                       .group_by(RuleDraft.document_id, RuleDraft.status)):
        drafts.setdefault(doc_id, {})[status] = n
    last = s.scalars(select(SourceCrawl).where(SourceCrawl.tenant_id == p.tenant_id)
                     .order_by(SourceCrawl.started_at.desc()).limit(1)).first()
    order = {"page": 0, "document": 1, "manual": 2}
    docs.sort(key=lambda d: (order.get(d.kind, 3), d.discovered_from or "", d.title or d.url))
    totals = {k: sum(v.get(k, 0) for v in drafts.values()) for k in ("open", "for_authoring", "dismissed", "superseded")}
    return {"last_crawl": _crawl_dict(last), "documents": [_src_doc_dict(d, drafts) for d in docs],
            "drafts": totals, "hosts": sorted(source_service.allowed_hosts(p.tenant_id, s)),
            "schedule": source_service.schedule_of(s.get(Municipality, p.tenant_id)),
            "schedules": source_service.SCHEDULE_HE,
            "attention": sum(1 for d in docs if d.change_state in ("new", "changed") and not d.acknowledged)}


@router.post("/api/source-monitor/crawl")
def source_crawl(wait: bool = False, p: Principal = Depends(require("source.crawl"))):
    try:   # with a separate crawler the app never fetches: the crawl is queued even when wait is asked
        cid = source_service.start_crawl(SessionLocal, p.tenant_id, p.id, wait=wait and not settings.crawler_separate)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    with SessionLocal() as s:
        return _crawl_dict(s.get(SourceCrawl, cid))


@router.get("/api/learning")
def learning_overview(p: Principal = Depends(require("learning.manage")), s: Session = Depends(get_session)):
    from .. import learning
    from ..models import LearningRecord
    recs = list(s.scalars(select(LearningRecord).where(LearningRecord.tenant_id == p.tenant_id,
                                                       LearningRecord.status != "superseded")
                          .order_by(LearningRecord.id.desc())))
    return {"records": [learning.record_dict(r, s.get(PermitCase, r.case_id)) for r in recs],
            "rule_stats": learning.rule_stats(s, p.tenant_id), "topics": learning.TOPIC_HE}


@router.put("/api/source-monitor/schedule")
def source_schedule(body: ScheduleIn, p: Principal = Depends(require("source.schedule")), s: Session = Depends(get_session)):
    """How often this authority's sources are crawled: on demand only (default), daily or weekly. Administrator only."""
    if body.schedule not in source_service.SCHEDULES:
        raise HTTPException(422, "תזמון לא מוכר")
    org = s.get(Municipality, p.tenant_id)
    old = source_service.schedule_of(org)
    org.settings = {**(org.settings or {}), "source_monitor": {**((org.settings or {}).get("source_monitor") or {}),
                                                               "schedule": body.schedule}}
    audit.record(s, p.tenant_id, p.id, "source.schedule", "municipality", p.tenant_id, {"from": old, "to": body.schedule})
    s.commit()
    return {"schedule": body.schedule}


@router.post("/api/source-monitor/upload")
async def source_upload(file: UploadFile = File(...), document_id: int | None = Form(None), source_id: str | None = Form(None),
                        p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    body = await file.read(source_service.load_config()["max_bytes"] + 1)
    if len(body) > source_service.load_config()["max_bytes"]:
        raise HTTPException(413, "הקובץ גדול מדי")
    try:
        d = source_service.ingest_upload(s, p.tenant_id, p.id, file.filename or "upload", body, file.content_type,
                                         document_id=document_id, source_id=source_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    s.commit()
    return _src_doc_dict(d, {})


@router.get("/api/source-monitor/documents/{doc_id}/file")
def source_file(doc_id: int, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    d = _src_doc(s, p, doc_id)
    if not d.storage_path or not Path(d.storage_path).exists():
        raise HTTPException(404, "אין עותק שמור של המסמך")
    return FileResponse(d.storage_path, media_type=d.content_type or "application/octet-stream")


@router.get("/api/source-monitor/documents/{doc_id}/page/{n}.png")
def source_page(doc_id: int, n: int, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    d = _src_doc(s, p, doc_id)
    if not d.storage_path or not d.page_count or not 1 <= n <= d.page_count:
        raise HTTPException(404)
    return Response(render_page_png(Path(d.storage_path), n, zoom=1.3), media_type="image/png")


@router.post("/api/source-monitor/documents/{doc_id}/acknowledge")
def source_ack(doc_id: int, p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    d = _src_doc(s, p, doc_id)
    d.acknowledged, d.acknowledged_by = True, p.id
    audit.record(s, p.tenant_id, p.id, "source.acknowledge", "source_document", str(d.id),
                 {"sha256": d.sha256, "change_state": d.change_state})
    s.commit()
    return {"ok": True}


@router.get("/api/source-monitor/documents/{doc_id}/drafts")
def source_drafts(doc_id: int, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    d = _src_doc(s, p, doc_id)
    rows = s.scalars(select(RuleDraft).where(RuleDraft.document_id == d.id).order_by(RuleDraft.page, RuleDraft.id))
    return [{"id": r.id, "page": r.page, "section": r.section, "kind": r.kind, "topics": r.topics, "text_he": r.text_he,
             "values": r.values, "status": r.status, "note": r.note, "decided_by": r.decided_by} for r in rows]


@router.post("/api/source-monitor/drafts/{draft_id}")
def source_draft_decide(draft_id: int, body: DraftDecisionIn, p: Principal = Depends(require("source.crawl")),
                        s: Session = Depends(get_session)):
    r = s.get(RuleDraft, draft_id)
    if not r or r.tenant_id != p.tenant_id:
        raise HTTPException(404)
    if body.status not in ("open", "for_authoring", "dismissed"):
        raise HTTPException(422, "מצב לא חוקי")
    r.status, r.note, r.decided_by, r.decided_at = body.status, body.note, p.id, dt.datetime.now(dt.timezone.utc)
    audit.record(s, p.tenant_id, p.id, f"rule_draft.{body.status}", "rule_draft", str(r.id),
                 {"document_id": r.document_id, "page": r.page, "note": body.note})
    s.commit()
    return {"ok": True}


@router.get("/api/source-monitor/drafts.yaml")
def source_drafts_yaml(status: str = "for_authoring", p: Principal = Depends(require("case.read")),
                       s: Session = Depends(get_session)):
    """Rule skeletons for the drafts marked for authoring — a starting point for knowledge/rules, never loaded as-is."""
    sources = load_sources()
    rows = s.execute(select(RuleDraft, SourceDocument).join(SourceDocument, RuleDraft.document_id == SourceDocument.id)
                     .where(RuleDraft.tenant_id == p.tenant_id, RuleDraft.status == status)
                     .order_by(SourceDocument.id, RuleDraft.page, RuleDraft.id)).all()
    rules = []
    for r, d in rows:
        src = sources.get(d.source_id or "", {})
        v = (r.values or [None])[0]
        if r.kind == "numeric_limit" and v:
            check = {"kind": "compare", "operand": "TODO", "operator": v.get("op") or "TODO",
                     "threshold": v["value"], "units": v["unit"]}
        else:
            check = {"kind": "doc_required" if r.kind == "required_document" else "qualitative"}
        rules.append({
            "id": f"DRAFT-{d.source_id or 'SRC' + str(d.id)}-{r.id}",
            "version": "0.0",
            "title_he": r.text_he[:90],
            "legal_level": LEVEL_BY_CATEGORY.get(src.get("category"), "MUNICIPAL_POLICY"),
            "report": "completeness" if r.kind == "required_document" else "reviewer",
            "severity": "medium",
            "review_state": "DRAFT",
            "permit_types": [],
            "stages": ["plan_review"],
            "check": check,
            "sources": [{"source_id": d.source_id or "TODO-register-this-document", "section": r.section,
                         "page": r.page, "quote_he": r.text_he}],
            "exact_clause_he": None,
            "notes": f"Drafted automatically from {d.url} (page {r.page}). Verify the clause against the PDF, "
                     f"complete applicability and check, then move to knowledge/rules. Topics: {', '.join(r.topics)}",
        })
    header = ("# Rule drafts exported from the source monitor — NOT loaded by the rule engine.\n"
              "# Every value was found by a text heuristic; verify against the source PDF before use.\n")
    text = header + yaml.safe_dump({"rules": rules}, allow_unicode=True, sort_keys=False, width=120)
    return Response(text, media_type="text/yaml; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="rule_drafts.yaml"'})


@router.get("/api/committees")
def committees_list(p: Principal = Depends(require("source.crawl")), account: User = Depends(login_account),
                    s: Session = Depends(get_session)):
    from .. import committees
    return {**committees.listing(s), "can_edit": authorities.can_create(account)}


@router.patch("/api/committees/{committee_id}")
def committees_update(committee_id: str, body: CommitteePatch, account: User = Depends(_platform_admin),
                      s: Session = Depends(get_session)):
    from .. import committees
    from ..models import PlanningCommittee
    c = s.get(PlanningCommittee, committee_id)
    if not c:
        raise HTTPException(404, "ועדה לא נמצאה")
    try:
        change = committees.update(s, c, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if change:
        audit.record(s, account.tenant_id, account.id, "committee.update", "planning_committee", c.id, change)
    s.commit()
    return committees.as_dict(s, c)


@router.post("/api/committees/probe")
def committees_probe(body: ProbeIn, account: User = Depends(_platform_admin), s: Session = Depends(get_session)):
    """Queue site probes for the crawler process (public sites only, one request per second)."""
    from .. import committees
    n = committees.queue_probes(s, body.ids)
    audit.record(s, account.tenant_id, account.id, "committee.probe.queue", "planning_committee", None,
                 {"count": n, "ids": (body.ids or [])[:50]})
    s.commit()
    return {"queued": n}


@router.post("/api/committees/fetch")
def committees_fetch(body: ProbeIn, account: User = Depends(_platform_admin), s: Session = Depends(get_session)):
    """Queue fetching of the committees' candidate sources (crawler process, public sites, one request per second)."""
    from .. import committees
    n = committees.queue_fetches(s, body.ids)
    audit.record(s, account.tenant_id, account.id, "committee.fetch.queue", "planning_committee", None,
                 {"count": n, "ids": (body.ids or [])[:50]})
    s.commit()
    return {"queued": n}


@router.get("/api/committees/{committee_id}/documents")
def committee_documents(committee_id: str, p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    from ..models import CommitteeDocument, CommitteeSnapshot
    out = []
    for d in s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == committee_id).order_by(CommitteeDocument.id)):
        snaps = list(s.scalars(select(CommitteeSnapshot).where(CommitteeSnapshot.document_id == d.id).order_by(CommitteeSnapshot.id)))
        last = snaps[-1] if snaps else None
        out.append({"id": d.id, "url": d.url, "title": d.title, "kind": d.kind, "found_on": d.found_on, "status": d.status,
                    "message": d.message, "checked_at": d.checked_at.isoformat() if d.checked_at else None,
                    "versions": len(snaps), "snapshot": last and {"id": last.id, "sha256": last.sha256, "content_type": last.content_type,
                                                                  "size": last.size, "pages": last.pages, "text_status": last.text_status,
                                                                  "fetched_at": last.fetched_at.isoformat()}})
    return out


@router.get("/api/committees/passages")
def committee_passages(q: str, committee_id: str | None = None, mode: str = "hybrid",
                       p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    """Search the text fetched from committee sites (unverified candidates): keyword and local-embedding retrieval
    fused by reciprocal rank (mode=hybrid), or one of them (keyword / semantic). Each hit says what found it."""
    from .. import embeddings as E
    from ..models import CommitteeChunk, CommitteeDocument, CommitteePassage, CommitteeSnapshot, PlanningCommittee
    q = E.normalize_query(q)
    if len(q) < 2:
        raise HTTPException(422, "יש להזין לפחות 2 תווים")
    base = (select(CommitteePassage, CommitteeSnapshot, CommitteeDocument, PlanningCommittee)
            .join(CommitteeSnapshot, CommitteePassage.snapshot_id == CommitteeSnapshot.id)
            .join(CommitteeDocument, CommitteeSnapshot.document_id == CommitteeDocument.id)
            .join(PlanningCommittee, CommitteeDocument.committee_id == PlanningCommittee.id)
            .where(CommitteeDocument.sha256 == CommitteeSnapshot.sha256))
    if committee_id:
        base = base.where(PlanningCommittee.id == committee_id)
    rows, kw, sem, best_chunk = {}, [], [], {}
    if mode in ("hybrid", "keyword"):
        for x, snap, d, c in s.execute(base.where(CommitteePassage.text_he.contains(q, autoescape=True)).limit(50)):
            rows[x.id] = (x, snap, d, c)
            kw.append(x.id)
    if mode in ("hybrid", "semantic"):
        hits = E.semantic(s, q, k=50, committee_id=committee_id)
        if hits:
            chunk_rows = {ch.id: ch for ch in s.scalars(select(CommitteeChunk).where(CommitteeChunk.id.in_([h[0] for h in hits])))}
            for cid, sim in hits:
                ch = chunk_rows.get(cid)
                if ch and ch.passage_id not in best_chunk:
                    best_chunk[ch.passage_id] = (ch, sim)
                    sem.append(ch.passage_id)
            missing = [pid for pid in sem if pid not in rows]
            for x, snap, d, c in s.execute(base.where(CommitteePassage.id.in_(missing))) if missing else []:
                rows[x.id] = (x, snap, d, c)
    out = []
    for pid in E.rrf(kw, sem)[:50]:
        if pid not in rows:
            continue
        x, snap, d, c = rows[pid]
        if pid in kw:
            i = x.text_he.find(q)
            excerpt = x.text_he[max(0, i - 200): i + 300]
        else:
            ch, _ = best_chunk[pid]
            excerpt = x.text_he[ch.start:ch.end]
        out.append({"committee": c.name_he, "committee_id": c.id, "document": d.title or d.url, "url": d.url, "kind": d.kind,
                    "page": x.page, "snapshot_id": snap.id, "excerpt": excerpt, "verification": "UNVERIFIED",
                    "found_by": [n for n, lst in (("keyword", kw), ("semantic", sem)) if pid in lst],
                    "similarity": round(best_chunk[pid][1], 3) if pid in best_chunk else None})
    return out


@router.get("/api/committees/snapshots/{snapshot_id}/file")
def committee_snapshot_file(snapshot_id: int, p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    from fastapi.responses import FileResponse
    from ..committee_docs import store_root
    from ..models import CommitteeSnapshot
    snap = s.get(CommitteeSnapshot, snapshot_id)
    path = store_root() / snap.path if snap else None
    if not snap or not path.resolve().is_relative_to(store_root().resolve()) or not path.exists():
        raise HTTPException(404, "הקובץ לא נמצא")
    return FileResponse(path, media_type=snap.content_type, filename=Path(snap.path).name)
