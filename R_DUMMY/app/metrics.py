"""Process metrics for the management dashboard (tender spec §8.1–8.2).

Stage timings are reconstructed from the append-only audit log, so they cannot drift from
what actually happened and need no extra bookkeeping in the workflow code.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent, InferenceCost, PermitCase

OPEN_STATUSES = {"INTAKE", "IN_REVIEW", "RETURNED_FOR_COMPLETION", "WAITING_EXTERNAL"}
DEFAULT_STUCK_DAYS = 5      # DESIGN_ASSUMPTION — to be set per tenant at the specification stage


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def case_timelines(s: Session, tenant: str) -> dict[str, list[tuple[str, dt.datetime]]]:
    """case_id -> ordered [(status, entered_at)] reconstructed from audit events."""
    tl: dict[str, list[tuple[str, dt.datetime]]] = defaultdict(list)
    run_case: dict[str, str] = {}
    for ev in s.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant).order_by(AuditEvent.id)):
        at = _aware(ev.at)
        if ev.action == "case.create":
            tl[ev.entity_id].append(("INTAKE", at))
        elif ev.action == "check.run":
            cid = ev.detail.get("case_id")
            if cid and tl.get(cid) and tl[cid][-1][0] in ("INTAKE", "RETURNED_FOR_COMPLETION"):
                tl[cid].append(("IN_REVIEW", at))
            run_case[ev.entity_id] = cid
        elif ev.action == "case.status":
            tl[ev.entity_id].append((ev.detail.get("status"), at))
        elif ev.action == "case.lock":
            tl[ev.entity_id].append(("REVIEWER_APPROVED", at))
    return tl


def stage_stats(s: Session, tenant: str, now: dt.datetime | None = None, stuck_days: int = DEFAULT_STUCK_DAYS) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    cases = {c.id: c for c in s.scalars(select(PermitCase).where(PermitCase.tenant_id == tenant, PermitCase.kind != "design"))}
    spent: dict[str, list[float]] = defaultdict(list)
    stuck = []
    for cid, events in case_timelines(s, tenant).items():
        if cid not in cases:
            continue
        for (st, t0), (_, t1) in zip(events, events[1:]):
            spent[st].append((t1 - t0).total_seconds() / 3600)
        last_status, last_at = events[-1]
        if last_status in OPEN_STATUSES:
            hours = (now - last_at).total_seconds() / 3600
            spent[last_status].append(hours)
            if hours >= stuck_days * 24:
                c = cases[cid]
                stuck.append({"case_id": cid, "case_number": c.case_number, "status": last_status,
                              "days_in_status": round(hours / 24, 1)})
    return {
        "avg_hours_by_stage": {k: round(sum(v) / len(v), 2) for k, v in spent.items() if v},
        "samples_by_stage": {k: len(v) for k, v in spent.items()},
        "stuck": sorted(stuck, key=lambda x: -x["days_in_status"]),
        "stuck_threshold_days": stuck_days,
        "waiting_external": sum(1 for c in cases.values() if c.status == "WAITING_EXTERNAL"),
        "new_last_7_days": sum(1 for c in cases.values() if _aware(c.created_at) >= now - dt.timedelta(days=7)),
    }


def cost_breakdown(s: Session, tenant: str) -> dict:
    by_user: dict[str, float] = defaultdict(float)
    by_month: dict[str, float] = defaultdict(float)
    calls_by_month: dict[str, int] = defaultdict(int)
    for r in s.scalars(select(InferenceCost).where(InferenceCost.tenant_id == tenant)):
        by_user[r.user_id or "system"] += r.cost_ils or 0
        month = _aware(r.at).strftime("%Y-%m")
        by_month[month] += r.cost_ils or 0
        calls_by_month[month] += 1
    return {
        "cost_per_user": {k: round(v, 4) for k, v in sorted(by_user.items())},
        "cost_per_month": [{"month": m, "cost_ils": round(by_month[m], 4), "calls": calls_by_month[m]}
                           for m in sorted(by_month)],
    }
