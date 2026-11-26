"""Case pipeline: ingest files -> facts -> rule engine -> persisted, versioned findings."""
from __future__ import annotations

import datetime as dt
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from shapely import wkt as shapely_wkt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .ai.gateway import AIGateway, AIResult
from .config import settings
from .geometry import standard_measurements
from .ingest import cad, excel, files, pdf
from .knowledge import load_sources
from .models import (AIPolicyRow, CadEntity, CaseFile, CheckRun, Finding, InferenceCost, Municipality, PermitCase,
                     RuleApproval, RuleDefinition)
from .rules.derived import derive_completeness_facts, derive_document_facts
from .rules.doc_signals import document_signals
from .rules.engine import Rule, evaluate, load_rules, ruleset_hash

RULE_FILES_BY_TENANT = {
    "bnei-brak": ["bnei_brak.yaml", "internal_qa.yaml"],
    # Hof Ashkelon local committee: plan 633-0723718 (Zikim) rules — drafts until a committee reviewer approves.
    "hof-ashkelon": ["hof_ashkelon.yaml", "internal_qa.yaml"],
    "demo": ["bnei_brak.yaml", "internal_qa.yaml", "demo.yaml"],
}

DOC_TYPES_HE = {
    "application_form": "טופס בקשה להיתר",
    "survey_map": "מפת מדידה",
    "permit_info": "מידע להיתר",
    "architectural_plan": "תכנית הגשה (CAD)",
    "area_table": "טבלת שטחים",
    "existing_building_photos": "תמונות בניין קיים",
    "building_master_plan": "תכנית כוללת לבניין",
    "ownership_docs": "מסמכי בעלות",
    "consents": "הסכמות בעלי זכויות",
    "sections_elevations": "חתכים וחזיתות",
    "committee_protocol": "פרוטוקול ועדה",
    "disabled_committee_approval": "אישור ועדת נכים",
    "inspection_report": "דו\"ח פיקוח",
    "electric_company_approval": "אישור חברת החשמל",
    "antiquities_approval": "אישור רשות העתיקות",
    "professional_license": "רישיון עורך בקשה / מתכנן",
    "reg36_notice_proof": "אסמכתא להודעה לבעלים (תקנה 36)",
    "planning_regulation": "מסמך תכנוני (תכנית/תקנון)",
    "other": "אחר",
}


def ai_provider_settings(s: Session, tenant: str) -> dict:
    m = s.get(Municipality, tenant)
    return dict(((m.settings or {}).get("ai") or {}).get("providers") or {}) if m else {}


def gateway_for(s: Session, tenant: str, bulk: bool = False) -> AIGateway:
    """The tenant's AI gateway: policy overrides and provider settings from the AI settings screen."""
    ov = [{"task": r.task, "data_class": r.data_class, "mode": r.mode, "providers": r.provider_order}
          for r in s.scalars(select(AIPolicyRow).where(AIPolicyRow.tenant_id == tenant).order_by(AIPolicyRow.id.desc()))]
    return AIGateway(overrides=ov, provider_settings=ai_provider_settings(s, tenant), bulk=bulk)


def gateway_logger(s: Session, tenant: str, case_id: str | None, user: str | None):
    def _log(r: AIResult):
        s.add(InferenceCost(tenant_id=tenant, case_id=case_id, user_id=user, task=r.task,
                            provider_id=r.provider_id or "-", model_version=r.model_version or "-",
                            outcome=r.outcome, latency_ms=r.latency_ms,
                            units=(r.tokens_in + r.tokens_out) or 1, cost_ils=r.cost_ils))
    return _log


# ------------------------------------------------------------------ ingest

DWFX_PENDING_HE = "ממתין להמרה במחשב ה-AI (DWFX ← PDF)"
# document-presence rules a submitted drawing package can satisfy (sheets inside the DWFX)
DRAWING_DOC_RULES = {"QA-REQ-SECTIONS", "QA-REQ-ELEVATIONS", "QA-REQ-ARCH-PLANS", "HA-633-DOC-PLANS-100"}
DWFX_CLAIM_TTL_S = 30 * 60       # a claimed conversion that never came back is offered again after this


def converted_pdf_path(cf: CaseFile) -> Path | None:
    """The PDF the AI PC made from a DWFX, if it has come back."""
    p = (cf.ingest_report or {}).get("conversion", {}).get("pdf_path")
    return Path(p) if p and Path(p).exists() else None


def claim_dwfx_conversion(s: Session) -> CaseFile | None:
    """The oldest DWFX waiting for conversion (or whose claim expired), marked as taken by the agent."""
    now = dt.datetime.now(dt.timezone.utc)
    for cf in s.scalars(select(CaseFile).where(CaseFile.kind == "dwfx", CaseFile.lifecycle == "ACTIVE",
                                               CaseFile.ingest_status == "PENDING_CONVERSION")
                        .order_by(CaseFile.uploaded_at)):
        conv = dict((cf.ingest_report or {}).get("conversion") or {})
        claimed = conv.get("claimed_at")
        if claimed and (now - dt.datetime.fromisoformat(claimed)).total_seconds() < DWFX_CLAIM_TTL_S:
            continue
        conv.update(state="converting", claimed_at=now.isoformat(), attempts=conv.get("attempts", 0) + 1)
        cf.ingest_report = {**(cf.ingest_report or {}), "conversion": conv}
        return cf
    return None


def complete_dwfx_conversion(s: Session, cf: CaseFile, pdf_bytes: bytes | None, info: dict, error: str | None) -> None:
    """Take the AI PC's result: store the PDF next to the original DWFX and read it like any PDF (text for search
    and classification). Tables are not extracted: a rendered sheet has no ruled cells, only pixels."""
    conv = dict((cf.ingest_report or {}).get("conversion") or {})
    if error or not pdf_bytes or not pdf_bytes.startswith(b"%PDF-"):
        conv.update(state="failed", error=error or "התוצאה אינה PDF")
        cf.ingest_status = "ERROR"
        cf.ingest_report = {"warnings": [f"המרת DWFX נכשלה: {conv['error']}"], "conversion": conv}
    else:
        out = Path(cf.storage_path).with_suffix(".converted.pdf")
        out.write_bytes(pdf_bytes)
        r = pdf.parse_pdf(out, extract_tables=False)
        report = r.report()
        report["warnings"] = report.get("warnings", []) + [
            "תמונה של השרטוט שהומרה מ-DWFX במחשב ה-AI — לתצוגה ולחיפוש טקסט בלבד, לא נמדדה; המקור הוא קובץ ה-DWFX"]
        conv.update(state="done", pdf_path=str(out), pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                    pdf_bytes=len(pdf_bytes), info=info, converted_at=dt.datetime.now(dt.timezone.utc).isoformat())
        report["conversion"] = conv
        report["signals"] = document_signals(cf.filename, r.full_text)
        cf.ingest_status, cf.ingest_report = ("OK" if r.status in ("OK", "NEEDS_OCR") else r.status), report
    audit.record(s, cf.tenant_id, "ai-agent", "file.convert", "case_file", cf.id,
                 {"from": "dwfx", "state": conv["state"], "error": conv.get("error"), "pdf_sha256": conv.get("pdf_sha256")})

def claim_drawing_read(s: Session) -> CaseFile | None:
    """The oldest converted DWFX plan that the AI PC has not read yet (or whose claim expired)."""
    now = dt.datetime.now(dt.timezone.utc)
    for cf in s.scalars(select(CaseFile).where(CaseFile.kind == "dwfx", CaseFile.lifecycle == "ACTIVE",
                                               CaseFile.doc_type == "architectural_plan", CaseFile.ingest_status == "OK")
                        .order_by(CaseFile.uploaded_at)):
        rep = cf.ingest_report or {}
        read = dict(rep.get("drawing_read") or {})
        if read.get("state") == "done":
            continue
        claimed = read.get("claimed_at")
        if claimed and (now - dt.datetime.fromisoformat(claimed)).total_seconds() < 2 * 3600:
            continue
        read.update(state="reading", claimed_at=now.isoformat(), attempts=read.get("attempts", 0) + 1)
        cf.ingest_report = {**rep, "drawing_read": read}
        return cf
    return None


def complete_drawing_read(s: Session, cf: CaseFile, result: dict | None, error: str | None) -> None:
    """Store what the AI PC read on the plan's sheets, then re-run the case checks so the answers show."""
    rep = dict(cf.ingest_report or {})
    read = dict(rep.get("drawing_read") or {})
    if error or not isinstance(result, dict):
        read.update(state="failed", error=error or "no result")
    else:
        read = {"state": "done", "read_at": dt.datetime.now(dt.timezone.utc).isoformat(), **result}
    cf.ingest_report = {**rep, "drawing_read": read}
    audit.record(s, cf.tenant_id, "ai-agent", "file.drawing_read", "case_file", cf.id,
                 {"state": read["state"], "error": read.get("error"), "height": (read.get("height") or {}).get("value_m")})
    case = s.get(PermitCase, cf.case_id)
    if read["state"] == "done" and case is not None and case.locked_version is None and case.runs:
        s.flush()
        run_checks(s, case, "ai-agent")


def ingest_file(s: Session, case: PermitCase, filename: str, data: bytes, doc_type: str, user: str,
                declared_units_m: float | None = None, gateway: AIGateway | None = None,
                extract_tables: bool = True) -> CaseFile:
    intake = files.store(case.tenant_id, case.id, filename, data)
    dup = s.scalars(select(CaseFile).where(CaseFile.case_id == case.id, CaseFile.sha256 == intake.sha256)).first()
    if dup:
        if dup.lifecycle == "DELETED":
            raise files.IntakeError(f"קובץ זהה ({dup.filename}) נמחק בעבר מהתיק במחיקה מבוקרת; לא ניתן לקלוט אותו מחדש")
        where = " (בארכיון — ניתן לשחזר)" if dup.lifecycle == "ARCHIVED" else ""
        raise files.IntakeError(f"קובץ זהה כבר קיים בתיק ({dup.filename}, גרסה {dup.version}){where}")
    # A new version replaces an earlier file only when type AND filename match. Rishuy Zamin allows several files
    # per requirement (e.g. two letters under "electric company approval"); a differently named file of the same
    # type is a separate document, so content rules see both (application 10000197313: a scanned Bezeq letter
    # had silently superseded the HOT letter for another plot).
    prev = s.scalars(select(CaseFile).where(CaseFile.case_id == case.id, CaseFile.doc_type == doc_type,
                                            CaseFile.filename == filename)
                     .order_by(CaseFile.version.desc())).first()
    cf = CaseFile(tenant_id=case.tenant_id, case_id=case.id, doc_type=doc_type, filename=filename, kind=intake.kind,
                  sha256=intake.sha256, size_bytes=intake.size, storage_path=str(intake.stored_path),
                  av_status=intake.av_status, uploaded_by=user,
                  version=(prev.version + 1) if prev else 1, supersedes_id=prev.id if prev else None)
    s.add(cf)
    s.flush()
    report: dict = {}
    path = Path(cf.storage_path)
    if intake.av_status == "INFECTED":
        cf.ingest_status, report = "QUARANTINED", {"warnings": ["הקובץ סומן נגוע ע\"י סורק האנטי-וירוס"]}
    elif cf.kind == "pdf":
        r = pdf.parse_pdf(path, extract_tables=extract_tables)
        cf.ingest_status, report = r.status, r.report()
        cf.signature_status = "FIELD_PRESENT_NOT_VALIDATED" if r.is_signed else "NO_SIGNATURE_FIELD"
        gw = gateway or gateway_for(s, case.tenant_id)
        ai = gw.route("Classification", "CASE_DOCUMENT", {"filename": filename, "text": r.full_text[:20000]},
                      log=gateway_logger(s, case.tenant_id, case.id, user))
        if ai.outcome in ("OK", "FALLBACK") and ai.output and ai.output.get("label"):
            cf.suggested_doc_type = ai.output["label"]
        report["classification"] = {"outcome": ai.outcome, "provider": ai.provider_id, "output": ai.output}
        report["signals"] = document_signals(filename, r.full_text)
    elif cf.kind in ("dxf", "dwg"):
        dxf_path = path
        if cf.kind == "dwg":
            dxf_path, msg = cad.convert_dwg(path)
            if dxf_path is None:
                cf.ingest_status, report = "NEEDS_CONVERSION", {"warnings": [msg]}
        if dxf_path is not None:
            r = cad.parse_dxf(dxf_path, declared_units_m=declared_units_m)
            cf.ingest_status, report = r.status, r.report()
            for e in r.entities:
                s.add(CadEntity(tenant_id=case.tenant_id, file_id=cf.id, layer=e.layer, role=e.role,
                                dxftype=e.dxftype, wkt_m=e.geom.wkt, closed=e.closed,
                                source_handle=e.handle, via_block=e.via_block))
    elif cf.kind == "xlsx":
        r = excel.parse_area_table(path)
        cf.ingest_status, report = r.status, r.report()
    elif cf.kind == "dwfx":     # converted on the AI PC, never here: see complete_dwfx_conversion
        cf.ingest_status = "PENDING_CONVERSION"
        report = {"warnings": [DWFX_PENDING_HE], "conversion": {"state": "queued"}}
    if "signals" not in report and cf.kind != "pdf":
        report["signals"] = document_signals(filename, None)   # a placeholder is recognisable by name alone
    cf.ingest_report = report
    audit.record(s, case.tenant_id, user, "file.upload", "case_file", cf.id,
                 {"case_id": case.id, "filename": filename, "sha256": cf.sha256, "doc_type": doc_type,
                  "version": cf.version, "ingest_status": cf.ingest_status, "av": cf.av_status})
    return cf


# ------------------------------------------------------------------ facts

def add_months(d: dt.date, n: int) -> dt.date:
    """Calendar-month arithmetic (31.8 + 6 months -> 28/29.2), never a 183-day approximation."""
    import calendar
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))

@dataclass
class _Ent:
    layer: str
    role: str | None
    geom: object
    handle: str | None
    via_block: str | None


def latest_files(s: Session, case: PermitCase) -> list[CaseFile]:
    """The newest ACTIVE version of each document, a document being (doc_type, filename)."""
    out: dict[tuple[str, str], CaseFile] = {}
    for f in sorted((f for f in case.files if f.lifecycle == "ACTIVE"), key=lambda f: f.version):
        out[(f.doc_type, f.filename)] = f
    return list(out.values())


def build_facts(s: Session, case: PermitCase) -> tuple[dict, dict]:
    files_ = latest_files(s, case)
    usable = [f for f in files_ if f.ingest_status not in ("ERROR", "QUARANTINED")]
    # A "יישלח בהמשך" placeholder is not the document: it must not satisfy a doc_required rule.
    real = [f for f in usable if not (f.ingest_report or {}).get("signals", {}).get("placeholder")]
    ref_date = case.declared.get("submission_date") or case.created_at.date().isoformat()
    facts: dict = {
        "case": {"permit_type": case.permit_type, "track": case.track, "zone": case.zone, "stage": case.stage,
                 "applicable_plans": case.applicable_plans, "reference_date": ref_date,
                 "building_existing": case.declared.get("building_existing",
                                                        case.permit_type.startswith("addition") or
                                                        case.permit_type == "roof_room_addition")},
        "declared": dict(case.declared),
        "docs": {"present": {f.doc_type: True for f in real}},
        "facts_derived": derive_completeness_facts(case.title, case.application_type, case.declared),
    }
    facts["facts_derived"].update(derive_document_facts(
        [{"filename": f.filename, "doc_type": f.doc_type, "doc_label_he": DOC_TYPES_HE.get(f.doc_type),
          "signals": (f.ingest_report or {}).get("signals")} for f in usable], case.gush, ref_date))
    convention = cad.load_convention()
    facts["cad"] = {"required_roles": convention["required_roles_by_permit_type"].get(case.permit_type, [])}
    cad_files = [f for f in usable if f.kind in ("dxf", "dwg") and f.ingest_status in ("OK",)]
    measurements = {}
    if cad_files:
        ids = [f.id for f in cad_files]
        ents = [_Ent(e.layer, e.role, shapely_wkt.loads(e.wkt_m), e.source_handle, e.via_block)
                for e in s.scalars(select(CadEntity).where(CadEntity.file_id.in_(ids)))]
        facts["cad"]["roles"] = sorted({e.role for e in ents if e.role})
        measurements = {k: m.as_dict() for k, m in standard_measurements(ents).items()}
    facts["measure"] = measurements
    survey = case.declared.get("survey_map_date")
    if survey:
        try:
            sd, rd = dt.date.fromisoformat(str(survey)), dt.date.fromisoformat(ref_date)
            if sd <= rd:   # a survey dated after the reference date is left unknown -> UNCERTAIN
                facts["facts_derived"]["survey_map_within_6_months"] = rd <= add_months(sd, 6)
                facts["facts_derived"]["survey_map_valid_until"] = add_months(sd, 6).isoformat()
        except ValueError:
            pass
    xl = [f for f in usable if f.kind == "xlsx" and f.ingest_status == "OK"]
    if xl:
        t = xl[-1].ingest_report.get("totals_m2", {})
        facts["facts_derived"]["table_proposed_total_m2"] = round(
            t.get("proposed_main_m2", 0) + t.get("proposed_service_m2", 0), 3)
        facts["facts_derived"]["total_main_after_m2"] = round(
            t.get("existing_main_m2", 0) + t.get("proposed_main_m2", 0), 3)
    return facts, measurements


# ------------------------------------------------------------------ rules

# Shared catalogue rules that do not fit a municipality. Hof Ashkelon receives plans through Rishui Zamin as DWFX
# (a plotted drawing without semantic layers), so the CAD layer-convention check — written for Bnei Brak's draft
# convention — would report "no CAD" on every request.
RULES_EXCLUDED_BY_TENANT = {
    "hof-ashkelon": {"QA-CAD-LAYERS"},
}


def file_rules(tenant_id: str) -> list[Rule]:
    names = RULE_FILES_BY_TENANT.get(tenant_id, ["internal_qa.yaml"])
    excluded = RULES_EXCLUDED_BY_TENANT.get(tenant_id, set())
    rules = [r for r in load_rules([settings.knowledge_dir / "rules" / n for n in names]) if r.id not in excluded]
    for r in rules:
        r.raw["origin"] = "file"
    return rules


def rules_for_tenant(s: Session, tenant_id: str, include_deleted: bool = False) -> list[Rule]:
    """The YAML catalogue with the tenant's rules-screen changes applied (RuleDefinition), then approvals."""
    rules = file_rules(tenant_id)
    file_ids = {r.id for r in rules}
    defs = {d.rule_id: d for d in s.scalars(select(RuleDefinition).where(RuleDefinition.tenant_id == tenant_id))}
    merged = []
    for r in rules:
        d = defs.get(r.id)
        if d is None:
            merged.append(r)
        elif not d.deleted:
            merged.append(Rule({**d.data, "origin": "edited", "file_version": r.raw.get("version")}))
        elif include_deleted:
            merged.append(Rule({**r.raw, "origin": "file", "deleted": True}))
    for rid, d in sorted(defs.items(), key=lambda kv: kv[1].created_at):
        if rid not in file_ids and (not d.deleted or include_deleted):
            merged.append(Rule({**d.data, "origin": "custom", **({"deleted": True} if d.deleted else {})}))
    rules = merged
    approvals = {}
    for a in s.scalars(select(RuleApproval).where(RuleApproval.tenant_id == tenant_id).order_by(RuleApproval.id)):
        approvals[(a.rule_id, a.rule_version)] = a
    for r in rules:
        a = approvals.get((r.id, str(r.raw.get("version"))))
        r.raw["yaml_review_state"] = r.raw.get("review_state")
        if a and a.decision == "APPROVED" and r.raw.get("review_state") not in ("DEMO_FIXTURE", "RETIRED"):
            r.raw["review_state"] = "PROFESSIONALLY_APPROVED"
            r.raw["reviewer"] = a.approved_by
    return rules


KB_PASSAGES_MAX = 6
KB_MIN_SCORE = 4.0       # BM25: below this a "hit" shares only common words with the finding


def case_passages(case: PermitCase, results: list) -> list[dict]:
    """Knowledge passages for the summary: for each open finding (FAIL first, then UNCERTAIN), the best passage of the
    case's own municipality or national sources. A passage is never a finding: it is context the reviewer can open."""
    from .knowledge import search
    order = {"FAIL": 0, "UNCERTAIN": 1}
    open_ = sorted((r.as_dict() for r in results if r.status in order), key=lambda f: order[f["status"]])
    picked: dict[str, dict] = {}
    for f in open_:
        q = " ".join(x for x in (f.get("title_he"), f.get("explanation_he")) if x)
        for h in search(q, k=2, tenant_id=case.tenant_id):
            if h["score"] >= KB_MIN_SCORE and h["id"] not in picked:
                picked[h["id"]] = {k: h.get(k) for k in ("id", "source_id", "source_title_he", "page", "section",
                                                         "text_he", "url", "verification", "score")}
                break
        if len(picked) >= KB_PASSAGES_MAX:
            break
    return list(picked.values())


# What a finding means for the request, in the reviewer's three words: something is missing, something contradicts
# something else, or something is not valid. Stored as a flag (ISSUE_*) on the finding.
ISSUE_BY_RULE = {
    "QA-DOC-PLACEHOLDER": "MISSING", "QA-APPROVAL-PARCEL-MISMATCH": "CONFLICT",
    "QA-APPROVAL-ISSUER-MISMATCH": "INVALID", "QA-IAA-DEMAND-NOT-APPROVAL": "INVALID", "QA-LICENCE-EXPIRED": "INVALID",
}
ISSUE_BY_KIND = {"doc_required": "MISSING", "any_present": "MISSING", "condition": "MISSING", "declared_bool": "INVALID",
                 "consistency": "CONFLICT", "list_empty": "INVALID", "qualitative": "INVALID", "cad_roles": "MISSING"}


def issue_type(rule: Rule | None, r) -> str:
    """MISSING | CONFLICT | INVALID for a finding the documents answer as not met; OPEN when nothing decided it;
    OK / NA otherwise. A rule may set `issue_type` itself."""
    if r.rule_id.startswith("CONFLICT:"):        # two sources give different values for the same fact
        return "CONFLICT"
    result = r.computed_result if r.computed_result in ("PASS", "FAIL", "NA") else r.status
    if result == "PASS":
        return "OK"
    if result == "NA":
        return "NA"
    if result != "FAIL":
        return "OPEN"
    if r.rule_id.startswith("CONFLICT:") or "SOURCE_CONFLICT" in r.flags:
        return "CONFLICT"
    if rule is None:
        return "INVALID"
    if rule.raw.get("issue_type"):
        return rule.raw["issue_type"]
    if r.rule_id in ISSUE_BY_RULE:
        return ISSUE_BY_RULE[r.rule_id]
    kind = rule.check.get("kind")
    if kind == "compare":
        return "MISSING" if "INCOMPLETE" in r.flags else "INVALID"
    return ISSUE_BY_KIND.get(kind, "INVALID")


# ------------------------------------------------------------------ review statuses, licensing stage, decision
STAGES = ("PRELIMINARY_ACCEPTANCE", "SPATIAL_REVIEW", "DECISION", "DESIGN_CONTROL", "PERMIT_ISSUANCE", "COMMENCEMENT",
          "CONSTRUCTION", "COMPLETION")
STAGE_HE = {"PRELIMINARY_ACCEPTANCE": "קליטה מקדמית", "SPATIAL_REVIEW": "בקרה מרחבית", "DECISION": "החלטת רשות הרישוי",
            "DESIGN_CONTROL": "בקרת תכן", "PERMIT_ISSUANCE": "הוצאת היתר", "COMMENCEMENT": "תחילת עבודות",
            "CONSTRUCTION": "ביצוע", "COMPLETION": "תעודת גמר"}
REGISTER_STAGE = (("בקרה מרחבית", "SPATIAL_REVIEW"), ("הגשה", "SPATIAL_REVIEW"), ("קליטה", "PRELIMINARY_ACCEPTANCE"),
                  ("בקרת תכן", "DESIGN_CONTROL"), ("מאושר", "DESIGN_CONTROL"), ("היתר", "CONSTRUCTION"), ("גמר", "COMPLETION"))
EXTERNAL_STATUSES = ("CONFIRMED_DEFECT", "DOCUMENTED_DISCREPANCY")


def licensing_stage(case: PermitCase, register_status: str | None) -> tuple[str, str]:
    """(stage, how it was set): declared on the case, else from the committee register's status, else spatial review."""
    st = (case.declared or {}).get("licensing_stage")
    if st in STAGES:
        return st, "הוצהר בתיק"
    for key, stage in REGISTER_STAGE:
        if register_status and key in register_status:
            return stage, f"לפי סטטוס הבקשה במאגר הוועדה: {register_status}"
    return "SPATIAL_REVIEW", "ברירת מחדל — בקשה שהוגשה נבדקת בבקרה מרחבית"


def review_status(rule: Rule | None, r, issue: str, stage: str) -> str:
    """PASS | CONFIRMED_DEFECT | DOCUMENTED_DISCREPANCY | UNRESOLVED | NOT_CHECKED | NOT_APPLICABLE | FUTURE_STAGE.
    A resolver may set it (flag REVIEW:x). A requirement of a later licensing stage is never a current defect."""
    if issue == "OK":
        return "PASS"
    if issue == "NA":
        return "NOT_APPLICABLE"
    override = next((f.split(":", 1)[1] for f in r.flags if f.startswith("REVIEW:")), None)
    rule_stage = (rule.raw.get("licensing_stage") if rule else None) or "SPATIAL_REVIEW"
    if issue in ("MISSING", "CONFLICT", "INVALID") and STAGES.index(rule_stage) > STAGES.index(stage):
        return "FUTURE_STAGE"
    if override:
        return override
    if issue == "OPEN":
        return "NOT_CHECKED" if "NEEDS_DRAWING_READ" in r.flags or not r.evidence else "UNRESOLVED"
    return "DOCUMENTED_DISCREPANCY" if issue == "CONFLICT" else "CONFIRMED_DEFECT"


def final_decision(results, by_id: dict, coverage: dict | None = None) -> tuple[str, str]:
    """NO_DEFECTS_IDENTIFIED | RETURN_FOR_CORRECTIONS | REJECT_RECOMMENDATION | INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION.
    Rejection needs a substantive basis — a confirmed defect of a rule marked reject_basis; never missing documents,
    an incomplete check or the official register status alone."""
    status = {r.rule_id: next(f[7:] for f in r.flags if f.startswith("STATUS_")) for r in results}
    external = [r for r in results if "EXTERNAL" in r.flags]
    if any(status[r.rule_id] == "CONFIRMED_DEFECT" and ("REJECT_BASIS" in r.flags or
                                                       (by_id.get(r.rule_id) and by_id[r.rule_id].raw.get("reject_basis")))
           for r in external):
        return "REJECT_RECOMMENDATION", "נמצא ליקוי מהותי שאינו ניתן לתיקון במסגרת הבקשה"
    if external:
        return "RETURN_FOR_CORRECTIONS", f"{len(external)} ליקויים ופערים מתועדים מחייבים תיקון או הבהרה"
    open_ = [r for r in results if status[r.rule_id] in ("UNRESOLVED", "NOT_CHECKED")
             and (by_id.get(r.rule_id) and by_id[r.rule_id].severity in ("high", "critical"))]
    if open_:
        return "INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION", f"{len(open_)} בדיקות מהותיות לא הושלמו"
    # an empty or partial check list is never compliance: every required family must be complete
    from .coverage import family_coverage
    cov = coverage if coverage is not None else family_coverage(results)
    if not results or not cov.get("full_compliance_possible"):
        return ("INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION",
                f"{len(cov.get('open') or [])} בדיקות נדרשות לא הושלמו או לא מומשו")
    return "NO_DEFECTS_IDENTIFIED", "לא נמצאו ליקויים בבדיקות שהושלמו"


def run_checks(s: Session, case: PermitCase, user: str, gateway: AIGateway | None = None) -> CheckRun:
    if case.locked_version is not None:
        raise PermissionError("התיק נעול לאחר אישור; לא ניתן להריץ בדיקה חדשה על הגרסה הנעולה")
    t0 = time.perf_counter()
    cpu0 = time.process_time()
    tenant = s.get(Municipality, case.tenant_id)
    rules = rules_for_tenant(s, case.tenant_id)
    facts, measurements = build_facts(s, case)
    # values read from the case's documents (e.g. cell totals from the area table) — never over a declared value
    from .rules.evidence import document_facts, resolve
    usable = [f for f in latest_files(s, case) if f.ingest_status not in ("ERROR", "QUARANTINED")]
    from . import derivation_cache as dcache
    from .rules.evidence import TEXT_ALGORITHM
    cache_before = dcache.stats()
    t_docs = time.perf_counter()

    def _text_cache(sha, compute):
        return dcache.get_or_compute(s, algorithm=TEXT_ALGORITHM[0], version=TEXT_ALGORITHM[1], sha256=sha,
                                     compute=compute)[0]
    docs, doc_facts, area_evidence = document_facts(usable, cache=_text_cache)
    t_docs = time.perf_counter() - t_docs
    from .rules.evidence import drawing_facts
    drawing, drawing_fact_values = drawing_facts(usable)
    for k, v in drawing_fact_values.items():
        doc_facts.setdefault(k, v)
    for k, v in doc_facts.items():
        facts["declared"].setdefault(k, v)
    if doc_facts:
        facts["document_facts"] = doc_facts
    from .rules.evidence import survey_file_date
    survey_date, survey_evidence = (None, []) if case.declared.get("survey_map_date") else survey_file_date(usable)
    if survey_date:            # the survey is no newer than its file: validity is judged from that date
        ref = dt.date.fromisoformat(facts["case"]["reference_date"])
        sd = dt.date.fromisoformat(survey_date)
        if sd <= ref:
            facts["declared"]["survey_map_date"] = survey_date
            facts["facts_derived"]["survey_map_within_6_months"] = ref <= add_months(sd, 6)
            facts["facts_derived"]["survey_map_valid_until"] = add_months(sd, 6).isoformat()
    results = evaluate(rules, facts, load_sources(), tenant_is_demo=bool(tenant and tenant.is_demo))
    for r in results:          # compare rules answered by a value read from a document: show where it was read
        operand = next((x.check.get("operand") for x in rules if x.id == r.rule_id), None) or ""
        key = operand.split(".")[-1]
        if key in doc_facts and key not in case.declared:
            r.evidence = list(r.evidence or []) + (drawing.get("evidence", {}).get(key) or area_evidence)
    resolve(results, docs, case.declared, case.title, doc_facts, area_evidence, drawing, case.gush)
    # a drawing still waiting for conversion on the AI PC may hold the "missing" sheets: never a confirmed absence
    pending = [f.filename for f in usable if f.kind == "dwfx"
               and ((f.ingest_report or {}).get("conversion") or {}).get("state") not in ("done", "converted")
               and not ((f.ingest_report or {}).get("conversion") or {}).get("pdf_path")]
    if pending:
        for r in results:
            if r.rule_id in DRAWING_DOC_RULES and "FAIL" in (r.status, r.computed_result):
                r.status = r.computed_result = "UNCERTAIN"
                r.explanation_he = (r.explanation_he or "") + f" — {DWFX_PENDING_HE}: {', '.join(pending)}."
                r.flags = list(r.flags) + ["NEEDS_DRAWING_READ"]
    guard_single_read_height(results, rules, drawing_fact_values, case.declared)
    for r in results:
        if survey_evidence and r.rule_id == "QA-SURVEY-MAP-AGE" and r.status in ("PASS", "FAIL", "UNCERTAIN"):
            r.evidence = list(r.evidence or []) + survey_evidence
            until = facts["facts_derived"].get("survey_map_valid_until")
            if until:
                r.explanation_he = (f"קובץ המדידה נוצר ב־{dt.date.fromisoformat(survey_date).strftime('%d.%m.%Y')}; "
                                    f"מפת המדידה בתוקף לכל היותר עד {dt.date.fromisoformat(until).strftime('%d.%m.%Y')}, "
                                    f"והבקשה הוגשה ב־{dt.date.fromisoformat(facts['case']['reference_date']).strftime('%d.%m.%Y')}.")
    by_id = {x.id: x for x in rules}
    from .rules.evidence import load_ledger, request_units, Context, find_cell
    register_status = None
    ledger = load_ledger(case.gush, find_cell(docs))
    if ledger:
        units = request_units(Context([], case.declared or {}, case.title or "", None, {}, []))
        rec = next((x for x in ledger["records"] if units and tuple(sorted(x.get("units") or [])) == units), None)
        register_status = rec and rec.get("status")
    stage, stage_how = licensing_stage(case, register_status)
    for r in results:
        rule = by_id.get(r.rule_id)
        issue = issue_type(rule, r)
        status = review_status(rule, r, issue, stage)
        internal = "INTERNAL" in r.flags or (rule is not None and rule.raw.get("external") is False)
        r.flags = ([f for f in r.flags if not f.startswith(("ISSUE_", "STATUS_")) and f != "EXTERNAL"]
                   + ["ISSUE_" + issue, "STATUS_" + status]
                   + (["EXTERNAL"] if status in EXTERNAL_STATUSES and not internal else []))
    from .coverage import disclaimer_he, family_coverage
    coverage = family_coverage(results)
    decision, decision_why = final_decision(results, by_id, coverage)
    ver = (s.scalar(select(func.max(CheckRun.version)).where(CheckRun.case_id == case.id)) or 0) + 1
    run = CheckRun(tenant_id=case.tenant_id, case_id=case.id, version=ver, ruleset_hash=ruleset_hash(rules),
                   input_hashes=[{"file": f.filename, "sha256": f.sha256, "version": f.version}
                                 for f in latest_files(s, case)],
                   measurements=measurements)
    s.add(run)
    s.flush()
    for r in results:
        d = r.as_dict()
        s.add(Finding(tenant_id=case.tenant_id, run_id=run.id, **d))
    counts: dict = {}
    for r in results:
        counts.setdefault(r.report, {}).setdefault(r.status, 0)
        counts[r.report][r.status] += 1
    gw = gateway or gateway_for(s, case.tenant_id)
    passages = case_passages(case, results)
    draft = gw.route("ReportDraft", "CASE_DOCUMENT", {"findings": [r.as_dict() for r in results], "passages": passages},
                     log=gateway_logger(s, case.tenant_id, case.id, user))
    ok = draft.outcome in ("OK", "FALLBACK")
    cited = set((draft.output or {}).get("citations") or []) if ok else set()
    run.duration_ms = int((time.perf_counter() - t0) * 1000)
    cache_after = dcache.stats()
    metrics = run_metrics(usable, run.duration_ms, t_docs, cpu0, draft, cache_before, cache_after)
    regulation = resolve_regulation(s, case, facts)
    review_counts: dict = {}
    for r in results:
        st = next(f[7:] for f in r.flags if f.startswith("STATUS_"))
        review_counts[st] = review_counts.get(st, 0) + 1
    done = sum(v for k, v in review_counts.items() if k not in ("UNRESOLVED", "NOT_CHECKED", "NOT_APPLICABLE", "FUTURE_STAGE"))
    applicable = sum(v for k, v in review_counts.items() if k not in ("NOT_APPLICABLE", "FUTURE_STAGE"))
    run.summary = {"counts": counts, "facts": {k: v for k, v in facts.items() if k != "measure"},
                   "review": {"stage": stage, "stage_he": STAGE_HE[stage], "stage_source": stage_how,
                              "decision": decision, "decision_why": decision_why, "counts": review_counts,
                              "coverage": {"completed": done, "applicable": applicable,
                                           "families": coverage["families"], "open": coverage["open"],
                                           "full_compliance_possible": coverage["full_compliance_possible"],
                                           "inventory_version": coverage["inventory_version"]},
                              "disclaimer_he": disclaimer_he(coverage),
                              "regulation_sources": regulation,     # internal record — never in external reports
                              "external_findings": sum(1 for r in results if "EXTERNAL" in r.flags),
                              "limitations_he": [
                                  ("מקור ג׳ של בדיקת השטחים נמדד לשטחים שבתוך הקירות; סככות ושטחים מקורים מחוץ לקירות לא נמדדו מהתכניות."
                                   if any(r.rule_id == "HA-AREA-FLOORPLANS" and "RESOLVED_FROM_DOCUMENTS" in r.flags or
                                          r.rule_id == "HA-AREA-FLOORPLANS" and any(f == "REVIEW:UNRESOLVED" for f in r.flags)
                                          for r in results)
                                   else "מקור ג׳ של בדיקת השטחים (שחזור מתכניות הקומות) לא בוצע."),
                                  "בדיקות שלא הושלמו: " + str(review_counts.get("UNRESOLVED", 0) + review_counts.get("NOT_CHECKED", 0)) + "."]},
                   "metrics": metrics,
                   "ai_summary": (draft.output or {}).get("text") if draft.outcome in ("OK", "FALLBACK") else None,
                   "ai_summary_outcome": draft.outcome, "ai_provider": draft.provider_id,
                   # passages given to the summary; `cited` = the summary refers to it by its id
                   "kb_passages": [{**{k: v for k, v in p.items() if k != "text_he"}, "cited": p["id"] in cited}
                                   for p in passages]}
    if case.status in ("INTAKE", "RETURNED_FOR_COMPLETION"):
        case.status = "IN_REVIEW"
    audit.record(s, case.tenant_id, user, "check.run", "check_run", run.id,
                 {"case_id": case.id, "version": ver, "ruleset_hash": run.ruleset_hash, "counts": counts,
                  "duration_ms": run.duration_ms})
    return run



def guard_single_read_height(results, rules, drawing_facts: dict, declared: dict) -> int:
    """The height checked is the highest ridge read (never too low), but a value read only once cannot confirm a
    violation: when the twice-read ridge is within the limit, the excess is unresolved until the sheet is checked."""
    corroborated = drawing_facts.get("building_height_corroborated_m")
    if corroborated is None or "building_height_m" in declared:
        return 0
    operands = {x.id: x.check.get("operand") or "" for x in rules}
    n = 0
    for r in results:
        if (operands.get(r.rule_id, "").endswith(".building_height_m") and "FAIL" in (r.status, r.computed_result)
                and r.threshold is not None and corroborated <= r.threshold):
            r.status = r.computed_result = "UNCERTAIN"
            r.explanation_he = (f"רום רכס הגג שנקרא פעמיים: +{corroborated:.2f} מ׳ (בתחום ≤ {r.threshold:.2f}); "
                                f"ערך גבוה יותר (+{drawing_facts['building_height_m']:.2f}) נקרא פעם אחת בלבד "
                                "ואינו מאומת — נדרשת בדיקת הגיליון לפני קביעה.")
            r.flags = list(r.flags) + ["REVIEW:UNRESOLVED", "INTERNAL", "NEEDS_DRAWING_READ"]
            n += 1
    return n

def resolve_regulation(s: Session, case: PermitCase, facts: dict) -> dict:
    """ApplicableRegulationResolver for the case (internal record). Cached by property + knowledge-base version."""
    from . import derivation_cache as dcache
    from .rules.applicability import AppContext, ApplicableRegulationResolver
    try:
        decl = case.declared or {}
        ref = dt.date.fromisoformat(facts["case"]["reference_date"])
        lot = decl.get("lot") or decl.get("plot")
        app = AppContext(case.case_number, ref, list(case.applicable_plans or []), case.gush, case.helka,
                         str(lot) if lot else None, decl.get("main_use") or "מגורים", activity=decl.get("request_text", ""))
        rr = ApplicableRegulationResolver()

        def cache(key, compute):
            return dcache.get_or_compute(s, algorithm="applicability", version="1",
                                         sha256=hashlib.sha256(key.encode()).hexdigest(), compute=compute)[0]
        res = rr.resolve(app, cache=cache)
        return {"sources": [{k: x.__dict__[k] for k in ("plan", "kind", "status", "reason")} for x in res.sources],
                "unresolved": res.unresolved, "kb_version": rr.kb_version()}
    except Exception as e:                        # resolution never breaks a run; the failure is recorded
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def run_metrics(files, duration_ms: int, docs_s: float, cpu0: float, draft, cache_before: dict, cache_after: dict) -> dict:
    """V9 §Output: wall time, CPU, model tokens / cost, cache hits and the AI-PC work behind the run's inputs.
    GPU work happens on the AI PC (drawing reader, image model); its time is taken from each file's own record."""
    drawing = []
    for f in files:
        rep = f.ingest_report or {}
        dr = rep.get("drawing_read") or {}
        conv = rep.get("conversion") or {}
        if dr or conv:
            drawing.append({"file": f.filename, "sha256": f.sha256,
                            "drawing_read_s": dr.get("seconds"), "drawing_model": dr.get("model"),
                            "image_calls": dr.get("calls"), "conversion_s": conv.get("seconds"),
                            "geometry": {k: (dr.get(k) or {}).get("algorithm") for k in ("area_geometry", "floor_geometry")
                                         if dr.get(k)}})
    return {"wall_ms": duration_ms, "documents_text_s": round(docs_s, 2),
            "cpu_s": round(time.process_time() - cpu0, 2),
            "llm": {"provider": getattr(draft, "provider_id", None), "outcome": getattr(draft, "outcome", None),
                    "tokens_in": getattr(draft, "tokens_in", 0), "tokens_out": getattr(draft, "tokens_out", 0),
                    "latency_ms": getattr(draft, "latency_ms", 0), "cost_ils": getattr(draft, "cost_ils", 0.0)},
            "cache": {"hits": cache_after["hits"] - cache_before["hits"],
                      "misses": cache_after["misses"] - cache_before["misses"]},
            "ai_pc": drawing,
            "gpu_on_this_host": False}


def lock_case(s: Session, case: PermitCase, user: str) -> None:
    if not case.runs:
        raise ValueError("אין הרצת בדיקה לנעילה")
    last = case.runs[-1]
    undecided = [f for f in last.findings if f.status in ("FAIL", "UNCERTAIN") and not f.reviewer_decision]
    if undecided:
        raise ValueError(f"{len(undecided)} ממצאים ממתינים להחלטת בודק — לא ניתן לנעול")
    last.locked = True
    case.locked_version = last.version
    case.status = "REVIEWER_APPROVED"
    audit.record(s, case.tenant_id, user, "case.lock", "permit_case", case.id, {"run_version": last.version})


LIFECYCLE_STATES = ("ACTIVE", "ARCHIVED", "DELETED")


def set_file_lifecycle(s: Session, cf: CaseFile, state: str, user: str, note: str) -> None:
    """ACTIVE <-> ARCHIVED is reversible. DELETED is final: the stored bytes are removed, while the
    row (name, sha256, versions) and the audit trail are kept as evidence of what was deleted."""
    if state not in LIFECYCLE_STATES:
        raise ValueError("מצב לא מוכר")
    if cf.lifecycle == "DELETED":
        raise ValueError("הקובץ נמחק — לא ניתן לשנות את מצבו")
    if cf.case.locked_version is not None:
        raise ValueError("התיק נעול; לא ניתן לשנות מסמכים בגרסה נעולה")
    prev = cf.lifecycle
    if state == "DELETED":
        try:
            Path(cf.storage_path).unlink(missing_ok=True)
        except OSError as exc:
            raise ValueError(f"מחיקת הקובץ נכשלה: {exc}") from exc
        s.query(CadEntity).filter(CadEntity.file_id == cf.id).delete()
    cf.lifecycle = state
    audit.record(s, cf.tenant_id, user, f"file.{state.lower()}", "case_file", cf.id,
                 {"case_id": cf.case_id, "filename": cf.filename, "sha256": cf.sha256, "from": prev, "note": note})


def sla_default(now: dt.datetime | None = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(days=14)
