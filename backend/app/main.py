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

from . import __version__, audit, batch_import, metrics, services
from .ai.gateway import AIGateway
from .config import settings
from .db import Base, SessionLocal, engine, get_session, run_migrations
from .ingest.files import IntakeError
from .ingest.pdf import render_page_png
from .knowledge import load_sources, search
from .models import (AIPolicyRow, AuditEvent, CadEntity, CaseFile, CheckRun, CommitteeDecision, ExtractedField,
                     Finding, ImportBatch, InferenceCost, Municipality, PlanningComment, SourceReference,
                     PermitCase, RuleApproval, RuleDraft, SourceCrawl, SourceDocument, User)
from .reports import build_report, render_pdf
from .source_monitor import service as source_service
from .security import PERMISSIONS, ROLES, Principal, current_user, require

app = FastAPI(title="Bnei Brak Permit Review AI — POC", version=__version__,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                   allow_headers=["*"])


@app.on_event("startup")
def _startup():
    run_migrations()


PERMIT_TYPES = {
    "addition_extension": "תוספת בנייה — הרחבת דירה/אגף",
    "addition_balcony": "תוספת מרפסת",
    "addition_sukkah": "מרפסת סוכה",
    "roof_room_addition": "תוספת חדרי גג",
    "new_building": "בנייה חדשה / הריסה ובנייה",
    "permit_changes": "שינויים להיתר קיים",
    "parcel_unification": "איחוד וחלוקת חלקות",
    "other": "אחר",
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


class RecheckIn(BaseModel):
    case_ids: list[str] | None = None      # None = every case of the tenant


RECHECK_MAX = 500


@app.post("/api/cases/recheck")
def recheck(body: RecheckIn, p: Principal = Depends(require("case.run")), s: Session = Depends(get_session)):
    """Re-run the rule checks on many cases (e.g. after a rule was approved or changed).
    Locked cases and cases without documents are skipped with a reason; one failure does not stop the rest."""
    q = select(PermitCase).where(PermitCase.tenant_id == p.tenant_id)
    if body.case_ids is not None:
        if not body.case_ids:
            raise HTTPException(422, "לא נבחרו תיקים")
        q = q.where(PermitCase.id.in_(body.case_ids))
    cases = list(s.scalars(q.order_by(PermitCase.created_at)))
    if len(cases) > RECHECK_MAX:
        raise HTTPException(422, f"ניתן להריץ בדיקה חוזרת על עד {RECHECK_MAX} תיקים בפעם אחת")
    done, skipped, failed = [], [], []
    for c in cases:
        if c.locked_version is not None:
            skipped.append({"case_id": c.id, "case_number": c.case_number, "reason": "התיק נעול לאחר אישור"})
            continue
        if not services.latest_files(s, c):
            skipped.append({"case_id": c.id, "case_number": c.case_number, "reason": "אין מסמכים בתיק"})
            continue
        try:
            with s.begin_nested():
                r = services.run_checks(s, c, p.id)
            done.append({"case_id": c.id, "case_number": c.case_number, "version": r.version,
                         "counts": r.summary.get("counts")})
        except Exception as e:                       # noqa: BLE001 — report and continue with the next case
            failed.append({"case_id": c.id, "case_number": c.case_number, "reason": str(e)[:300]})
    audit.record(s, p.tenant_id, p.id, "case.recheck_bulk", "permit_case", "*",
                 {"requested": len(cases), "done": len(done), "skipped": len(skipped), "failed": len(failed),
                  "scope": "selected" if body.case_ids is not None else "all"})
    s.commit()
    return {"requested": len(cases), "done": done, "skipped": skipped, "failed": failed}


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


# ------------------------------------------------------------------ document intake (import)

IMPORT_TTL_HOURS = 24
TOKEN_RE = __import__("re").compile(r"^[0-9]{14}-[0-9a-f]{8}$")
REF_RE = __import__("re").compile(r"^[0-9a-f]{12}$")


def _import_dir(tenant: str, token: str | None = None) -> Path:
    base = settings.storage_dir / "_import" / tenant
    return base / token if token else base


def _cleanup_imports(tenant: str) -> None:
    """Uncommitted staging areas expire after IMPORT_TTL_HOURS."""
    import shutil
    base = _import_dir(tenant)
    if not base.exists():
        return
    cutoff = dt.datetime.now().timestamp() - IMPORT_TTL_HOURS * 3600
    for d in base.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


@app.post("/api/import/analyze")
async def import_analyze(files: list[UploadFile] = File(...), p: Principal = Depends(require("case.create")),
                         s: Session = Depends(get_session)):
    """Classify the documents, find the applications and extract their data. Creates no cases."""
    import uuid
    from .intake.pipeline import analyze_package
    _cleanup_imports(p.tenant_id)
    uploads, total = [], 0
    for f in files:
        data = await f.read()
        total += len(data)
        if total > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"סך הקבצים גדול מ־{settings.max_upload_mb}MB")
        uploads.append((f.filename or "upload", data))
    gw = _gateway_for(s, p.tenant_id)
    log = services.gateway_logger(s, p.tenant_id, None, p.id)
    route = lambda task, dc, payload: gw.route(task, dc, payload, log=log)  # noqa: E731
    existing_numbers = {c for (c,) in s.execute(select(PermitCase.case_number).where(PermitCase.tenant_id == p.tenant_id))}
    existing_hashes = {h: n for h, n in s.execute(select(CaseFile.sha256, PermitCase.case_number)
                                                  .join(PermitCase, CaseFile.case_id == PermitCase.id)
                                                  .where(CaseFile.tenant_id == p.tenant_id))}
    try:
        preview, blobs = analyze_package(uploads, route, existing_numbers, existing_hashes)
    except batch_import.ImportError_ as e:
        raise HTTPException(422, str(e)) from e
    token = dt.datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
    d = _import_dir(p.tenant_id, token)
    (d / "blobs").mkdir(parents=True, exist_ok=True)
    for ref, data in blobs.items():
        (d / "blobs" / ref).write_bytes(data)
    (d / "preview.json").write_text(json.dumps(preview, ensure_ascii=False), encoding="utf-8")
    import hashlib
    batch = ImportBatch(tenant_id=p.tenant_id, token=token, created_by=p.id, storage_path=str(d),
                        source_files=[{"name": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in uploads],
                        summary={"analysis": preview["counts"]})
    s.add(batch)
    s.flush()
    audit.record(s, p.tenant_id, p.id, "import.analyze", "import_batch", batch.id,
                 {"files": [n for n, _ in uploads], "counts": preview["counts"]})
    s.commit()
    return {"token": token, "batch_id": batch.id, **preview}


@app.get("/api/import/{token}/page/{ref}/{n}.png")
def import_page(token: str, ref: str, n: int, p: Principal = Depends(require("case.create"))):
    """Render a page of a staged document — the source preview next to an extracted value."""
    if not TOKEN_RE.match(token) or not REF_RE.match(ref):
        raise HTTPException(404)
    path = _import_dir(p.tenant_id, token) / "blobs" / ref
    if not path.exists():
        raise HTTPException(404, "המסמך לא נמצא או שפג תוקף הייבוא")
    try:
        return Response(render_page_png(path, n, zoom=1.3), media_type="image/png")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, "העמוד לא נמצא") from e


class ImportDocIn(BaseModel):
    ref: str
    include: bool = True
    doc_type: str | None = None


class ImportAppIn(BaseModel):
    key: str
    include: bool = True
    fields: dict = {}
    documents: list[ImportDocIn] = []


class ImportCommitIn(BaseModel):
    token: str
    applications: list[ImportAppIn]
    run_checks: bool = True


@app.post("/api/import/commit")
def import_commit(body: ImportCommitIn, p: Principal = Depends(require("case.create")),
                  s: Session = Depends(get_session)):
    import shutil
    from .intake.commit import commit_preview
    if not TOKEN_RE.match(body.token):
        raise HTTPException(404, "הייבוא לא נמצא")
    d = _import_dir(p.tenant_id, body.token)
    batch = s.scalars(select(ImportBatch).where(ImportBatch.tenant_id == p.tenant_id, ImportBatch.token == body.token)).first()
    if batch is None or batch.status != "analyzed" or not (d / "preview.json").exists():
        raise HTTPException(404, "הייבוא לא נמצא, כבר בוצע או שפג תוקפו — יש לנתח את הקבצים מחדש")
    preview = json.loads((d / "preview.json").read_text(encoding="utf-8"))
    nums = [(a.fields.get("application_number") or "").strip() for a in body.applications if a.include]
    nums = [n for n in nums if n]
    if len(nums) != len(set(nums)):
        raise HTTPException(422, "מספרי בקשה כפולים בין הבקשות שנבחרו")
    result = commit_preview(s, p.tenant_id, p.id, batch, preview, d / "blobs",
                            [a.model_dump() for a in body.applications], body.run_checks, set(PERMIT_TYPES))
    final = settings.storage_dir / "_batches" / p.tenant_id / batch.id     # keep the original files with the batch
    final.parent.mkdir(parents=True, exist_ok=True)
    s.commit()
    shutil.move(str(d), str(final))
    batch.storage_path = str(final)
    s.commit()
    return result


@app.get("/api/import/batches")
def import_batches(p: Principal = Depends(require("case.create")), s: Session = Depends(get_session)):
    rows = s.scalars(select(ImportBatch).where(ImportBatch.tenant_id == p.tenant_id)
                     .order_by(ImportBatch.created_at.desc()).limit(50))
    return [{"id": b.id, "created_at": b.created_at.isoformat(), "created_by": b.created_by, "status": b.status,
             "files": b.source_files, "summary": b.summary} for b in rows]


@app.get("/api/cases/{case_id}/extracted")
def case_extracted(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """Extracted fields, comments and committee decision of an imported case, with sources."""
    c = get_case(s, p, case_id)
    refs = {}

    def ref(rid):
        if rid is None:
            return None
        if rid not in refs:
            r = s.get(SourceReference, rid)
            refs[rid] = None if r is None else {"file_id": r.file_id, "file": r.file_name, "page": r.page,
                                                 "original_page": r.original_page, "quote": r.quote, "method": r.method,
                                                 "confidence": r.confidence, "provider": r.provider_id}
        return refs[rid]
    fields = [{"field": f.field, "value": f.value.get("v"), "original_value": (f.original_value or {}).get("v"),
               "confidence": f.confidence, "status": f.status, "source": ref(f.source_ref_id)}
              for f in s.scalars(select(ExtractedField).where(ExtractedField.case_id == c.id).order_by(ExtractedField.id))]
    comments = [{"department": x.department, "department_he": x.department_he, "item_no": x.item_no, "text": x.text,
                 "source": ref(x.source_ref_id)}
                for x in s.scalars(select(PlanningComment).where(PlanningComment.case_id == c.id).order_by(PlanningComment.id))]
    decisions = [{"outcome": x.outcome, "text": x.text, "conditions": x.conditions, "meeting_number": x.meeting_number,
                  "meeting_date": x.meeting_date, "item_number": x.item_number, "source": ref(x.source_ref_id)}
                 for x in s.scalars(select(CommitteeDecision).where(CommitteeDecision.case_id == c.id))]
    return {"fields": [f for f in fields if f["field"] != "area"], "areas": [f for f in fields if f["field"] == "area"],
            "comments": comments, "decisions": decisions}


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


# ------------------------------------------------------------------ source monitor (crawl official rule sources)

def _src_doc(s: Session, p: Principal, doc_id: int) -> SourceDocument:
    d = s.get(SourceDocument, doc_id)
    if not d or d.tenant_id != p.tenant_id:
        raise HTTPException(404, "מסמך מקור לא נמצא")
    return d


def _src_doc_dict(d: SourceDocument, drafts: dict) -> dict:
    return {"id": d.id, "url": d.url, "kind": d.kind, "source_id": d.source_id, "title": d.title,
            "discovered_from": d.discovered_from, "first_seen": d.first_seen.isoformat(),
            "last_checked": d.last_checked.isoformat() if d.last_checked else None,
            "fetch_status": d.fetch_status, "http_status": d.http_status, "message": d.message,
            "change_state": d.change_state, "changed_at": d.changed_at.isoformat() if d.changed_at else None,
            "acknowledged": d.acknowledged, "sha256": d.sha256, "content_type": d.content_type, "size": d.size,
            "page_count": d.page_count, "has_file": bool(d.storage_path), "links": len(d.links or []),
            "drafts": drafts.get(d.id, {})}


def _crawl_dict(c: SourceCrawl | None) -> dict | None:
    if not c:
        return None
    return {"id": c.id, "status": c.status, "triggered_by": c.triggered_by, "started_at": c.started_at.isoformat(),
            "finished_at": c.finished_at.isoformat() if c.finished_at else None, "summary": c.summary or {}}


@app.get("/api/source-monitor")
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
            "drafts": totals, "hosts": sorted(source_service.allowed_hosts()),
            "attention": sum(1 for d in docs if d.change_state in ("new", "changed") and not d.acknowledged)}


@app.post("/api/source-monitor/crawl")
def source_crawl(wait: bool = False, p: Principal = Depends(require("source.crawl"))):
    try:
        cid = source_service.start_crawl(SessionLocal, p.tenant_id, p.id, wait=wait)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    with SessionLocal() as s:
        return _crawl_dict(s.get(SourceCrawl, cid))


@app.get("/api/source-monitor/crawls/{crawl_id}")
def source_crawl_status(crawl_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    c = s.get(SourceCrawl, crawl_id)
    if not c or c.tenant_id != p.tenant_id:
        raise HTTPException(404)
    return _crawl_dict(c)


@app.post("/api/source-monitor/upload")
async def source_upload(file: UploadFile = File(...), document_id: int | None = Form(None), source_id: str | None = Form(None),
                        p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    body = await file.read()
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


@app.get("/api/source-monitor/documents/{doc_id}/file")
def source_file(doc_id: int, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    d = _src_doc(s, p, doc_id)
    if not d.storage_path or not Path(d.storage_path).exists():
        raise HTTPException(404, "אין עותק שמור של המסמך")
    return FileResponse(d.storage_path, media_type=d.content_type or "application/octet-stream")


@app.get("/api/source-monitor/documents/{doc_id}/page/{n}.png")
def source_page(doc_id: int, n: int, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    d = _src_doc(s, p, doc_id)
    if not d.storage_path or not d.page_count or not 1 <= n <= d.page_count:
        raise HTTPException(404)
    return Response(render_page_png(Path(d.storage_path), n, zoom=1.3), media_type="image/png")


@app.post("/api/source-monitor/documents/{doc_id}/acknowledge")
def source_ack(doc_id: int, p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    d = _src_doc(s, p, doc_id)
    d.acknowledged, d.acknowledged_by = True, p.id
    audit.record(s, p.tenant_id, p.id, "source.acknowledge", "source_document", str(d.id),
                 {"sha256": d.sha256, "change_state": d.change_state})
    s.commit()
    return {"ok": True}


@app.get("/api/source-monitor/documents/{doc_id}/drafts")
def source_drafts(doc_id: int, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    d = _src_doc(s, p, doc_id)
    rows = s.scalars(select(RuleDraft).where(RuleDraft.document_id == d.id).order_by(RuleDraft.page, RuleDraft.id))
    return [{"id": r.id, "page": r.page, "section": r.section, "kind": r.kind, "topics": r.topics, "text_he": r.text_he,
             "values": r.values, "status": r.status, "note": r.note, "decided_by": r.decided_by} for r in rows]


class DraftDecisionIn(BaseModel):
    status: str            # open | for_authoring | dismissed
    note: str | None = None


@app.post("/api/source-monitor/drafts/{draft_id}")
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


LEVEL_BY_CATEGORY = {"LAW": "STATUTE", "REGULATION": "REGULATION", "STATUTORY_PLAN": "STATUTORY_PLAN",
                     "LOCAL_POLICY": "MUNICIPAL_POLICY", "GOV_GUIDANCE": "REGULATION"}


@app.get("/api/source-monitor/drafts.yaml")
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
