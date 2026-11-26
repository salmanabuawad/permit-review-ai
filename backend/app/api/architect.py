"""API: Architect360 — private pre-submission designs checked by the same engine, readiness and design comparison.

A design is a case of kind "design" owned by its architect: invisible in the authority's case lists, dashboards and
metrics, and to anyone but its owner and the system administrator. The readiness score is an estimate of how ready the
design is for submission from the checks the system can run — never a statement of compliance.
"""
from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


class DesignIn(BaseModel):
    title: str
    permit_type: str
    track: str = "regular_permit"
    gush: str | None = None
    helka: str | None = None
    address: str | None = None
    applicable_plans: list[str] = []
    declared: dict = {}


def _design(s: Session, p: Principal, design_id: str) -> PermitCase:
    c = get_case(s, p, design_id)
    if c.kind != "design":
        raise HTTPException(404, "תכנון לא נמצא")
    return c


@router.get("/api/designs")
def designs(p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    q = select(PermitCase).where(PermitCase.tenant_id == p.tenant_id, PermitCase.kind == "design")
    if p.role != "sysadmin":
        q = q.where(PermitCase.owner_id == p.id)
    return [{**case_dict(c, with_files=False), "readiness": readiness(s, c)} for c in s.scalars(q.order_by(PermitCase.created_at.desc()))]


@router.post("/api/designs", status_code=201)
def design_create(body: DesignIn, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    if body.permit_type not in PERMIT_TYPES or body.track not in TRACKS:
        raise HTTPException(422, "סוג בקשה/מסלול לא מוכר")
    if not body.title.strip():
        raise HTTPException(422, "חסרה כותרת")
    n = s.scalar(select(func.count()).select_from(PermitCase).where(PermitCase.tenant_id == p.tenant_id, PermitCase.kind == "design")) or 0
    c = PermitCase(tenant_id=p.tenant_id, case_number=f"DES-{n + 1:04d}", title=body.title.strip(), permit_type=body.permit_type,
                   track=body.track, gush=body.gush, helka=body.helka, address=body.address,
                   applicable_plans=body.applicable_plans, declared=body.declared, kind="design", owner_id=p.id,
                   is_demo=False, status="INTAKE")
    s.add(c)
    s.flush()
    audit.record(s, p.tenant_id, p.id, "design.create", "permit_case", c.id, {"title": c.title})
    s.commit()
    return case_dict(c)


@router.post("/api/designs/{design_id}/check")
def design_check(design_id: str, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    """Run every applicable check on the design (same engine as a submitted request)."""
    c = _design(s, p, design_id)
    if not c.files:
        raise HTTPException(422, "יש להעלות לפחות קובץ אחד של התכנון")
    run = services.run_checks(s, c, p.id)
    s.commit()
    return {"run_id": run.id, "version": run.version, "readiness": readiness(s, c)}


def readiness(s: Session, c: PermitCase) -> dict | None:
    """Estimate from the latest run: blockers first, then a score over the applicable checks that were decided."""
    from .. import finding_schema as FS
    run = c.runs[-1] if c.runs else None
    if run is None:
        return None
    rules = {r.id: r.raw for r in services.rules_for_tenant(s, c.tenant_id, include_deleted=True)}
    rows = [FS.normalise(f, rules.get(f.rule_id), True) for f in run.findings]
    applicable = [r for r in rows if r["check_status"] != "NOT_APPLICABLE"]
    passed = [r for r in applicable if r["check_status"] == "PASS"]
    blockers = [r for r in applicable if r["check_status"] in ("CONFIRMED_VIOLATION", "DOCUMENT_INCONSISTENCY", "DECLARATION_MISMATCH")
                or (r["engine_status"] == "FAIL")]
    open_ = [r for r in applicable if r["check_status"] in ("UNRESOLVED", "DISCRETIONARY_REVIEW_REQUIRED") and r not in blockers]
    score = round(100 * len(passed) / len(applicable)) if applicable else 0
    return {"run_version": run.version, "score": score, "applicable": len(applicable), "passed": len(passed),
            "blockers": [{"rule_id": r["rule_id"], "description": r["description"], "measured": r["measured_value"],
                          "permitted": r["permitted_value"], "units": r["units"], "fix": r["recommended_action"]} for r in blockers],
            "open": len(open_), "ready": not blockers and not any(r["severity"] == "high" for r in open_),
            "note": "הערכה על בסיס הבדיקות שהמערכת מריצה — אינה קביעת עמידה בדין ואינה תחליף לבדיקת הוועדה"}


@router.get("/api/designs/{design_id}/readiness")
def design_readiness(design_id: str, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    return readiness(s, _design(s, p, design_id))


@router.get("/api/designs/compare")
def design_compare(a: str, b: str, p: Principal = Depends(require("design.create")), s: Session = Depends(get_session)):
    """Per-rule outcome of two designs (latest runs): where B is better, worse or the same as A."""
    da, db = _design(s, p, a), _design(s, p, b)
    ra, rb = (da.runs[-1] if da.runs else None), (db.runs[-1] if db.runs else None)
    if not ra or not rb:
        raise HTTPException(422, "יש להריץ בדיקה לשני התכנונים")
    rank = {"FAIL": 0, "UNCERTAIN": 1, "PASS": 2, "NA": 2}
    fa, fb = {f.rule_id: f for f in ra.findings}, {f.rule_id: f for f in rb.findings}
    out = {"better": [], "worse": [], "same_open": []}
    for rid in sorted(set(fa) | set(fb)):
        x, y = fa.get(rid), fb.get(rid)
        sx, sy = (x.status if x else "NA"), (y.status if y else "NA")
        item = {"rule_id": rid, "title_he": (y or x).title_he, "a": sx, "b": sy,
                "a_value": x.measured_value if x else None, "b_value": y.measured_value if y else None}
        if rank[sy] > rank[sx]:
            out["better"].append(item)
        elif rank[sy] < rank[sx]:
            out["worse"].append(item)
        elif sx in ("FAIL", "UNCERTAIN"):
            out["same_open"].append(item)
    return {"a": {"id": da.id, "title": da.title, "readiness": readiness(s, da)},
            "b": {"id": db.id, "title": db.title, "readiness": readiness(s, db)}, **out}
