"""End-user self sign-up for the Permit360 Pro workspace (engineers and architects, and property owners / permit
applicants as end customers).

Flow: the form creates an inactive end_user login in the Pro workspace → a verification link goes to the e-mail
address → after the link, either the superadmin approves (BBP_SIGNUP=approval, default) or the login opens at once
(BBP_SIGNUP=open). BBP_SIGNUP=off hides it. Without outgoing mail configured, sign-up is unavailable (no unverified
addresses).

Safeguards: per-address rate limit, a ceiling on pending requests, unverified requests expire after VERIFY_HOURS,
the role is always end_user in the Pro workspace (never a committee role), and the password follows the same policy
as administrator-created logins. Rejected and expired requests are deleted, which frees the username."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import threading
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, mailer
from .models import LoginAccount, User
from .security import WORKSPACE_TENANT
from .users import check_policy, hash_password, norm_username, now

EMAIL_PENDING, APPROVAL_PENDING, APPROVED = "EMAIL_PENDING", "APPROVAL_PENDING", "APPROVED"
VERIFY_HOURS = 48
PER_ADDR, PER_ADDR_S = 3, 3600
PROFESSIONS = {"engineer": "מהנדס/ת", "architect": "אדריכל/ית", "practical_engineer": "הנדסאי/ת",
               "owner": "בעל/ת נכס / מבקש/ת היתר", "other": "אחר"}
CUSTOMERS = {"owner"}                                   # end customers: no professional licence number
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
ACTOR = "self-signup"
_hits: dict[str, list[float]] = {}
_lock = threading.Lock()


class SignupError(ValueError):
    def __init__(self, msg: str, code: int = 422):
        super().__init__(msg)
        self.code = code


def mode() -> str:
    m = os.environ.get("BBP_SIGNUP", "approval").strip().lower()
    m = m if m in ("approval", "open", "off") else "approval"
    return m if m == "off" or mailer.configured() else "off"


def max_pending() -> int:
    return int(os.environ.get("BBP_SIGNUP_MAX_PENDING", "200"))


def _limited(addr: str) -> bool:
    t = time.time()
    with _lock:
        recent = [x for x in _hits.get(addr, []) if t - x < PER_ADDR_S]
        _hits[addr] = recent
        if len(recent) >= PER_ADDR:
            return True
        recent.append(t)
        return False


# ------------------------------------------------------------------ verification token (HMAC with the session key)

def token(username: str, hours: int = VERIFY_HOURS) -> str:
    from .login import _key
    exp = int(time.time() + hours * 3600)
    body = f"{username}|{exp}"
    return body + "|" + hmac.new(_key(), ("signup-verify|" + body).encode(), hashlib.sha256).hexdigest()


def read_token(t: str) -> str | None:
    from .login import _key
    try:
        username, exp, sig = (t or "").split("|")
        good = hmac.new(_key(), f"signup-verify|{username}|{exp}".encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, good) and int(exp) >= time.time():
            return username
    except ValueError:
        pass
    return None


# ------------------------------------------------------------------ helpers

def _delete(s: Session, acct: LoginAccount) -> None:
    u = s.get(User, acct.user_id)
    s.delete(acct)
    s.flush()
    if u is not None:
        s.delete(u)
    s.flush()


def purge_expired(s: Session) -> int:
    cut = now() - dt.timedelta(hours=VERIFY_HOURS)
    old = list(s.scalars(select(LoginAccount).where(LoginAccount.signup_state == EMAIL_PENDING, LoginAccount.created_at < cut)))
    for a in old:
        _delete(s, a)
    return len(old)


def _pending_count(s: Session) -> int:
    return len(list(s.scalars(select(LoginAccount.username).where(
        LoginAccount.signup_state.in_((EMAIL_PENDING, APPROVAL_PENDING))))))


def _notify_to() -> str | None:
    return os.environ.get("BBP_SIGNUP_NOTIFY") or os.environ.get("BBP_MAIL_FROM") or os.environ.get("BBP_SMTP_USER")


def _row(s: Session, a: LoginAccount) -> dict:
    u = s.get(User, a.user_id)
    info = a.signup_info or {}
    return {"username": a.username, "user_id": a.user_id, "display_name": u.display_name if u else None,
            "email": a.email, "state": a.signup_state, "profession": info.get("profession"),
            "profession_he": PROFESSIONS.get(info.get("profession"), info.get("profession")),
            "license_number": info.get("license_number"), "organization": info.get("organization"),
            "requested_at": a.created_at.isoformat() if a.created_at else None, "verified_at": info.get("verified_at")}


# ------------------------------------------------------------------ the flow

def request(s: Session, *, username: str, display_name: str, email: str, password: str, profession: str,
            license_number: str | None, organization: str | None, base_url: str, addr: str) -> dict:
    m = mode()
    if m == "off":
        raise SignupError("ההרשמה העצמית אינה פעילה כרגע", 403)
    purge_expired(s)
    name = norm_username(username)
    display_name = (display_name or "").strip()
    if not 2 <= len(display_name) <= 200:
        raise SignupError("שם מלא חסר או ארוך מדי")
    email = (email or "").strip().lower()
    if not EMAIL.fullmatch(email):
        raise SignupError("כתובת דוא״ל לא תקינה")
    if profession not in PROFESSIONS:
        raise SignupError("יש לבחור תחום מקצועי")
    license_number = None if profession in CUSTOMERS else (license_number or "").strip()[:40] or None
    organization = (organization or "").strip()[:200] or None
    check_policy(password, name)
    if s.get(LoginAccount, name):
        raise SignupError("שם המשתמש כבר קיים", 409)
    if s.scalar(select(LoginAccount.username).where(LoginAccount.email == email).limit(1)):
        raise SignupError("כתובת הדוא״ל כבר רשומה במערכת", 409)
    if _limited(addr):
        raise SignupError("יותר מדי בקשות הרשמה מכתובת זו — נסו שוב מאוחר יותר", 429)
    if _pending_count(s) >= max_pending():
        raise SignupError("מספר בקשות ההרשמה הממתינות הגיע לתקרה — נסו שוב מאוחר יותר", 503)
    u = User(id=uuid.uuid4().hex, tenant_id=WORKSPACE_TENANT, display_name=display_name, role="end_user")
    s.add(u)
    s.flush()
    s.add(LoginAccount(username=name, user_id=u.id, password_hash=hash_password(password), active=False, must_change=False,
                       created_by=ACTOR, email=email, signup_state=EMAIL_PENDING,
                       signup_info={"profession": profession, "license_number": license_number, "organization": organization,
                                    "mode": m}))
    s.flush()
    link = base_url.rstrip("/") + "/api/auth/signup/verify?t=" + token(name)
    body = (f"שלום {display_name},\n\nהתקבלה בקשת הרשמה ל-Permit360 Pro בשם המשתמש {name}.\n"
            f"לאימות כתובת הדוא״ל יש לפתוח את הקישור (בתוקף {VERIFY_HOURS} שעות):\n{link}\n\n"
            "אם לא ביקשתם להירשם, אפשר להתעלם מהודעה זו.\n")
    if not mailer.send(email, "אימות כתובת דוא״ל — Permit360 Pro", body):
        s.rollback()
        raise SignupError("לא ניתן לשלוח כעת את הודעת האימות — נסו שוב מאוחר יותר", 503)
    audit.record(s, WORKSPACE_TENANT, ACTOR, "signup.request", "user", u.id, {"username": name, "profession": profession})
    s.commit()
    return {"ok": True, "state": EMAIL_PENDING, "mode": m}


def verify(s: Session, t: str) -> str:
    """The account's state after the link: APPROVAL_PENDING or APPROVED; 'invalid' for a bad or expired link."""
    name = read_token(t)
    acct = s.get(LoginAccount, name) if name else None
    if acct is None or acct.signup_state is None:
        return "invalid"
    if acct.signup_state != EMAIL_PENDING:
        return acct.signup_state
    info = dict(acct.signup_info or {})
    info["verified_at"] = now().isoformat()
    acct.signup_info = info
    if info.get("mode") == "open" or mode() == "open":
        acct.signup_state, acct.active = APPROVED, True
    else:
        acct.signup_state = APPROVAL_PENDING
        to = _notify_to()
        if to:
            u = s.get(User, acct.user_id)
            mailer.send(to, "בקשת הרשמה ממתינה לאישור — Permit360 Pro",
                        f"בקשת הרשמה חדשה ממתינה לאישור בסביבת Permit360 Pro.\nשם משתמש: {acct.username}\n"
                        f"שם: {u.display_name if u else ''}\nתחום: {PROFESSIONS.get(info.get('profession'), '')}\n\n"
                        "לאישור: סביבת Permit360 Pro ← משתמשים ← בקשות הרשמה.\n")
    audit.record(s, WORKSPACE_TENANT, ACTOR, "signup.verified", "user", acct.user_id, {"username": acct.username, "state": acct.signup_state})
    s.commit()
    return acct.signup_state


def pending(s: Session) -> list[dict]:
    q = select(LoginAccount).where(LoginAccount.signup_state.in_((EMAIL_PENDING, APPROVAL_PENDING))).order_by(LoginAccount.created_at)
    return [_row(s, a) for a in s.scalars(q)]


def _waiting(s: Session, username: str) -> LoginAccount:
    acct = s.get(LoginAccount, (username or "").strip().lower())
    if acct is None or acct.signup_state not in (EMAIL_PENDING, APPROVAL_PENDING):
        raise SignupError("בקשת הרשמה לא נמצאה", 404)
    return acct


def approve(s: Session, actor: str, username: str) -> dict:
    acct = _waiting(s, username)
    if acct.signup_state != APPROVAL_PENDING:
        raise SignupError("כתובת הדוא״ל טרם אומתה", 409)
    acct.signup_state, acct.active = APPROVED, True
    audit.record(s, WORKSPACE_TENANT, actor, "signup.approve", "user", acct.user_id, {"username": acct.username})
    s.commit()
    if acct.email:
        mailer.send(acct.email, "החשבון אושר — Permit360 Pro",
                    f"החשבון {acct.username} ב-Permit360 Pro אושר. אפשר להיכנס עם שם המשתמש והסיסמה שבחרתם.\n")
    return _row(s, acct)


def reject(s: Session, actor: str, username: str, reason: str | None = None) -> None:
    acct = _waiting(s, username)
    email, name, uid = acct.email, acct.username, acct.user_id
    _delete(s, acct)
    audit.record(s, WORKSPACE_TENANT, actor, "signup.reject", "user", uid, {"username": name})
    s.commit()
    if email:
        mailer.send(email, "בקשת ההרשמה לא אושרה — Permit360 Pro",
                    "בקשת ההרשמה ל-Permit360 Pro לא אושרה." + (f"\nהערה: {reason.strip()[:500]}" if reason and reason.strip() else "") + "\n")


def waiting_state(s: Session, username: str, password: str) -> str | None:
    """For the login page: the sign-up state of an inactive self-signup login, only after the correct password."""
    from .users import verify_password
    acct = s.get(LoginAccount, (username or "").strip().lower())
    if acct is None or acct.active or acct.signup_state not in (EMAIL_PENDING, APPROVAL_PENDING):
        return None
    return acct.signup_state if verify_password(password or "", acct.password_hash) else None
