"""Submitting a Permit360 Pro project to the responsible planning committee, with a confirmation number.

The project must have a committee (established from the official boundaries, or chosen and marked unverified), a
declared purpose, at least one active document and the applicant's declaration. Submission:
  - issues a unique confirmation number P360-<year>-<6 digits>;
  - when that committee works in Permit360 (an authority workspace linked to it in the national register), opens the
    request as a case there — numbered with the confirmation number, documents copied — so its reviewers see it;
  - otherwise records it as submitted to Permit360 only, and says the committee is not connected yet;
  - freezes the project (no further uploads) and e-mails the confirmation to the submitter's verified address.
The submitter's name is not copied into the committee case; it refers to the submitting account."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit, mailer
from .models import CaseFile, LoginAccount, Municipality, PermitCase, PlanningCommittee, Submission

SUBMITTED = "SUBMITTED"


class SubmitError(ValueError):
    def __init__(self, msg: str, code: int = 422):
        super().__init__(msg)
        self.code = code


def committee_workspace(s: Session, committee_id: str | None) -> Municipality | None:
    if not committee_id:
        return None
    return s.scalars(select(Municipality).where(Municipality.committee_id == committee_id, Municipality.is_demo.is_(False))
                     .order_by(Municipality.id)).first()


def _active_files(case: PermitCase) -> list[CaseFile]:
    return [f for f in (case.files or []) if f.lifecycle == "ACTIVE"]


def checklist(s: Session, case: PermitCase) -> list[dict]:
    """What submission needs, each item done or not (the wizard shows the same list)."""
    d = case.declared or {}
    jur = case.jurisdiction or {}
    return [
        {"key": "committee", "done": bool(case.committee_id), "text_he": "ועדה מוסמכת נקבעה" +
         ("" if jur.get("status") in ("VERIFIED", "RESOLVED") else " (לא אומתה מגבולות רשמיים)")},
        {"key": "purpose", "done": bool(d.get("purpose") and case.permit_type), "text_he": "סוג הבקשה ומטרתה הוגדרו"},
        {"key": "documents", "done": bool(_active_files(case)), "text_he": "צורף לפחות מסמך אחד"},
    ]


def _number(s: Session, year: int) -> str:
    prefix = f"P360-{year}-"
    n = s.scalar(select(func.count()).select_from(Submission).where(Submission.confirmation_number.like(prefix + "%"))) or 0
    while True:
        n += 1
        num = f"{prefix}{n:06d}"
        if not s.scalar(select(Submission.id).where(Submission.confirmation_number == num)):
            return num


def view(s: Session, sub: Submission | None) -> dict | None:
    if sub is None:
        return None
    from .api.common import CASE_STATUSES
    target = s.get(PermitCase, sub.target_case_id) if sub.target_case_id else None
    c = s.get(PlanningCommittee, sub.committee_id) if sub.committee_id else None
    return {"confirmation_number": sub.confirmation_number, "submitted_at": sub.submitted_at.isoformat(),
            "committee_name": c.name_he if c else None, "connected": bool(target),
            "status": target.status if target else SUBMITTED,
            "status_he": CASE_STATUSES.get(target.status, target.status) if target else "הוגשה ל-Permit360",
            "note_he": "הבקשה נפתחה בתיקי הוועדה ב-Permit360 ותיבדק שם." if target else
            "הוועדה עדיין אינה עובדת ב-Permit360: הבקשה נשמרה עם מספר האישור, ויש להגישה גם במערכת רישוי זמין.",
            "documents": len(sub.snapshot.get("documents", [])) if sub.snapshot else 0}


def of_project(s: Session, project_id: str) -> Submission | None:
    return s.scalars(select(Submission).where(Submission.project_id == project_id)).first()


def submit(s: Session, case: PermitCase, user_id: str, declaration: bool) -> dict:
    from . import services
    if case.kind != "design":
        raise SubmitError("ניתן להגיש רק פרויקט", 404)
    if of_project(s, case.id) or case.status == SUBMITTED:
        raise SubmitError("הבקשה כבר הוגשה", 409)
    missing = [x["text_he"] for x in checklist(s, case) if not x["done"]]
    if missing:
        raise SubmitError("חסר לפני הגשה: " + "; ".join(missing))
    if not declaration:
        raise SubmitError("יש לאשר את הצהרת המגיש/ה")
    now = dt.datetime.now(dt.timezone.utc)
    files = _active_files(case)
    d = case.declared or {}
    snapshot = {"title": case.title, "permit_type": case.permit_type, "gush": case.gush, "helka": case.helka,
                "lot": d.get("lot"), "address": case.address, "purpose": d.get("purpose"), "main_use": d.get("main_use"),
                "jurisdiction": {k: (case.jurisdiction or {}).get(k) for k in ("status", "status_he", "committee_name", "path")},
                "documents": [{"filename": f.filename, "doc_type": f.doc_type, "sha256": f.sha256, "version": f.version} for f in files]}
    sub = Submission(confirmation_number=_number(s, now.year), project_id=case.id, committee_id=case.committee_id,
                     submitted_by=user_id, submitted_at=now, snapshot=snapshot)
    s.add(sub)
    s.flush()
    ws = committee_workspace(s, case.committee_id)
    if ws is not None:
        t = PermitCase(tenant_id=ws.id, case_number=sub.confirmation_number, title=case.title, permit_type=case.permit_type,
                       track=case.track, gush=case.gush, helka=case.helka, address=case.address,
                       applicable_plans=list(case.applicable_plans or []), zone=case.zone,
                       declared={**{k: v for k, v in d.items() if k in ("purpose", "main_use", "lot")},
                                 "submitted_via": "permit360-pro", "confirmation_number": sub.confirmation_number,
                                 "submitted_by": user_id},
                       application_type="הוגשה דרך Permit360 Pro", source="pro", status="INTAKE", kind="application",
                       is_demo=False, committee_id=case.committee_id, jurisdiction=case.jurisdiction,
                       sla_due=services.sla_default())
        s.add(t)
        s.flush()
        for f in files:
            try:
                services.ingest_file(s, t, f.filename, Path(f.storage_path).read_bytes(), f.doc_type, user_id)
            except Exception:  # noqa: BLE001 — a file that cannot be copied is listed, the rest still go
                snapshot.setdefault("not_copied", []).append(f.filename)
        sub.target_tenant_id, sub.target_case_id = ws.id, t.id
        sub.snapshot = dict(snapshot)
        audit.record(s, ws.id, user_id, "submission.received", "permit_case", t.id,
                     {"confirmation_number": sub.confirmation_number, "project_id": case.id})
    case.status = SUBMITTED
    case.workflow = {**(case.workflow or {}), "submission": {"confirmation_number": sub.confirmation_number,
                                                              "at": now.isoformat(), "connected": ws is not None}}
    audit.record(s, case.tenant_id, user_id, "submission.create", "permit_case", case.id,
                 {"confirmation_number": sub.confirmation_number, "committee_id": case.committee_id,
                  "target_tenant": sub.target_tenant_id})
    s.commit()
    out = view(s, sub)
    acct = s.scalars(select(LoginAccount).where(LoginAccount.user_id == user_id)).first()
    if acct and acct.email and mailer.configured():
        mailer.send(acct.email, f"אישור הגשה {sub.confirmation_number} — Permit360",
                    f"הבקשה \"{case.title}\" הוגשה.\nמספר אישור: {sub.confirmation_number}\n"
                    f"ועדה: {out['committee_name'] or '—'}\nגוש {case.gush} חלקה {case.helka}\n\n{out['note_he']}\n")
    return out
