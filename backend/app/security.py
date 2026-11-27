"""RBAC. POC authentication = demo user header (X-User). Production: OIDC/SAML SSO with
MFA enforced by the IdP (see docs/03 §Security); the role model below stays the same.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import User

# Four user levels. Superadmin is a platform flag on a login (server configuration, BBP_SUPERADMINS), not a role that
# anyone grants in the application. A committee (authority tenant) has two roles only: its administrator and reviewers,
# who do all the professional work. End users (engineers / architects, Permit360 Pro) live in the Pro workspace,
# outside any committee, and see only their own projects.
TIERS = {"superadmin": "מנהל־על (פלטפורמה)", "committee_admin": "מנהל ועדה", "committee_user": "משתמש ועדה",
         "end_user": "משתמש קצה — מהנדס / אדריכל"}
ROLES = {
    "sysadmin":      {"label_he": "מנהל/ת ועדה", "tier": "committee_admin"},
    "reviewer":      {"label_he": "בודק/ת", "tier": "committee_user"},
    "end_user":      {"label_he": "מהנדס/ת / אדריכל/ית", "tier": "end_user"},
}
# former committee roles (before 2026-11-27): read as their successor, so an old row or token never fails
LEGACY_ROLES = {"city_engineer": "reviewer", "dept_manager": "reviewer", "secretariat": "reviewer", "inspector": "reviewer",
                "external": "reviewer", "planner": "end_user"}


def role_of(role: str) -> str:
    return LEGACY_ROLES.get(role, role)


WORKSPACE_TENANT = "pro"                      # the end users' workspace (no committee, no applications)
WORKSPACE_ROLES = {"end_user", "sysadmin"}    # sysadmin there = the superadmin administering end users


def roles_for(tenant: str) -> dict:
    """The roles that may be given in a tenant: end users only in the Pro workspace, committee roles elsewhere."""
    if tenant == WORKSPACE_TENANT:
        return {k: v for k, v in ROLES.items() if k in WORKSPACE_ROLES}
    return {k: v for k, v in ROLES.items() if k not in WORKSPACE_ROLES or k == "sysadmin"}


def superadmin_ids() -> set[str]:
    import json as _json
    import os as _os
    out: set[str] = set()
    for var in ("BBP_SUPERADMINS", "BBP_AUTHORITY_CREATORS"):
        try:
            v = _json.loads(_os.environ.get(var, "[]"))
            out |= {str(x) for x in v} if isinstance(v, list) else set()
        except ValueError:
            pass
    return out

_COMMITTEE = {"sysadmin", "reviewer"}
PERMISSIONS = {
    "case.read":       _COMMITTEE | {"end_user"},
    "inspection.manage": _COMMITTEE,                                    # Construction360 site inspections
    "case.create":     _COMMITTEE,
    "case.upload":     _COMMITTEE | {"end_user"},
    "file.delete":     _COMMITTEE,
    "case.run":        _COMMITTEE,
    "design.create":   {"sysadmin", "end_user"},                        # Architect360 / Pro projects: private designs
    "case.assign":     _COMMITTEE,
    "finding.decide":  _COMMITTEE,
    "case.lock":       _COMMITTEE,
    "rule.approve":    _COMMITTEE,
    "source.crawl":    _COMMITTEE,
    "rule.edit":       _COMMITTEE,                                      # authoring; approval stays rule.approve
    "audit.read":      _COMMITTEE,
    "dashboard.read":  _COMMITTEE,
    # the committee administrator only
    "ai.configure":    {"sysadmin"},
    "source.schedule": {"sysadmin"},                                    # crawl on demand only, or daily / weekly
    "learning.manage": {"sysadmin"},                                    # load decided cases to learn from
    "user.manage":     {"sysadmin"},                                    # users, roles and logins of the authority
}


@dataclass
class Principal:
    id: str
    tenant_id: str
    role: str
    display_name: str

    def can(self, perm: str) -> bool:
        return self.role in PERMISSIONS.get(perm, set())


# while an administrator-set password waits to be replaced, only these answer
MUST_CHANGE_OPEN = ("/api/me", "/api/meta", "/api/auth/", "/api/authorities")


def login_account(request: Request, x_user: str | None = Header(default=None),
                  bbp_session: str | None = Cookie(default=None), s: Session = Depends(get_session)) -> User:
    if settings.login_required:                       # app login: the signed session cookie names the user
        from .login import read_session_full
        from .users import session_valid
        from .models import LoginAccount
        got = read_session_full(bbp_session)
        u = s.get(User, got[0]) if got else None
        if not u or not session_valid(s, u.id, got[1]):
            raise HTTPException(401, "נדרשת כניסה למערכת")
        acct = s.scalars(select(LoginAccount).where(LoginAccount.user_id == u.id)).first()
        if acct and acct.must_change and not request.url.path.startswith(MUST_CHANGE_OPEN):
            raise HTTPException(403, "נדרשת החלפת סיסמה")
        return u
    if settings.environment == "production":
        raise HTTPException(501, "Demo header auth is disabled in production — configure SSO/OIDC.")
    uid = x_user or "u-reviewer"
    u = s.get(User, uid)
    if not u:
        raise HTTPException(401, "משתמש לא מוכר")
    return u


def current_user(account: User = Depends(login_account), x_authority: str | None = Header(default=None),
                 s: Session = Depends(get_session)) -> Principal:
    from .authority_onboarding import member
    u = member(s, account, x_authority)
    if not u:
        raise HTTPException(403, "אין הרשאה לרשות שנבחרה")
    return Principal(u.id, u.tenant_id, role_of(u.role), u.display_name)


def require(perm: str):
    def dep(p: Principal = Depends(current_user)) -> Principal:
        if not p.can(perm):
            raise HTTPException(403, f"אין הרשאה: {perm}")
        return p
    return dep
