"""API: Permit360 Pro projects — committee directory, parcel-based committee discovery (path B), committee verification
(path A), project creation, the applicable regulatory package, the preparation workflow and the engineering assistant;
committee knowledge-base uploads by authorised users."""
from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


class ParcelIn(BaseModel):
    gush: str
    helka: str
    lot: str | None = None
    committee_id: str | None = None


class ProjectIn(ParcelIn):
    path: str                       # A | B
    title: str = ""
    permit_type: str = "new_building"
    manual: bool = False            # choose the committee by hand when the boundaries cannot answer (marked unresolved)
    confirm: bool = False           # the engineer confirmed the discovered / verified jurisdiction


class PurposeIn(BaseModel):
    permit_type: str
    purpose: str
    main_use: str | None = None


class AskIn(BaseModel):
    question: str


def _err(e):
    from .. import projects as P
    if isinstance(e, P.ProjectError):
        raise HTTPException(e.code, {"message": str(e), "result": e.detail}) from e
    raise e


def _project(s: Session, p: Principal, case_id: str) -> PermitCase:
    c = get_case(s, p, case_id)
    if c.kind != "design":
        raise HTTPException(404, "פרויקט לא נמצא")
    return c


@router.get("/api/committees/directory")
def committee_directory(q: str = "", p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    from .. import projects as P
    return P.directory(s, q)


@router.post("/api/projects/discover")
def project_discover(body: ParcelIn, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    """Path B, no side effects: the committee responsible for the parcel by official boundaries."""
    from .. import jurisdiction as J
    from .. import projects as P
    try:
        g, h, _ = P._check_ids(body.gush, body.helka, body.lot)
    except P.ProjectError as e:
        _err(e)
    return J.discover(s, g, h)


@router.post("/api/projects/verify")
def project_verify(body: ParcelIn, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    """Path A, no side effects: is the parcel inside the selected committee's planning area?"""
    from .. import jurisdiction as J
    from .. import projects as P
    if not body.committee_id:
        raise HTTPException(422, "יש לבחור ועדה")
    try:
        g, h, _ = P._check_ids(body.gush, body.helka, body.lot)
    except P.ProjectError as e:
        _err(e)
    return J.verify(s, body.committee_id, g, h)


@router.post("/api/projects", status_code=201)
def project_create(body: ProjectIn, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    from .. import projects as P
    if body.permit_type not in PERMIT_TYPES:
        raise HTTPException(422, "סוג בקשה לא מוכר")
    if not body.confirm:
        raise HTTPException(422, "יש לאשר את פרטי התחום והוועדה לפני פתיחת הפרויקט")
    try:
        c = P.create(s, p.tenant_id, p.id, body.path, body.gush, body.helka, body.lot, body.committee_id, body.title,
                     body.permit_type, body.manual)
    except P.ProjectError as e:
        s.rollback()
        _err(e)
    audit.record(s, p.tenant_id, p.id, "project.create", "permit_case", c.id,
                 {"path": body.path, "committee_id": c.committee_id, "jurisdiction": (c.jurisdiction or {}).get("status")})
    s.commit()
    return {**case_dict(c), "jurisdiction": c.jurisdiction, "workflow": c.workflow}


@router.get("/api/projects/{case_id}")
def project_view(case_id: str, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    from .. import projects as P
    c = _project(s, p, case_id)
    pkg = P.package(s, c)
    return {"case": case_dict(c), "jurisdiction": c.jurisdiction, "package": pkg, "workflow": P.workflow(s, c, pkg)}


@router.put("/api/projects/{case_id}/purpose")
def project_purpose(case_id: str, body: PurposeIn, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    c = _project(s, p, case_id)
    if body.permit_type not in PERMIT_TYPES or not body.purpose.strip():
        raise HTTPException(422, "יש לבחור סוג בקשה ולתאר את מטרתה")
    c.permit_type = body.permit_type
    c.declared = {**(c.declared or {}), "purpose": body.purpose.strip()[:1000], **({"main_use": body.main_use} if body.main_use else {})}
    audit.record(s, p.tenant_id, p.id, "project.purpose", "permit_case", c.id, {"permit_type": body.permit_type})
    s.commit()
    return {"ok": True}


@router.post("/api/projects/{case_id}/assistant")
def project_assistant(case_id: str, body: AskIn, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    from .. import projects as P
    c = _project(s, p, case_id)
    try:
        out = P.ask(s, c, body.question)
    except P.ProjectError as e:
        _err(e)
    audit.record(s, p.tenant_id, p.id, "project.ask", "permit_case", c.id, {"outcome": out["outcome"]})
    s.commit()
    return out


@router.post("/api/committees/{committee_id}/upload", status_code=201)
async def committee_upload(committee_id: str, file: UploadFile = File(...), kind: str = Form("guideline"), title: str = Form(""),
                           p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    """An authorised user adds a regulatory document to a committee's knowledge base (unverified until reviewed)."""
    import hashlib

    from .. import committee_docs as CD
    from ..models import CommitteeDocument, PlanningCommittee
    from ..safe_extract import extract as sandboxed
    from ..source_monitor.service import validate_upload
    c = s.get(PlanningCommittee, committee_id)
    if c is None:
        raise HTTPException(404, "ועדה לא נמצאה")
    if kind not in ("guideline", "plan", "bylaw", "procedure"):
        raise HTTPException(422, "סוג מסמך לא מוכר")
    body = await file.read(50 * 1024 * 1024 + 1)
    if len(body) > 50 * 1024 * 1024:
        raise HTTPException(413, "הקובץ גדול מ־50 MB")
    name = (file.filename or "upload").lower()
    ext = next((e for e in (".pdf", ".docx", ".xlsx") if name.endswith(e)), None)
    if ext is None:
        raise HTTPException(422, "רק PDF, DOCX או XLSX")
    try:
        validate_upload(body, ext)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    sha = hashlib.sha256(body).hexdigest()
    url = f"upload:{sha}"
    doc = s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id, CommitteeDocument.url == url)).first()
    if doc is None:
        doc = CommitteeDocument(committee_id=c.id, url=url, title=(title or file.filename or "")[:300], kind=kind,
                                found_on=f"upload:{p.id}", status="pending")
        s.add(doc)
        s.flush()
        CD._save(s, doc, body, CD.DOC_EXT[ext], ext, None, sandboxed)
        doc.status, doc.checked_at = "ok", dt.datetime.now(dt.timezone.utc)
    audit.record(s, p.tenant_id, p.id, "committee.upload", "committee_document", str(doc.id), {"committee_id": c.id, "sha256": sha})
    s.commit()
    return {"id": doc.id, "committee_id": c.id, "title": doc.title, "kind": doc.kind, "status": doc.status}
