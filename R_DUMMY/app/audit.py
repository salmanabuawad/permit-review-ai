"""Append-only, hash-chained audit log. verify_chain() detects any edited/deleted row."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import AuditEvent

GENESIS = "0" * 64


def _digest(prev: str, tenant: str, actor: str, action: str, entity: str, entity_id: str | None, detail: dict) -> str:
    blob = json.dumps([prev, tenant, actor, action, entity, entity_id, detail], sort_keys=True,
                      ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def record(s: Session, tenant: str, actor: str, action: str, entity: str, entity_id: str | None = None,
           detail: dict | None = None) -> AuditEvent:
    detail = detail or {}
    if s.get_bind().dialect.name == "postgresql":
        # one writer at a time per authority's chain: two transactions reading the same "last" row forked the
        # chain (seen 2026-11-26 on SQLite under concurrent background jobs); released at commit / rollback
        s.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": "audit:" + str(tenant)})
    last = s.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant)
                     .order_by(AuditEvent.id.desc()).limit(1)).first()
    prev = last.hash if last else GENESIS
    ev = AuditEvent(tenant_id=tenant, actor=actor, action=action, entity=entity, entity_id=entity_id,
                    detail=detail, prev_hash=prev, hash=_digest(prev, tenant, actor, action, entity, entity_id, detail))
    s.add(ev)
    s.flush()
    return ev


def verify_chain(s: Session, tenant: str) -> tuple[bool, int | None]:
    prev = GENESIS
    for ev in s.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant).order_by(AuditEvent.id)):
        if ev.prev_hash != prev or ev.hash != _digest(prev, ev.tenant_id, ev.actor, ev.action, ev.entity,
                                                      ev.entity_id, ev.detail):
            return False, ev.id
        prev = ev.hash
    return True, None


def chain_report(s: Session, tenant: str) -> dict:
    """Why a chain does not verify: rows whose hash does not match their content (edited) versus links that skip
    back to an earlier row (a fork from concurrent writes, or deleted rows in between)."""
    evs = list(s.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant).order_by(AuditEvent.id)))
    ids = {e.hash: e.id for e in evs}
    edited = [e.id for e in evs if e.hash != _digest(e.prev_hash, e.tenant_id, e.actor, e.action, e.entity, e.entity_id, e.detail)]
    links = [{"id": b.id, "links_to": ids.get(b.prev_hash)} for a, b in zip([None, *evs], evs)
             if b.prev_hash != (a.hash if a else GENESIS)]
    return {"events": len(evs), "edited_rows": edited, "broken_links": links}
