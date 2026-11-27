"""API: Building360 — property passports (bitemporal facts with their standing and source)."""
from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


def _when(as_of: str | None, known_at: str | None):
    try:
        a = dt.date.fromisoformat(as_of) if as_of else None
        k = dt.datetime.fromisoformat(known_at).replace(tzinfo=dt.timezone.utc) if known_at else None
    except ValueError as e:
        raise HTTPException(422, "תאריך לא תקין (YYYY-MM-DD)") from e
    return a, k


@router.get("/api/properties")
def properties(gush: str | None = None, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from ..models import Property, PropertyFact
    q = select(Property).where(Property.tenant_id == p.tenant_id)
    if gush:
        q = q.where(Property.gush == gush)
    counts = dict(s.execute(select(PropertyFact.property_id, func.count()).where(PropertyFact.tenant_id == p.tenant_id,
                  PropertyFact.superseded_at.is_(None)).group_by(PropertyFact.property_id)).all())
    return [{"id": x.id, "gush": x.gush, "helka": x.helka, "cell": x.cell, "locality": x.locality, "plan": x.plan,
             "facts": counts.get(x.id, 0)} for x in s.scalars(q.order_by(Property.gush, Property.helka))]


@router.get("/api/properties/{property_id}")
def property_passport(property_id: int, as_of: str | None = None, known_at: str | None = None,
                      p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from .. import building as B
    from ..models import Property
    prop = s.get(Property, property_id)
    if not prop or prop.tenant_id != p.tenant_id:
        raise HTTPException(404)
    a, k = _when(as_of, known_at)
    return B.passport(s, p.tenant_id, prop, a, k)


@router.get("/api/cases/{case_id}/properties")
def case_properties(case_id: str, as_of: str | None = None, p: Principal = Depends(require("case.read")),
                    s: Session = Depends(get_session)):
    """The passports relevant to a case: its parcel, then plan-cell properties of the same block."""
    from .. import building as B
    c = get_case(s, p, case_id)
    a, _ = _when(as_of, None)
    return [B.passport(s, p.tenant_id, prop, a) for prop in B.properties_for_case(s, c)]


@router.post("/api/properties/sync")
def properties_sync(p: Principal = Depends(require("case.assign")), s: Session = Depends(get_session)):
    """Refresh passports from the committee register snapshots, signed permit tables, cases and decisions."""
    from .. import building as B
    out = {"ledgers": B.sync_ledgers(s, p.tenant_id), "cases": B.sync_cases(s, p.tenant_id)}
    audit.record(s, p.tenant_id, p.id, "property.sync", "property", None, out)
    s.commit()
    return out
