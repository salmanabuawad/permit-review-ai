"""RBAC. POC authentication = demo user header (X-User). Production: OIDC/SAML SSO with
MFA enforced by the IdP (see docs/03 §Security); the role model below stays the same.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
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
}

PERMISSIONS = {
    "case.read":       {"sysadmin", "city_engineer", "dept_manager", "reviewer", "secretariat", "planner", "external"},
    "case.create":     {"sysadmin", "dept_manager", "secretariat", "reviewer"},
    "case.upload":     {"sysadmin", "dept_manager", "secretariat", "reviewer", "planner"},
    "file.delete":     {"sysadmin", "dept_manager", "city_engineer"},
    "case.run":        {"sysadmin", "dept_manager", "reviewer"},
    "case.assign":     {"sysadmin", "dept_manager", "city_engineer"},
    "finding.decide":  {"reviewer", "dept_manager", "city_engineer"},
    "case.lock":       {"reviewer", "dept_manager", "city_engineer"},
    "rule.approve":    {"city_engineer", "dept_manager"},
    "source.crawl":    {"sysadmin", "city_engineer", "dept_manager"},
    "ai.configure":    {"sysadmin"},
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


def current_user(x_user: str | None = Header(default=None), s: Session = Depends(get_session)) -> Principal:
    if settings.environment == "production":
        raise HTTPException(501, "Demo header auth is disabled in production — configure SSO/OIDC.")
    uid = x_user or "u-reviewer"
    u = s.get(User, uid)
    if not u:
        raise HTTPException(401, "משתמש לא מוכר")
    return Principal(u.id, u.tenant_id, u.role, u.display_name)


def require(perm: str):
    def dep(p: Principal = Depends(current_user)) -> Principal:
        if not p.can(perm):
            raise HTTPException(403, f"אין הרשאה: {perm}")
        return p
    return dep
