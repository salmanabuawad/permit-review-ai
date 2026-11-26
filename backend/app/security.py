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

ROLES = {
    "sysadmin":      {"label_he": "מנהל מערכת"},
    "city_engineer": {"label_he": "מהנדס העיר"},
    "dept_manager":  {"label_he": "מנהל אגף"},
    "reviewer":      {"label_he": "בודק תכניות"},
    "planner":       {"label_he": "מתכנן/עורך בקשה"},
    "secretariat":   {"label_he": "מזכירות"},
    "external":      {"label_he": "גורם חיצוני מאושר"},
    "inspector":     {"label_he": "פקח/ית בנייה"},
}

PERMISSIONS = {
    "case.read":       {"sysadmin", "city_engineer", "dept_manager", "reviewer", "secretariat", "planner", "external", "inspector"},
    "inspection.manage": {"sysadmin", "dept_manager", "city_engineer", "inspector"},   # Construction360 site inspections
    "case.create":     {"sysadmin", "dept_manager", "secretariat", "reviewer"},
    "case.upload":     {"sysadmin", "dept_manager", "secretariat", "reviewer", "planner"},
    "file.delete":     {"sysadmin", "dept_manager", "city_engineer"},
    "case.run":        {"sysadmin", "dept_manager", "reviewer"},
    "design.create":   {"sysadmin", "planner"},                          # Architect360: private pre-submission designs
    "case.assign":     {"sysadmin", "dept_manager", "city_engineer"},
    # single-user deployment: the system administrator does the professional steps too
    "finding.decide":  {"sysadmin", "reviewer", "dept_manager", "city_engineer"},
    "case.lock":       {"sysadmin", "reviewer", "dept_manager", "city_engineer"},
    "rule.approve":    {"sysadmin", "city_engineer", "dept_manager"},
    "source.crawl":    {"sysadmin", "city_engineer", "dept_manager"},
    "rule.edit":       {"sysadmin", "city_engineer", "dept_manager"},   # authoring; approval stays rule.approve
    "ai.configure":    {"sysadmin"},
    "source.schedule": {"sysadmin"},                                    # crawl on demand only, or daily / weekly
    "learning.manage": {"sysadmin"},                                    # load decided cases to learn from
    "user.manage":     {"sysadmin"},                                    # users, roles and logins of the authority
    "audit.read":      {"sysadmin", "city_engineer", "dept_manager"},
    "dashboard.read":  {"sysadmin", "city_engineer", "dept_manager"},
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
    return Principal(u.id, u.tenant_id, u.role, u.display_name)


def require(perm: str):
    def dep(p: Principal = Depends(current_user)) -> Principal:
        if not p.can(perm):
            raise HTTPException(403, f"אין הרשאה: {perm}")
        return p
    return dep
