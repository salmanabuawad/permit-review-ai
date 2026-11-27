"""API: Construction360 — site inspections at construction milestones, approved vs observed, photos, passport updates.

An inspection belongs to a permitted case. Recording it compares each observed item with the approved value; a
difference beyond the item's tolerance is a deviation (a finding for a professional, never an automatic sanction).
Every observation is written to the property passport as an OBSERVED fact, dated the inspection day.
"""
import hashlib

from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()

MILESTONES = {"start": "תחילת עבודות", "foundations": "יסודות", "frame": "שלד", "roof": "גג / קומה עליונה",
              "envelope": "מעטפת", "completion": "גמר / טופס 4"}
PHOTO_TYPES = {b"\xff\xd8\xff": ("image/jpeg", ".jpg"), b"\x89PNG": ("image/png", ".png")}
MAX_PHOTO = 15 * 1024 * 1024


class InspectionIn(BaseModel):
    milestone: str
    scheduled_for: str | None = None
    inspector_id: str | None = None


class ObservationIn(BaseModel):
    item: str
    unit: str | None = None
    approved: float | None = None
    observed: float | None = None
    tolerance: float | None = None
    note: str | None = None


class InspectionResultIn(BaseModel):
    observations: list[ObservationIn]
    notes: str = ""


def _insp(s: Session, p: Principal, inspection_id: int):
    from ..models import Inspection
    i = s.get(Inspection, inspection_id)
    if not i or i.tenant_id != p.tenant_id:
        raise HTTPException(404)
    get_case(s, p, i.case_id)
    return i


def _dict(i) -> dict:
    return {"id": i.id, "case_id": i.case_id, "milestone": i.milestone, "milestone_he": MILESTONES.get(i.milestone, i.milestone),
            "scheduled_for": i.scheduled_for and i.scheduled_for.isoformat(), "inspector_id": i.inspector_id, "status": i.status,
            "result": i.result, "observations": i.observations, "photos": [{k: v for k, v in x.items() if k != "path"} for x in i.photos or []],
            "notes": i.notes, "done_at": i.done_at and i.done_at.isoformat()}


@router.get("/api/cases/{case_id}/inspections")
def inspections(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from ..models import Inspection
    c = get_case(s, p, case_id)
    return {"milestones": MILESTONES,
            "inspections": [_dict(i) for i in s.scalars(select(Inspection).where(Inspection.case_id == c.id).order_by(Inspection.id))]}


@router.post("/api/cases/{case_id}/inspections", status_code=201)
def inspection_schedule(case_id: str, body: InspectionIn, p: Principal = Depends(require("inspection.manage")), s: Session = Depends(get_session)):
    from ..models import Inspection
    c = get_case(s, p, case_id)
    if c.kind == "design":
        raise HTTPException(422, "לתכנון לפני הגשה אין פיקוח")
    if body.milestone not in MILESTONES:
        raise HTTPException(422, "אבן דרך לא מוכרת")
    try:
        when = dt.date.fromisoformat(body.scheduled_for) if body.scheduled_for else None
    except ValueError as e:
        raise HTTPException(422, "תאריך לא תקין") from e
    i = Inspection(tenant_id=p.tenant_id, case_id=c.id, milestone=body.milestone, scheduled_for=when,
                   inspector_id=body.inspector_id or p.id, status="scheduled", observations=[], photos=[], created_by=p.id)
    s.add(i)
    s.flush()
    audit.record(s, p.tenant_id, p.id, "inspection.schedule", "inspection", str(i.id), {"case_id": c.id, "milestone": body.milestone})
    s.commit()
    return _dict(i)


@router.post("/api/inspections/{inspection_id}/result")
def inspection_result(inspection_id: int, body: InspectionResultIn, p: Principal = Depends(require("inspection.manage")),
                      s: Session = Depends(get_session)):
    """Record what was seen. Deviation = observed − approved beyond tolerance (a finding for a professional)."""
    from .. import building as B
    i = _insp(s, p, inspection_id)
    if i.status != "scheduled":
        raise HTTPException(409, "הפיקוח כבר נרשם או בוטל")
    if not body.observations:
        raise HTTPException(422, "נדרשת לפחות תצפית אחת")
    obs = []
    for o in body.observations:
        dev = None
        if o.approved is not None and o.observed is not None:
            diff = round(o.observed - o.approved, 4)
            dev = {"difference": diff, "beyond_tolerance": abs(diff) > (o.tolerance or 0)}
        obs.append({**o.model_dump(), "deviation": dev})
    beyond = [x for x in obs if x["deviation"] and x["deviation"]["beyond_tolerance"]]
    i.observations, i.notes, i.status, i.done_at = obs, body.notes or None, "done", dt.datetime.now(dt.timezone.utc)
    i.result = "deviations" if beyond else "pass"
    c = get_case(s, p, i.case_id)
    if c.gush and c.helka:                                  # passport: what was seen on site
        prop = B.get_property(s, c.tenant_id, c.gush, c.helka, None)
        for k, x in enumerate(obs):
            B.put_fact(s, prop, "inspection", f"{i.id}:{k}:{x['item']}", {**x, "milestone": i.milestone, "case_id": c.id},
                       "OBSERVED", "site_inspection", str(i.id), valid_from=i.done_at.date(), user=p.id)
    audit.record(s, p.tenant_id, p.id, "inspection.result", "inspection", str(i.id), {"result": i.result, "deviations": len(beyond)})
    s.commit()
    return _dict(i)


@router.post("/api/inspections/{inspection_id}/photos")
async def inspection_photo(inspection_id: int, file: UploadFile = File(...), lat: float | None = Form(None), lon: float | None = Form(None),
                           p: Principal = Depends(require("inspection.manage")), s: Session = Depends(get_session)):
    i = _insp(s, p, inspection_id)
    body = await file.read(MAX_PHOTO + 1)
    if len(body) > MAX_PHOTO:
        raise HTTPException(413, "תמונה גדולה מ־15 MB")
    kind = next((v for k, v in PHOTO_TYPES.items() if body.startswith(k)), None)
    if not kind:
        raise HTTPException(422, "רק JPEG או PNG")
    if (lat is not None and not -90 <= lat <= 90) or (lon is not None and not -180 <= lon <= 180):
        raise HTTPException(422, "מיקום לא תקין")
    sha = hashlib.sha256(body).hexdigest()
    rel = f"{sha[:2]}/{sha}{kind[1]}"
    path = settings.storage_dir / "_inspections" / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    i.photos = [*(i.photos or []), {"sha256": sha, "path": rel, "content_type": kind[0], "lat": lat, "lon": lon,
                                    "taken_at": dt.datetime.now(dt.timezone.utc).isoformat()}]
    audit.record(s, p.tenant_id, p.id, "inspection.photo", "inspection", str(i.id), {"sha256": sha})
    s.commit()
    return _dict(i)


@router.get("/api/inspections/{inspection_id}/photos/{sha}")
def inspection_photo_file(inspection_id: int, sha: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    i = _insp(s, p, inspection_id)
    ph = next((x for x in i.photos or [] if x["sha256"] == sha), None)
    if not ph:
        raise HTTPException(404)
    return FileResponse(settings.storage_dir / "_inspections" / ph["path"], media_type=ph["content_type"])
