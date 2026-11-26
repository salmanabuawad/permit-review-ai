"""Building360: the digital property passport — one place for what is known about a property, from where, how sure.

Facts are bitemporal: `valid_from / valid_to` say when a fact held in the world; `recorded_at / superseded_at` when
the system knew it. A re-sync never overwrites: a changed value supersedes the previous row, which keeps its history,
so "what did we know on date X about date Y" can be answered. Each fact carries its standing:
  APPROVED   — from an issued permit / certificate or an approved table whose arithmetic closes
  DECLARED   — stated by an applicant (application, declared values) or pending in the register
  OBSERVED   — seen on site (inspections)
  UNVERIFIED — anything else, with the reason (e.g. a register entry flagged by spatial control, a table that does not close)
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import CommitteeDecision, PermitCase, Property, PropertyFact

STATUSES = ("APPROVED", "DECLARED", "OBSERVED", "UNVERIFIED")
REGISTER_STATUS = {"היתר בניה": "APPROVED", "היתר / תעודת גמר": "APPROVED", "מאושר": "APPROVED", "הגשה": "DECLARED"}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _date(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def get_property(s: Session, tenant: str, gush: str, helka: str | None = None, cell: str | None = None, **extra) -> Property:
    p = s.scalars(select(Property).where(Property.tenant_id == tenant, Property.gush == str(gush),
                                         Property.helka.is_(None) if helka is None else Property.helka == str(helka),
                                         Property.cell.is_(None) if cell is None else Property.cell == str(cell))).first()
    if p is None:
        p = Property(tenant_id=tenant, gush=str(gush), helka=None if helka is None else str(helka),
                     cell=None if cell is None else str(cell), **extra)
        s.add(p)
        s.flush()
    else:
        for k, v in extra.items():
            if v and not getattr(p, k):
                setattr(p, k, v)
    return p


def put_fact(s: Session, p: Property, kind: str, key: str, value: dict, status: str, source_type: str,
             source_ref: str | None = None, source_url: str | None = None, valid_from=None, valid_to=None,
             user: str = "system") -> str:
    """Insert or supersede. Returns 'new', 'changed' or 'same'."""
    assert status in STATUSES
    cur = s.scalars(select(PropertyFact).where(PropertyFact.property_id == p.id, PropertyFact.kind == kind,
                                               PropertyFact.key == key, PropertyFact.superseded_at.is_(None))).first()
    if cur is not None and cur.value == value and cur.status == status and cur.valid_from == _date(valid_from) \
            and cur.valid_to == _date(valid_to):
        return "same"
    if cur is not None:
        cur.superseded_at = now()
    s.add(PropertyFact(tenant_id=p.tenant_id, property_id=p.id, kind=kind, key=key, value=value, status=status,
                       source_type=source_type, source_ref=source_ref, source_url=source_url,
                       valid_from=_date(valid_from), valid_to=_date(valid_to), recorded_by=user))
    s.flush()
    return "changed" if cur is not None else "new"


def sync_ledgers(s: Session, tenant: str) -> dict:
    """Committee register snapshots and permit area tables under knowledge/lots for this authority's files."""
    out = {"new": 0, "changed": 0, "same": 0}
    prefix = {"hof-ashkelon": "hof_ashkelon_"}.get(tenant)
    if not prefix:
        return out
    for path in sorted((settings.knowledge_dir / "lots").glob(f"{prefix}*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "records" in data:
            lot = data.get("lot") or {}
            p = get_property(s, tenant, lot.get("block"), None, lot.get("lot"), locality=lot.get("locality"), plan=lot.get("plan"),
                             note_he="תא שטח לפי תכנית; צילום מצב של מאגר הוועדה — אינו ספר זכויות מאושר")
            for r in data["records"]:
                st = REGISTER_STATUS.get(r.get("status") or "", "UNVERIFIED")
                v = {k: r.get(k) for k in ("type", "status", "building", "units", "primary_m2", "service_m2", "essence", "permit_id", "flags")}
                if st == "UNVERIFIED":
                    v["unverified_reason"] = f"סטטוס במאגר: {r.get('status')}"
                res = put_fact(s, p, "permit" if r.get("permit_id") else "application", str(r.get("application_id")), v, st,
                               "committee_register", path.name, r.get("source_url"), r.get("permit_date") or r.get("submitted"))
                out[res] += 1
        if "permits" in data:
            lot_file = path.name.replace("_permits", "")
            lot = (yaml.safe_load((path.parent / lot_file).read_text(encoding="utf-8")) or {}).get("lot", {}) if (path.parent / lot_file).exists() else {}
            p = get_property(s, tenant, lot.get("block", "2832"), None, lot.get("lot"))
            for r in data["permits"]:
                closes = all(a.get("closes") for a in r.get("arithmetic") or [])
                v = {"building": r.get("building"), "kind": r.get("kind"), "amends": r.get("amends"), "table": r.get("table"),
                     "arithmetic": r.get("arithmetic"), "read_method": r.get("read_method")}
                if not closes:
                    v["unverified_reason"] = "חשבון הטבלה אינו נסגר — הערכים נשמרו ללא תיקון"
                res = put_fact(s, p, "area_table", f"{r.get('permit')}:{r.get('document')}", v, "APPROVED" if closes else "UNVERIFIED",
                               "signed_permit_drawing", r.get("document_sha256"), r.get("source_url"))
                out[res] += 1
    return out


def sync_cases(s: Session, tenant: str) -> dict:
    out = {"new": 0, "changed": 0, "same": 0}
    for c in s.scalars(select(PermitCase).where(PermitCase.tenant_id == tenant, PermitCase.kind != "design",
                                                PermitCase.gush.is_not(None), PermitCase.helka.is_not(None))):
        p = get_property(s, tenant, c.gush, c.helka, None)
        res = put_fact(s, p, "application", c.case_number, {"title": c.title, "permit_type": c.permit_type, "status": c.status,
                       "case_id": c.id, "plans": c.applicable_plans}, "DECLARED", "permit_case", c.id,
                       valid_from=(c.declared or {}).get("submission_date") or c.created_at.date())
        out[res] += 1
        for k, v in sorted((c.declared or {}).items()):
            if isinstance(v, (int, float, str, bool)) and k not in ("submission_date", "description", "request_text"):
                res = put_fact(s, p, "declared", f"{c.case_number}:{k}", {"field": k, "value": v, "case_id": c.id}, "DECLARED",
                               "permit_case", c.id, valid_from=(c.declared or {}).get("submission_date"))
                out[res] += 1
        for d in s.scalars(select(CommitteeDecision).where(CommitteeDecision.case_id == c.id)):
            oc = d.outcome or ""
            approved = oc.upper().startswith("APPROV") or "אושר" in oc or "לאשר" in oc
            res = put_fact(s, p, "decision", f"{c.case_number}:{d.id}",
                           {"outcome": oc, "meeting": d.meeting_number, "item": d.item_number, "conditions": d.conditions, "case_id": c.id},
                           "APPROVED" if approved else "DECLARED", "committee_decision", str(d.id), valid_from=d.meeting_date)
            out[res] += 1
    return out


def passport(s: Session, tenant: str, prop: Property, as_of: dt.date | None = None, known_at: dt.datetime | None = None) -> dict:
    """The property's facts valid at `as_of` as known at `known_at` (default: today, now)."""
    q = select(PropertyFact).where(PropertyFact.property_id == prop.id)
    if known_at is not None:
        q = q.where(PropertyFact.recorded_at <= known_at,
                    or_(PropertyFact.superseded_at.is_(None), PropertyFact.superseded_at > known_at))
    else:
        q = q.where(PropertyFact.superseded_at.is_(None))
    if as_of is not None:
        q = q.where(or_(PropertyFact.valid_from.is_(None), PropertyFact.valid_from <= as_of),
                    or_(PropertyFact.valid_to.is_(None), PropertyFact.valid_to > as_of))
    facts = list(s.scalars(q.order_by(PropertyFact.valid_from.desc().nulls_last(), PropertyFact.id)))
    by_status: dict[str, int] = {}
    for f in facts:
        by_status[f.status] = by_status.get(f.status, 0) + 1
    return {"property": {"id": prop.id, "gush": prop.gush, "helka": prop.helka, "cell": prop.cell, "locality": prop.locality,
                         "plan": prop.plan, "note_he": prop.note_he},
            "as_of": as_of.isoformat() if as_of else None, "known_at": known_at.isoformat() if known_at else None,
            "by_status": by_status,
            "facts": [{"id": f.id, "kind": f.kind, "key": f.key, "value": f.value, "status": f.status, "source_type": f.source_type,
                       "source_ref": f.source_ref, "source_url": f.source_url, "valid_from": f.valid_from and f.valid_from.isoformat(),
                       "valid_to": f.valid_to and f.valid_to.isoformat(), "recorded_at": f.recorded_at.isoformat()} for f in facts]}


def properties_for_case(s: Session, case: PermitCase) -> list[Property]:
    """The case's own parcel, then plan-cell properties of the same block (cells can span parcels)."""
    if not case.gush:
        return []
    rows = list(s.scalars(select(Property).where(Property.tenant_id == case.tenant_id, Property.gush == case.gush)))
    return sorted(rows, key=lambda p: (p.helka != case.helka, p.cell is None))
