"""Authenticated review attestations (V9 §Run and integrate 1).

A reviewer's "I reviewed this" is recorded server-side for one exact run — never read from a flag in an uploaded
JSON, a rule file or a client request. The attestation binds:

  * who: the authenticated principal (user id and role at the time),
  * what: `run_digest(run)` — SHA-256 over the run's inputs (file SHA-256s), rule-set hash and every finding's status,
    review status and reviewer decision,
  * a signature: HMAC-SHA256 with the server's attestation key (BBP_ATTESTATION_KEY, else a 0600 key file under the
    storage dir, created on first use). The key never leaves the server and is never given to a client or a model.

`verify()` returns VALID only when the signature matches, the run still has the signed digest and the run is the
case's latest — so a changed finding, a new run (stale revision) or a forged row is never shown as reviewed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .config import settings
from .models import CheckRun, ReviewAttestation

DECISIONS = ("REVIEWED", "APPROVED_FOR_REPORT", "REJECTED_RUN")
ATTEST_ROLES = {"reviewer", "dept_manager", "city_engineer"}


def _key() -> bytes:
    env = os.environ.get("BBP_ATTESTATION_KEY")
    if env:
        return env.encode()
    p = Path(settings.storage_dir) / "_keys" / "attestation.key"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return p.read_text().strip().encode()


def run_digest(run: CheckRun) -> str:
    findings = sorted(
        ({"rule": f.rule_id, "v": f.rule_version, "status": f.status, "computed": f.computed_result,
          "review": next((x[7:] for x in (f.flags or []) if x.startswith("STATUS_")), None),
          "value": f.measured_value, "decision": f.reviewer_decision, "note": f.reviewer_note}
         for f in run.findings), key=lambda d: (d["rule"], d["v"]))
    body = {"run": run.id, "version": run.version, "case": run.case_id, "ruleset": run.ruleset_hash,
            "inputs": sorted((i.get("sha256") or "", i.get("file") or "") for i in (run.input_hashes or [])),
            "findings": findings}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _sign(run_id: str, digest: str, user: str, role: str, decision: str, at: dt.datetime) -> str:
    at_s = (at if at.tzinfo else at.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    msg = "|".join((run_id, digest, user, role, decision, at_s)).encode()
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()


def attest(s: Session, run: CheckRun, user_id: str, role: str, decision: str, note: str = "") -> ReviewAttestation:
    if role not in ATTEST_ROLES:
        raise PermissionError("תפקיד זה אינו רשאי לאשר בדיקה")
    if decision not in DECISIONS:
        raise ValueError("החלטה לא מוכרת")
    latest = s.scalar(select(func.max(CheckRun.version)).where(CheckRun.case_id == run.case_id))
    if run.version != latest:
        raise ValueError("ניתן לאשר רק את הרצת הבדיקה האחרונה של התיק")
    at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    digest = run_digest(run)
    a = ReviewAttestation(tenant_id=run.tenant_id, case_id=run.case_id, run_id=run.id, run_version=run.version,
                          user_id=user_id, role=role, decision=decision, note=note or "", digest=digest,
                          signature=_sign(run.id, digest, user_id, role, decision, at), at=at)
    s.add(a)
    s.flush()
    audit.record(s, run.tenant_id, user_id, "run.attest", "check_run", run.id,
                 {"decision": decision, "digest": digest, "attestation": a.id})
    return a


def verify(s: Session, a: ReviewAttestation) -> str:
    """VALID | INVALID (signature or digest forged) | STALE (the run changed or is no longer the latest)."""
    expected = _sign(a.run_id, a.digest, a.user_id, a.role, a.decision, a.at)
    if not hmac.compare_digest(expected, a.signature or ""):
        return "INVALID"
    run = s.get(CheckRun, a.run_id)
    if run is None or run.case_id != a.case_id:
        return "INVALID"
    if run_digest(run) != a.digest:
        return "STALE"
    latest = s.scalar(select(func.max(CheckRun.version)).where(CheckRun.case_id == run.case_id))
    return "VALID" if run.version == latest else "STALE"


def public_view(s: Session, a: ReviewAttestation) -> dict:
    """What a client may see: no signature, no key material."""
    return {"id": a.id, "run_id": a.run_id, "run_version": a.run_version, "user_id": a.user_id, "role": a.role,
            "decision": a.decision, "note": a.note, "at": a.at.isoformat() if a.at else None,
            "state": verify(s, a)}


def run_attestations(s: Session, run: CheckRun) -> list[dict]:
    rows = s.scalars(select(ReviewAttestation).where(ReviewAttestation.run_id == run.id)
                     .order_by(ReviewAttestation.id))
    return [public_view(s, a) for a in rows]
