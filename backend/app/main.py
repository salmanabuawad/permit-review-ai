"""FastAPI application — REST API (OpenAPI at /api/docs)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import __version__, audit, metrics, services
from .ai.gateway import AIGateway
from .config import settings
from .db import Base, engine, get_session
from .ingest.files import IntakeError
from .ingest.pdf import render_page_png
from .knowledge import load_sources, search
from .models import (AIPolicyRow, AuditEvent, CadEntity, CaseFile, CheckRun, Finding, InferenceCost, Municipality,
                     PermitCase, RuleApproval, User)
from .reports import build_report, render_pdf
from .security import PERMISSIONS, ROLES, Principal, current_user, require

app = FastAPI(title="Bnei Brak Permit Review AI — POC", version=__version__,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                   allow_headers=["*"])


@app.on_event("startup")
def _startup():
    Base.metadata.create_all(engine)


PERMIT_TYPES = {
    "addition_extension": "תוספת בנייה — הרחבת דירה/אגף",
    "addition_balcony": "תוספת מרפסת",
    "addition_sukkah": "מרפסת סוכה",
    "roof_room_addition": "חדר גג (תכנית תוספת זכויות)",
}
TRACKS = {
    "regular_permit": "בקשה להיתר (מסלול רגיל)",
    "policy_2026_roof_rights": "תכנית לתוספת זכויות — מדיניות 13.1.2026",
}
STAGES = {"permit_request": "בקשה להיתר", "plan_review": "בדיקת תכנית"}
ZONES = {"residential_A": "מגורים א׳", "residential_B": "מגורים ב׳", "residential_B1": "מגורים ב׳1",
         "residential_C": "מגורים ג׳"}
CASE_STATUSES = {"INTAKE": "קליטה", "IN_REVIEW": "בבדיקה", "RETURNED_FOR_COMPLETION": "הוחזר להשלמות",
                 "WAITING_EXTERNAL": "ממתין לגורם חוץ",
                 "REVIEWER_APPROVED": "אושר ע\"י בודק", "CLOSED": "סגור"}


def get_case(s: Session, p: Principal, case_id: str) -> PermitCase:
    c = s.get(PermitCase, case_id)
    if not c or c.tenant_id != p.tenant_id:          # tenant isolation
        raise HTTPException(404, "תיק לא נמצא")
    return c


def case_dict(c: PermitCase, with_files=True) -> dict:
    last = c.runs[-1] if c.runs else None
    d = {"id": c.id, "case_number": c.case_number, "title": c.title, "is_demo": c.is_demo,
         "permit_type": c.permit_type, "track": c.track, "stage": c.stage, "gush": c.gush, "helka": c.helka,
         "address": c.address, "zone": c.zone, "applicable_plans": c.applicable_plans, "declared": c.declared,
         "status": c.status, "assigned_to": c.assigned_to, "sla_due": c.sla_due.isoformat() if c.sla_due else None,
         "locked_version": c.locked_version, "created_at": c.created_at.isoformat(),
         "last_run": None if not last else {"id": last.id, "version": last.version, "summary": last.summary,
                                            "at": last.started_at.isoformat(), "duration_ms": last.duration_ms,
                                            "locked": last.locked}}
    if with_files:
        d["files"] = [{"id": f.id, "filename": f.filename, "doc_type": f.doc_type, "kind": f.kind,
                       "suggested_doc_type": f.suggested_doc_type, "sha256": f.sha256, "size_bytes": f.size_bytes,
                       "version": f.version, "ingest_status": f.ingest_status, "ingest_report": f.ingest_report,
                       "av_status": f.av_status, "signature_status": f.signature_status, "lifecycle": f.lifecycle,
                       "uploaded_at": f.uploaded_at.isoformat()} for f in sorted(c.files, key=lambda f: f.uploaded_at)]
    return d


# ------------------------------------------------------------------ meta / auth

@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "env": settings.environment,
            "integrations_enabled": settings.integrations_enabled}


@app.get("/api/me")
def me(p: Principal = Depends(current_user)):
    return {**p.__dict__, "role_he": ROLES[p.role]["label_he"],
            "permissions": sorted(k for k, v in PERMISSIONS.items() if p.role in v)}


@app.get("/api/users")
def users(s: Session = Depends(get_session)):
    """Demo user switcher (POC only — production uses SSO)."""
    return [{"id": u.id, "tenant_id": u.tenant_id, "display_name": u.display_name, "role": u.role,
             "role_he": ROLES[u.role]["label_he"]} for u in s.scalars(select(User))]


@app.get("/api/meta")
def meta():
    return {"permit_types": PERMIT_TYPES, "tracks": TRACKS, "stages": STAGES, "zones": ZONES,
            "doc_types": services.DOC_TYPES_HE, "case_statuses": CASE_STATUSES, "roles": ROLES}


# ------------------------------------------------------------------ cases

class CaseIn(BaseModel):
    case_number: str
    title: str
    permit_type: str
    track: str = "regular_permit"
    stage: str = "permit_request"
    gush: str | None = None
    helka: str | None = None
    address: str | None = None
    zone: str | None = None
    applicable_plans: list[str] = []
    declared: dict = {}


@app.get("/api/cases")
def list_cases(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    cs = s.scalars(select(PermitCase).where(PermitCase.tenant_id == p.tenant_id)
                   .order_by(PermitCase.created_at.desc()))
    return [case_dict(c, with_files=False) for c in cs]


@app.post("/api/cases")
def create_case(body: CaseIn, p: Principal = Depends(require("case.create")), s: Session = Depends(get_session)):
    if body.permit_type not in PERMIT_TYPES or body.track not in TRACKS:
        raise HTTPException(422, "סוג בקשה/מסלול לא מוכר")
    tenant = s.get(Municipality, p.tenant_id)
    c = PermitCase(tenant_id=p.tenant_id, is_demo=bool(tenant and tenant.is_demo), sla_due=services.sla_default(),
                   **body.model_dump())
    s.add(c)
    s.flush()
    audit.record(s, p.tenant_id, p.id, "case.create", "permit_case", c.id, body.model_dump())
    s.commit()
    return case_dict(c)


@app.get("/api/cases/{case_id}")
def get_case_api(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    return case_dict(get_case(s, p, case_id))


class DeclaredIn(BaseModel):
    declared: dict | None = None
    zone: str | None = None
    applicable_plans: list[str] | None = None
    track: str | None = None
    stage: str | None = None


@app.patch("/api/cases/{case_id}")
def patch_case(case_id: str, body: DeclaredIn, p: Principal = Depends(require("case.upload")),
               s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    if c.locked_version is not None:
        raise HTTPException(409, "התיק נעול")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(c, k, {**c.declared, **v} if k == "declared" else v)
    audit.record(s, p.tenant_id, p.id, "case.update", "permit_case", c.id, changes)
    s.commit()
    return case_dict(c)


@app.post("/api/cases/{case_id}/files")
async def upload(case_id: str, file: UploadFile = File(...), doc_type: str = Form(...),
                 declared_units_m: float | None = Form(None), p: Principal = Depends(require("case.upload")),
                 s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    if c.locked_version is not None:
        raise HTTPException(409, "התיק נעול")
    if doc_type not in services.DOC_TYPES_HE:
        raise HTTPException(422, "סוג מסמך לא מוכר")
    data = await file.read()
    try:
        cf = services.ingest_file(s, c, file.filename or "upload", data, doc_type, p.id, declared_units_m)
    except IntakeError as e:
        s.rollback()
        raise HTTPException(422, str(e)) from e
    s.commit()
    return case_dict(c)


def _file(s: Session, p: Principal, file_id: str, allow_deleted: bool = False) -> CaseFile:
    f = s.get(CaseFile, file_id)
    if not f or f.tenant_id != p.tenant_id:
        raise HTTPException(404, "קובץ לא נמצא")
    if f.lifecycle == "DELETED" and not allow_deleted:
        raise HTTPException(410, "הקובץ נמחק במחיקה מבוקרת")
    return f


class LifecycleIn(BaseModel):
    state: str      # ACTIVE | ARCHIVED | DELETED
    note: str


@app.post("/api/files/{file_id}/lifecycle")
def file_lifecycle(file_id: str, body: LifecycleIn, p: Principal = Depends(current_user),
                   s: Session = Depends(get_session)):
    f = _file(s, p, file_id, allow_deleted=True)
    need = "file.delete" if body.state == "DELETED" else "case.upload"
    if not p.can(need):
        raise HTTPException(403, f"אין הרשאה: {need}")
    if len(body.note.strip()) < 3:
        raise HTTPException(422, "נדרש נימוק")
    try:
        services.set_file_lifecycle(s, f, body.state, p.id, body.note)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    s.commit()
    return case_dict(f.case)


@app.get("/api/files/{file_id}/page/{n}.png")
def page_png(file_id: str, n: int, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    f = _file(s, p, file_id)
    if f.kind != "pdf":
        raise HTTPException(400, "לא PDF")
    return Response(render_page_png(Path(f.storage_path), n), media_type="image/png")


@app.get("/api/files/{file_id}/download")
def download(file_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    f = _file(s, p, file_id)
    audit.record(s, p.tenant_id, p.id, "file.download", "case_file", f.id, {})
    s.commit()
    return FileResponse(f.storage_path, filename=f.filename)


@app.get("/api/cases/{case_id}/geometry")
def geometry(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    ids = [f.id for f in services.latest_files(s, c) if f.kind in ("dxf", "dwg") and f.ingest_status == "OK"]
    feats = []
    for e in s.scalars(select(CadEntity).where(CadEntity.file_id.in_(ids))) if ids else []:
        g = shapely_wkt.loads(e.wkt_m)
        feats.append({"type": "Feature", "geometry": mapping(g),
                      "properties": {"layer": e.layer, "role": e.role, "dxftype": e.dxftype,
                                     "handle": e.source_handle, "via_block": e.via_block}})
    return {"type": "FeatureCollection", "features": feats, "units": "m", "crs": "local drawing coordinates"}


@app.post("/api/cases/{case_id}/run")
def run(case_id: str, p: Principal = Depends(require("case.run")), s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    try:
        r = services.run_checks(s, c, p.id)
    except PermissionError as e:
        raise HTTPException(409, str(e)) from e
    s.commit()
    return {"run_id": r.id, "version": r.version, "duration_ms": r.duration_ms, "summary": r.summary}


@app.get("/api/cases/{case_id}/runs")
def runs(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    return [{"id": r.id, "version": r.version, "at": r.started_at.isoformat(), "ruleset_hash": r.ruleset_hash,
             "duration_ms": r.duration_ms, "counts": r.summary.get("counts"), "locked": r.locked} for r in c.runs]


def _run(s: Session, p: Principal, run_id: str) -> CheckRun:
    r = s.get(CheckRun, run_id)
    if not r or r.tenant_id != p.tenant_id:
        raise HTTPException(404, "הרצה לא נמצאה")
    return r


@app.get("/api/runs/{run_id}/report/{kind}")
def report(run_id: str, kind: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    if kind not in ("completeness", "rights", "reviewer"):
        raise HTTPException(404)
    r = _run(s, p, run_id)
    return build_report(s, r.case, r, kind)


@app.get("/api/runs/{run_id}/pdf/{kind}")
def report_pdf(run_id: str, kind: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    if kind not in ("completeness", "rights", "reviewer"):
        raise HTTPException(404)
    r = _run(s, p, run_id)
    rep = build_report(s, r.case, r, kind)
    pdf = render_pdf(s, r.case, rep)
    audit.record(s, p.tenant_id, p.id, "report.export", "check_run", r.id, {"kind": kind, "format": "pdf"})
    s.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{kind}_{r.case.case_number}_v{r.version}.pdf"'})


class DecisionIn(BaseModel):
    decision: str     # CONFIRMED | OVERRIDDEN
    note: str


@app.post("/api/findings/{finding_id}/decision")
def decide(finding_id: str, body: DecisionIn, p: Principal = Depends(require("finding.decide")),
           s: Session = Depends(get_session)):
    f = s.get(Finding, finding_id)
    if not f or f.tenant_id != p.tenant_id:
        raise HTTPException(404)
    if f.run.locked:
        raise HTTPException(409, "הגרסה נעולה")
    if body.decision not in ("CONFIRMED", "OVERRIDDEN"):
        raise HTTPException(422)
    if body.decision == "OVERRIDDEN" and len(body.note.strip()) < 5:
        raise HTTPException(422, "דחיית ממצא מחייבת נימוק")
    f.reviewer_decision, f.reviewer_note, f.reviewer_id = body.decision, body.note, p.id
    audit.record(s, p.tenant_id, p.id, f"finding.{body.decision.lower()}", "finding", f.id,
                 {"rule_id": f.rule_id, "status": f.status, "note": body.note})
    s.commit()
    return {"ok": True}


class StatusIn(BaseModel):
    status: str
    note: str = ""
    assigned_to: str | None = None


@app.post("/api/cases/{case_id}/workflow")
def workflow(case_id: str, body: StatusIn, p: Principal = Depends(current_user), s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    if body.status == "LOCK":
        if not p.can("case.lock"):
            raise HTTPException(403)
        try:
            services.lock_case(s, c, p.id)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
    elif body.status == "ASSIGN":
        if not p.can("case.assign"):
            raise HTTPException(403)
        u = s.get(User, body.assigned_to or "")
        if not u or u.tenant_id != p.tenant_id or u.role != "reviewer":
            raise HTTPException(422, "בודק לא תקין")
        c.assigned_to = u.id
        audit.record(s, p.tenant_id, p.id, "case.assign", "permit_case", c.id, {"to": u.id})
    elif body.status in ("RETURNED_FOR_COMPLETION", "IN_REVIEW", "WAITING_EXTERNAL", "CLOSED"):
        if not p.can("case.run"):
            raise HTTPException(403)
        if c.locked_version is not None and body.status != "CLOSED":
            raise HTTPException(409, "התיק נעול")
        c.status = body.status
        audit.record(s, p.tenant_id, p.id, "case.status", "permit_case", c.id, {"status": body.status, "note": body.note})
    else:
        raise HTTPException(422)
    s.commit()
    return case_dict(c)


@app.get("/api/cases/{case_id}/export")
def export_case(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """Open-format export (JSON) of a case with all runs and findings — no vendor lock-in."""
    c = get_case(s, p, case_id)
    data = case_dict(c)
    data["runs"] = [build_report(s, c, r, "reviewer") for r in c.runs]
    audit.record(s, p.tenant_id, p.id, "case.export", "permit_case", c.id, {})
    s.commit()
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="case_{c.case_number}.json"'})


# ------------------------------------------------------------------ rules / knowledge

@app.get("/api/rules")
def rules(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    rs = services.rules_for_tenant(s, p.tenant_id)
    sources = load_sources()
    out = []
    for r in rs:
        raw = dict(r.raw)
        raw["sources_resolved"] = [{**c, "source": sources.get(c.get("source_id"), {})} for c in raw.get("sources", [])]
        out.append(raw)
    return out


class ApproveIn(BaseModel):
    decision: str = "APPROVED"     # APPROVED | REVOKED
    note: str


@app.post("/api/rules/{rule_id}/approval")
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


@app.get("/api/sources")
def sources(p: Principal = Depends(current_user), s: Session = Depends(get_session)):
    tenant = s.get(Municipality, p.tenant_id)
    show_demo = bool(tenant and tenant.is_demo)   # the fictitious DEMO/1 plan is listed only in a demo tenant
    return [src for src in load_sources().values() if show_demo or src.get("category") != "DEMO"]


@app.get("/api/kb/search")
def kb_search(q: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    res = AIGateway().route("Retrieval", "PUBLIC_REGULATION", {"query": q, "k": 6},
                            log=services.gateway_logger(s, p.tenant_id, None, p.id))
    s.commit()
    return {"outcome": res.outcome, "provider": res.provider_id,
            "hits": (res.output or {}).get("hits", []),
            "note_he": "אחזור לקסיקלי (BM25). רכיב הווקטורים מושבת עד לבדיקת מודל embedding מקומי."}


# ------------------------------------------------------------------ AI settings

def _gateway_for(s: Session, tenant: str) -> AIGateway:
    ov = [{"task": r.task, "data_class": r.data_class, "mode": r.mode, "providers": r.provider_order}
          for r in s.scalars(select(AIPolicyRow).where(AIPolicyRow.tenant_id == tenant).order_by(AIPolicyRow.id.desc()))]
    return AIGateway(overrides=ov)


@app.get("/api/ai")
def ai_settings(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    gw = _gateway_for(s, p.tenant_id)
    pols = []
    seen = set()
    for pol in gw.overrides + gw.policy["policies"]:
        key = (pol["task"], pol["data_class"])
        if key in seen:
            continue
        seen.add(key)
        pols.append({**pol, "provider_checks": {pid: gw.check_provider(pid, pol["task"], pol["data_class"])
                                                for pid in pol["providers"]}})
    return {"providers": gw.providers(), "data_classes": gw.policy["data_classes"], "policies": pols}


class PolicyIn(BaseModel):
    task: str
    data_class: str
    mode: str
    providers: list[str]


@app.put("/api/ai/policy")
def set_policy(body: PolicyIn, p: Principal = Depends(require("ai.configure")), s: Session = Depends(get_session)):
    gw = _gateway_for(s, p.tenant_id)
    if body.mode not in ("LOCAL", "CLOUD", "HYBRID"):
        raise HTTPException(422)
    blocked = {pid: gw.check_provider(pid, body.task, body.data_class) for pid in body.providers}
    if body.mode == "LOCAL" and any(gw.providers().get(pid, {}).get("kind") == "CLOUD" for pid in body.providers):
        raise HTTPException(422, "מצב LOCAL אינו יכול לכלול ספק ענן")
    s.add(AIPolicyRow(tenant_id=p.tenant_id, task=body.task, data_class=body.data_class, mode=body.mode,
                      provider_order=body.providers, approved_by=p.id, approved_at=dt.datetime.now(dt.timezone.utc)))
    audit.record(s, p.tenant_id, p.id, "ai.policy.update", "ai_policy", f"{body.task}/{body.data_class}",
                 {**body.model_dump(), "provider_checks": blocked})
    s.commit()
    return {"ok": True, "provider_checks": blocked}


@app.get("/api/integrations")
def integrations():
    data = yaml.safe_load((settings.knowledge_dir / "integrations.yaml").read_text(encoding="utf-8"))
    return [{**i, "enabled": False, "connected": False} for i in data["integrations"]]


# ------------------------------------------------------------------ dashboard / audit

@app.get("/api/dashboard")
def dashboard(p: Principal = Depends(require("dashboard.read")), s: Session = Depends(get_session)):
    t = p.tenant_id
    by_status = dict(s.execute(select(PermitCase.status, func.count()).where(PermitCase.tenant_id == t)
                               .group_by(PermitCase.status)).all())
    by_reviewer = dict(s.execute(select(PermitCase.assigned_to, func.count()).where(PermitCase.tenant_id == t)
                                 .group_by(PermitCase.assigned_to)).all())
    now = dt.datetime.now(dt.timezone.utc)
    overdue = 0
    for c in s.scalars(select(PermitCase).where(PermitCase.tenant_id == t)):
        due = c.sla_due.replace(tzinfo=dt.timezone.utc) if c.sla_due and c.sla_due.tzinfo is None else c.sla_due
        if due and due < now and c.status not in ("REVIEWER_APPROVED", "CLOSED"):
            overdue += 1
    costs = s.execute(select(InferenceCost.task, InferenceCost.outcome, func.count(), func.sum(InferenceCost.cost_ils),
                             func.avg(InferenceCost.latency_ms)).where(InferenceCost.tenant_id == t)
                      .group_by(InferenceCost.task, InferenceCost.outcome)).all()
    cost_per_case = s.execute(select(InferenceCost.case_id, func.sum(InferenceCost.cost_ils))
                              .where(InferenceCost.tenant_id == t, InferenceCost.case_id.is_not(None))
                              .group_by(InferenceCost.case_id)).all()
    findings = dict(s.execute(select(Finding.status, func.count()).where(Finding.tenant_id == t)
                              .group_by(Finding.status)).all())
    durations = [r for (r,) in s.execute(select(CheckRun.duration_ms).where(CheckRun.tenant_id == t))]
    return {
        "cases_by_status": by_status, "cases_by_reviewer": {k or "unassigned": v for k, v in by_reviewer.items()},
        "sla_overdue": overdue, "findings_by_status": findings,
        "ai_usage": [{"task": a, "outcome": b, "calls": c, "cost_ils": round(d or 0, 4), "avg_latency_ms": round(e or 0)}
                     for a, b, c, d, e in costs],
        "cost_per_case": {k: round(v or 0, 4) for k, v in cost_per_case},
        "run_duration_ms": {"count": len(durations), "max": max(durations, default=0),
                            "avg": round(sum(durations) / len(durations)) if durations else 0},
        "stages": metrics.stage_stats(s, t),
        **metrics.cost_breakdown(s, t),
        "kpi_note_he": "מדדי הקבלה של המכרז (95%/90%/85%) יימדדו מול ground truth של בודקים על 100 תיקי אמת — טרם נמדדו.",
    }


@app.get("/api/audit")
def audit_list(limit: int = 200, p: Principal = Depends(require("audit.read")), s: Session = Depends(get_session)):
    evs = s.scalars(select(AuditEvent).where(AuditEvent.tenant_id == p.tenant_id)
                    .order_by(AuditEvent.id.desc()).limit(min(limit, 1000)))
    ok, bad = audit.verify_chain(s, p.tenant_id)
    return {"chain_ok": ok, "first_bad_id": bad,
            "events": [{"id": e.id, "at": e.at.isoformat(), "actor": e.actor, "action": e.action, "entity": e.entity,
                        "entity_id": e.entity_id, "detail": e.detail, "hash": e.hash[:16]} for e in evs]}
