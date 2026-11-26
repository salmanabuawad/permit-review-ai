"""User management for an authority: logins, roles, membership, passwords.

* A home user belongs to one authority (users.tenant_id) and may have a login (login_accounts). Someone from another
  authority is added as a member: an actor user in this authority, linked to their own login (authority_memberships).
* Only the authority's administrator (`user.manage`) manages its users, and only users of that authority.
* Passwords: scrypt, at least 10 characters. An administrator's reset makes the user choose a new one at next login.
  Deactivating a login or resetting its password voids the sessions already issued.
* Safeguards: nobody changes their own role, deactivates or removes themselves, and an authority always keeps one
  working administrator.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .models import AuthorityMembership, LoginAccount, User
from .security import ROLES

USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
MIN_PASSWORD = 10
_N, _R, _P = 2 ** 14, 8, 1


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b(salt)}${b(h)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(h)))
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def check_policy(password: str, username: str = "") -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"סיסמה חייבת לכלול לפחות {MIN_PASSWORD} תווים")
    if username and username.lower() in password.lower():
        raise ValueError("הסיסמה לא יכולה לכלול את שם המשתמש")


def norm_username(username: str) -> str:
    u = (username or "").strip().lower()
    if not USERNAME.fullmatch(u):
        raise ValueError("שם משתמש: 3–64 תווים — אותיות לטיניות קטנות, ספרות, נקודה, מקף או קו תחתון")
    return u


def _legacy_map() -> dict:
    try:
        m = json.loads(os.environ.get("BBP_LOGIN_USER_MAP") or "{}")
        return m if isinstance(m, dict) else {}
    except ValueError:
        return {}


def username_of(s: Session, user_id: str) -> str | None:
    a = s.scalars(select(LoginAccount).where(LoginAccount.user_id == user_id)).first()
    if a:
        return a.username
    return next((k for k, v in _legacy_map().items() if v == user_id), None)


# ------------------------------------------------------------------ login (used by /api/auth/login)

def authenticate(s: Session, username: str, password: str) -> tuple[User | None, LoginAccount | None]:
    """The user for a correct username + password, else (None, None). A username with a database login is checked
    only there; otherwise the legacy htpasswd file and server-side username map apply."""
    from . import login
    from .config import settings
    name = (username or "").strip().lower()
    acct = s.get(LoginAccount, name) if name else None
    if acct is not None:
        if acct.active and verify_password(password or "", acct.password_hash):
            return s.get(User, acct.user_id), acct
        return None, None
    uid = login.resolve_login_user((username or "").strip(), settings.login_user_id)
    if uid and login.check_password((username or "").strip(), password):
        return s.get(User, uid), None
    return None, None


def known_user(s: Session, username: str) -> User | None:
    """The user a username belongs to (for auditing failed logins), without checking any password."""
    from . import login
    from .config import settings
    name = (username or "").strip().lower()
    acct = s.get(LoginAccount, name) if name else None
    uid = acct.user_id if acct else login.resolve_login_user((username or "").strip(), settings.login_user_id)
    return s.get(User, uid) if uid else None


def session_valid(s: Session, user_id: str, issued_at: int) -> bool:
    acct = s.scalars(select(LoginAccount).where(LoginAccount.user_id == user_id)).first()
    if acct is None:
        return True
    if not acct.active:
        return False
    return not (acct.sessions_after and issued_at < int(acct.sessions_after.timestamp() * 1000))   # ms


# ------------------------------------------------------------------ listing

def _actors(s: Session, tenant: str, include_removed: bool = False) -> dict[str, AuthorityMembership]:
    q = select(AuthorityMembership).where(AuthorityMembership.tenant_id == tenant)
    return {m.actor_id: m for m in s.scalars(q) if include_removed or m.active is not False}


def _row(s: Session, u: User, membership: AuthorityMembership | None) -> dict:
    login_user = membership.account_id if membership else u.id
    acct = s.scalars(select(LoginAccount).where(LoginAccount.user_id == login_user)).first()
    home = s.get(User, login_user) if membership else u
    legacy = acct is None and username_of(s, login_user) is not None
    return {"id": u.id, "display_name": u.display_name, "role": u.role, "role_he": ROLES.get(u.role, {}).get("label_he", u.role),
            "kind": "member" if membership else "home",
            "home_authority": home.tenant_id if home else None,
            "username": acct.username if acct else username_of(s, login_user),
            "login": "db" if acct else "legacy" if legacy else "none",
            "active": acct.active if acct else True,
            "must_change": bool(acct and acct.must_change),
            "last_login_at": acct.last_login_at.isoformat() if acct and acct.last_login_at else None}


def list_users(s: Session, tenant: str) -> list[dict]:
    every = _actors(s, tenant, include_removed=True)
    out = []
    for u in s.scalars(select(User).where(User.tenant_id == tenant).order_by(User.display_name)):
        m = every.get(u.id)
        if m is None:
            out.append(_row(s, u, None))
        elif m.active is not False:
            out.append(_row(s, u, m))               # a removed member is no longer listed
    return out


# ------------------------------------------------------------------ safeguards

def _working_admins(s: Session, tenant: str) -> set[str]:
    every = _actors(s, tenant, include_removed=True)
    out = set()
    for u in s.scalars(select(User).where(User.tenant_id == tenant, User.role == "sysadmin")):
        m = every.get(u.id)
        if m is not None:
            if m.active is False:
                continue                            # removed member
            acct = s.scalars(select(LoginAccount).where(LoginAccount.user_id == m.account_id)).first()
        else:
            acct = s.scalars(select(LoginAccount).where(LoginAccount.user_id == u.id)).first()
        if acct is None or acct.active:
            out.add(u.id)
    return out


def _target(s: Session, tenant: str, user_id: str) -> User:
    u = s.get(User, user_id)
    m = s.scalars(select(AuthorityMembership).where(AuthorityMembership.actor_id == user_id)).first()
    if not u or u.tenant_id != tenant or (m is not None and m.active is False):
        raise LookupError("משתמש לא נמצא ברשות זו")
    return u


def _keep_an_admin(s: Session, tenant: str, user_id: str) -> None:
    if _working_admins(s, tenant) <= {user_id}:
        raise ValueError("לרשות חייב להישאר לפחות מנהל מערכת פעיל אחד")


# ------------------------------------------------------------------ operations

def create_user(s: Session, tenant: str, actor: str, username: str, display_name: str, role: str, password: str) -> dict:
    name = norm_username(username)
    if role not in ROLES:
        raise ValueError("תפקיד לא מוכר")
    if not (display_name or "").strip() or len(display_name.strip()) > 200:
        raise ValueError("שם תצוגה חסר או ארוך מדי")
    if s.get(LoginAccount, name) or name in _legacy_map():
        raise FileExistsError("שם המשתמש כבר קיים")
    check_policy(password, name)
    u = User(id=uuid.uuid4().hex, tenant_id=tenant, display_name=display_name.strip(), role=role)
    s.add(u)
    s.flush()
    s.add(LoginAccount(username=name, user_id=u.id, password_hash=hash_password(password), active=True,
                       must_change=True, created_by=actor))
    audit.record(s, tenant, actor, "user.create", "user", u.id, {"username": name, "role": role})
    s.flush()
    return _row(s, u, None)


def add_member(s: Session, tenant: str, actor: str, username: str, role: str) -> dict:
    """Give an existing login from another authority access to this one, with a role here."""
    name = (username or "").strip().lower()
    if role not in ROLES:
        raise ValueError("תפקיד לא מוכר")
    acct = s.get(LoginAccount, name)
    account_id = acct.user_id if acct else _legacy_map().get(name)
    account = s.get(User, account_id) if account_id else None
    if not account:
        raise LookupError("לא נמצא חשבון כניסה בשם זה")
    if account.tenant_id == tenant:
        raise FileExistsError("המשתמש כבר שייך לרשות זו")
    old = s.get(AuthorityMembership, (account.id, tenant))
    if old and old.active is not False:
        raise FileExistsError("המשתמש כבר חבר ברשות זו")
    if old:                                         # re-added: the same actor record, with the role given now
        a = s.get(User, old.actor_id)
        a.role, old.active = role, True
        audit.record(s, tenant, actor, "user.member_add", "user", a.id, {"username": name, "role": role, "restored": True})
        s.flush()
        return _row(s, a, old)
    a = User(id=uuid.uuid4().hex, tenant_id=tenant, display_name=account.display_name, role=role)
    s.add(a)
    s.flush()
    m = AuthorityMembership(account_id=account.id, tenant_id=tenant, actor_id=a.id)
    s.add(m)
    audit.record(s, tenant, actor, "user.member_add", "user", a.id, {"username": name, "role": role})
    s.flush()
    return _row(s, a, m)


def update_user(s: Session, tenant: str, actor: str, user_id: str, role: str | None, display_name: str | None) -> dict:
    u = _target(s, tenant, user_id)
    change = {}
    if role is not None and role != u.role:
        if role not in ROLES:
            raise ValueError("תפקיד לא מוכר")
        if user_id == actor:
            raise ValueError("לא ניתן לשנות את התפקיד של עצמך")
        if u.role == "sysadmin":
            _keep_an_admin(s, tenant, user_id)
        change["role"] = [u.role, role]
        u.role = role
    if display_name is not None and display_name.strip() != u.display_name:
        if not display_name.strip() or len(display_name.strip()) > 200:
            raise ValueError("שם תצוגה חסר או ארוך מדי")
        change["display_name"] = [u.display_name, display_name.strip()]
        u.display_name = display_name.strip()
    if change:
        audit.record(s, tenant, actor, "user.update", "user", u.id, change)
    s.flush()
    return _row(s, u, _actors(s, tenant).get(u.id))


def _home_login(s: Session, tenant: str, user_id: str) -> tuple[User, LoginAccount | None]:
    u = _target(s, tenant, user_id)
    if u.id in _actors(s, tenant, include_removed=True):
        raise ValueError("משתמש מרשות אחרת — הכניסה שלו מנוהלת ברשות הבית שלו")
    return u, s.scalars(select(LoginAccount).where(LoginAccount.user_id == u.id)).first()


def set_active(s: Session, tenant: str, actor: str, user_id: str, active: bool) -> dict:
    u, acct = _home_login(s, tenant, user_id)
    if acct is None:
        raise ValueError("למשתמש אין כניסה המנוהלת במערכת")
    if not active:
        if user_id == actor:
            raise ValueError("לא ניתן להשבית את עצמך")
        if u.role == "sysadmin":
            _keep_an_admin(s, tenant, user_id)
        acct.sessions_after = now()
    acct.active = active
    audit.record(s, tenant, actor, "user.activate" if active else "user.deactivate", "user", u.id, {"username": acct.username})
    s.flush()
    return _row(s, u, None)


def reset_password(s: Session, tenant: str, actor: str, user_id: str, password: str, username: str | None = None) -> dict:
    """Set a temporary password the user must replace at next login. A home user without a login gets one here."""
    u, acct = _home_login(s, tenant, user_id)
    if acct is None:
        if username_of(s, u.id):
            raise ValueError("הכניסה של משתמש זה מוגדרת בשרת — הוא יכול להחליף סיסמה בעצמו")
        name = norm_username(username or "")
        if s.get(LoginAccount, name) or name in _legacy_map():
            raise FileExistsError("שם המשתמש כבר קיים")
        check_policy(password, name)
        acct = LoginAccount(username=name, user_id=u.id, password_hash="", active=True, must_change=True, created_by=actor)
        s.add(acct)
    check_policy(password, acct.username)
    acct.password_hash, acct.must_change = hash_password(password), True
    acct.sessions_after, acct.password_changed_at = now(), now()
    audit.record(s, tenant, actor, "user.password_reset", "user", u.id, {"username": acct.username})
    s.flush()
    return _row(s, u, None)


def remove_member(s: Session, tenant: str, actor: str, user_id: str) -> None:
    """Revoke a member's access to this authority. Their actor record stays for the audit trail."""
    u = _target(s, tenant, user_id)
    m = _actors(s, tenant).get(u.id)
    if not m:
        raise ValueError("רק משתמש מרשות אחרת מוסר מהרשות; משתמש של הרשות מושבת")
    if user_id == actor:
        raise ValueError("לא ניתן להסיר את עצמך")
    if u.role == "sysadmin":
        _keep_an_admin(s, tenant, user_id)
    m.active = False
    audit.record(s, tenant, actor, "user.member_remove", "user", u.id, {"account": m.account_id})
    s.flush()


def change_own_password(s: Session, account: User, current: str, new: str) -> LoginAccount:
    """The signed-in user replaces their password. A legacy (htpasswd) login moves into the database here."""
    acct = s.scalars(select(LoginAccount).where(LoginAccount.user_id == account.id)).first()
    if acct is not None:
        if not verify_password(current or "", acct.password_hash):
            raise PermissionError("הסיסמה הנוכחית שגויה")
    else:
        from . import login
        name = username_of(s, account.id)
        if not name or not login.check_password(name, current or ""):
            raise PermissionError("הסיסמה הנוכחית שגויה")
        acct = LoginAccount(username=name.lower(), user_id=account.id, password_hash="", active=True,
                            must_change=False, created_by=account.id)
        s.add(acct)
    check_policy(new, acct.username)
    if current == new:
        raise ValueError("הסיסמה החדשה זהה לנוכחית")
    acct.password_hash, acct.must_change = hash_password(new), False
    acct.password_changed_at = acct.sessions_after = now()
    audit.record(s, account.tenant_id, account.id, "user.password_change", "user", account.id, {"username": acct.username})
    s.flush()
    return acct
