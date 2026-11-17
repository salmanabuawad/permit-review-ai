"""Case pipeline: ingest files -> facts -> rule engine -> persisted, versioned findings."""
from __future__ import annotations

import datetime as dt
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
from .models import CadEntity, CaseFile, CheckRun, Finding, InferenceCost, Municipality, PermitCase, RuleApproval
from .rules.engine import Rule, evaluate, load_rules, ruleset_hash

RULE_FILES_BY_TENANT = {
    "bnei-brak": ["bnei_brak.yaml", "internal_qa.yaml"],
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
    "planning_regulation": "מסמך תכנוני (תכנית/תקנון)",
    "other": "אחר",
}


def gateway_logger(s: Session, tenant: str, case_id: str | None, user: str | None):
    def _log(r: AIResult):
        s.add(InferenceCost(tenant_id=tenant, case_id=case_id, user_id=user, task=r.task,
                            provider_id=r.provider_id or "-", model_version=r.model_version or "-",
                            outcome=r.outcome, latency_ms=r.latency_ms, units=1, cost_ils=r.cost_ils))
    return _log


# ------------------------------------------------------------------ ingest

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
    prev = s.scalars(select(CaseFile).where(CaseFile.case_id == case.id, CaseFile.doc_type == doc_type)
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
        gw = gateway or AIGateway()
        ai = gw.route("Classification", "CASE_DOCUMENT", {"filename": filename, "text": r.full_text[:20000]},
                      log=gateway_logger(s, case.tenant_id, case.id, user))
        if ai.outcome in ("OK", "FALLBACK") and ai.output and ai.output.get("label"):
            cf.suggested_doc_type = ai.output["label"]
        report["classification"] = {"outcome": ai.outcome, "provider": ai.provider_id, "output": ai.output}
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
    out: dict[str, CaseFile] = {}
    for f in sorted((f for f in case.files if f.lifecycle == "ACTIVE"), key=lambda f: f.version):
        out[f.doc_type + ":" + f.kind] = f
    return list(out.values())


def build_facts(s: Session, case: PermitCase) -> tuple[dict, dict]:
    files_ = latest_files(s, case)
    usable = [f for f in files_ if f.ingest_status not in ("ERROR", "QUARANTINED")]
    ref_date = case.declared.get("submission_date") or case.created_at.date().isoformat()
    facts: dict = {
        "case": {"permit_type": case.permit_type, "track": case.track, "zone": case.zone, "stage": case.stage,
                 "applicable_plans": case.applicable_plans, "reference_date": ref_date,
                 "building_existing": case.declared.get("building_existing",
                                                        case.permit_type.startswith("addition") or
                                                        case.permit_type == "roof_room_addition")},
        "declared": dict(case.declared),
        "docs": {"present": {f.doc_type: True for f in usable}},
        "facts_derived": {},
    }
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

def rules_for_tenant(s: Session, tenant_id: str) -> list[Rule]:
    names = RULE_FILES_BY_TENANT.get(tenant_id, ["internal_qa.yaml"])
    rules = load_rules([settings.knowledge_dir / "rules" / n for n in names])
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


def run_checks(s: Session, case: PermitCase, user: str, gateway: AIGateway | None = None) -> CheckRun:
    if case.locked_version is not None:
        raise PermissionError("התיק נעול לאחר אישור; לא ניתן להריץ בדיקה חדשה על הגרסה הנעולה")
    t0 = time.perf_counter()
    tenant = s.get(Municipality, case.tenant_id)
    rules = rules_for_tenant(s, case.tenant_id)
    facts, measurements = build_facts(s, case)
    results = evaluate(rules, facts, load_sources(), tenant_is_demo=bool(tenant and tenant.is_demo))
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
    gw = gateway or AIGateway()
    draft = gw.route("ReportDraft", "CASE_DOCUMENT", {"findings": [r.as_dict() for r in results]},
                     log=gateway_logger(s, case.tenant_id, case.id, user))
    run.duration_ms = int((time.perf_counter() - t0) * 1000)
    run.summary = {"counts": counts, "facts": {k: v for k, v in facts.items() if k != "measure"},
                   "ai_summary": (draft.output or {}).get("text") if draft.outcome in ("OK", "FALLBACK") else None,
                   "ai_summary_outcome": draft.outcome, "ai_provider": draft.provider_id}
    if case.status in ("INTAKE", "RETURNED_FOR_COMPLETION"):
        case.status = "IN_REVIEW"
    audit.record(s, case.tenant_id, user, "check.run", "check_run", run.id,
                 {"case_id": case.id, "version": ver, "ruleset_hash": run.ruleset_hash, "counts": counts,
                  "duration_ms": run.duration_ms})
    return run


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
