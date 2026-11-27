"""API: login, current user, authorities and user management."""
from fastapi import APIRouter

from ..security import TIERS, WORKSPACE_TENANT, role_of, roles_for, superadmin_ids

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


@router.post("/api/auth/login")
def auth_login(body: LoginIn, request: Request, s: Session = Depends(get_session)):
    from .. import login
    addr = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    if login.throttled(addr):
        raise HTTPException(429, "יותר מדי ניסיונות כניסה — נסו שוב בעוד כמה דקות")
    admin, acct = usermgmt.authenticate(s, body.username, body.password)
    if not admin:
        from .. import signup
        waiting = signup.waiting_state(s, body.username, body.password)
        if waiting:
            raise HTTPException(403, "יש לאמת את כתובת הדוא״ל מהקישור שנשלח" if waiting == signup.EMAIL_PENDING
                                else "בקשת ההרשמה ממתינה לאישור מנהל המערכת")
        login.record_failure(addr)
        known = usermgmt.known_user(s, body.username)
        if known:
            audit.record(s, known.tenant_id, "anonymous", "auth.login_failed", "user", body.username.strip()[:64], {"addr": addr})
            s.commit()
        raise HTTPException(401, "שם משתמש או סיסמה שגויים")
    login.clear_failures(addr)
    if acct:
        acct.last_login_at = usermgmt.now()
    audit.record(s, admin.tenant_id, admin.id, "auth.login", "user", admin.id, {"addr": addr})
    s.commit()
    hours = float(__import__("os").environ.get("BBP_SESSION_HOURS", "12"))
    r = JSONResponse({"ok": True})
    r.set_cookie(login.COOKIE, login.make_session(admin.id, hours), max_age=int(hours * 3600),
                 httponly=True, secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
                 samesite="lax", path="/")
    return r


class SignupIn(BaseModel):
    username: str
    display_name: str
    email: str
    password: str
    profession: str
    license_number: str | None = None
    organization: str | None = None


class RejectIn(BaseModel):
    reason: str | None = None


def _signup_call(fn, *a):
    from .. import signup
    try:
        return fn(*a)
    except signup.SignupError as e:
        raise HTTPException(e.code, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/api/auth/signup")
def signup_info():
    """Whether self sign-up is open, for the login page."""
    from .. import signup
    return {"mode": signup.mode(), "professions": signup.PROFESSIONS}


@router.post("/api/auth/signup", status_code=201)
def signup_request(body: SignupIn, request: Request, s: Session = Depends(get_session)):
    from .. import signup
    addr = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    # the link in the mail comes from server configuration, never from the request's Host header
    base = __import__("os").environ.get("BBP_PUBLIC_URL") or str(request.base_url)
    return _signup_call(lambda: signup.request(s, username=body.username, display_name=body.display_name, email=body.email,
                                               password=body.password, profession=body.profession,
                                               license_number=body.license_number, organization=body.organization,
                                               base_url=base, addr=addr))


@router.get("/api/auth/signup/verify")
def signup_verify(t: str = "", s: Session = Depends(get_session)):
    from fastapi.responses import RedirectResponse
    from .. import signup
    state = signup.verify(s, t)
    return RedirectResponse("/login?signup=" + {"APPROVED": "approved", "APPROVAL_PENDING": "pending"}.get(state, "invalid"), 303)


def _signup_admin(p: Principal) -> None:
    if p.tenant_id != WORKSPACE_TENANT:
        raise HTTPException(403, "בקשות הרשמה מנוהלות בסביבת Permit360 Pro")


@router.get("/api/signups")
def signups_list(p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    from .. import signup
    _signup_admin(p)
    return {"mode": signup.mode(), "items": signup.pending(s)}


@router.post("/api/signups/{username}/approve")
def signups_approve(username: str, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    from .. import signup
    _signup_admin(p)
    return _signup_call(signup.approve, s, p.id, username)


@router.post("/api/signups/{username}/reject", status_code=204)
def signups_reject(username: str, body: RejectIn, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    from .. import signup
    _signup_admin(p)
    _signup_call(signup.reject, s, p.id, username, body.reason)


@router.post("/api/auth/logout")
def auth_logout():
    from ..login import COOKIE
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE, path="/")
    return r


@router.get("/api/me")
def me(p: Principal = Depends(current_user), account: User = Depends(login_account), s: Session = Depends(get_session)):
    from ..models import LoginAccount
    org = s.get(Municipality, p.tenant_id)
    acct = s.scalars(select(LoginAccount).where(LoginAccount.user_id == account.id)).first()
    return {**p.__dict__, "username": usermgmt.username_of(s, account.id), "must_change_password": bool(acct and acct.must_change),
            "municipality_name": org.name_he if org else p.tenant_id, "is_demo": bool(org and org.is_demo), "role_he": ROLES[p.role]["label_he"],
            "tier": "superadmin" if account.id in superadmin_ids() else ROLES[p.role].get("tier"),
            "tier_he": TIERS["superadmin" if account.id in superadmin_ids() else ROLES[p.role].get("tier", "committee_user")],
            "superadmin": account.id in superadmin_ids(), "workspace": p.tenant_id == WORKSPACE_TENANT,
            "assignable_roles": {k: v["label_he"] for k, v in roles_for(p.tenant_id).items()},
            "permissions": sorted(k for k, v in PERMISSIONS.items() if p.role in v)}


@router.get("/api/authorities")
def authority_list(account: User = Depends(login_account), s: Session = Depends(get_session)):
    return {"authorities": authorities.workspaces(s, account), "can_create": authorities.can_create(account)}


@router.post("/api/authorities", status_code=201)
def authority_create(body: AuthorityIn, account: User = Depends(login_account), s: Session = Depends(get_session)):
    try:
        org, actor = authorities.create_authority(s, account, body.id, body.name_he)
    except PermissionError as e: raise HTTPException(403, str(e)) from e
    except FileExistsError as e: raise HTTPException(409, str(e)) from e
    except ValueError as e: raise HTTPException(422, str(e)) from e
    audit.record(s, org.id, actor.id, "authority.create", "municipality", org.id, {"account_id": account.id})
    s.commit()
    authorities.start_onboarding(SessionLocal, org.id, actor.id)
    return {"id": org.id, "name_he": org.name_he, "onboarding": org.settings["onboarding"]}


@router.post("/api/authorities/{tenant}/discover")
def authority_discover(tenant: str, account: User = Depends(login_account), s: Session = Depends(get_session)):
    a = authorities.member(s, account, tenant)
    if not a or a.role not in PERMISSIONS['source.crawl']: raise HTTPException(403, "אין הרשאה לרשות")
    o = s.get(Municipality, tenant)
    if not o: raise HTTPException(404)
    old = o.settings or {}
    if old.get('onboarding', {}).get('state') in authorities.ACTIVE:
        raise HTTPException(409, "איתור מקורות כבר בתהליך")
    s.commit()
    authorities.start_onboarding(SessionLocal, tenant, a.id)
    return {"state":"DISCOVERY_PENDING"}


@router.get("/api/users")
def users(p: Principal = Depends(current_user), s: Session = Depends(get_session)):
    """Only colleagues in the authenticated workspace."""
    return [{"id": u.id, "tenant_id": u.tenant_id, "display_name": u.display_name, "role": u.role,
             "role_he": ROLES[role_of(u.role)]["label_he"]} for u in s.scalars(select(User).where(User.tenant_id == p.tenant_id))]


@router.get("/api/users/manage")
def users_list(p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    return {"users": usermgmt.list_users(s, p.tenant_id),
            "roles": [{"id": k, "label_he": v["label_he"], "tier": v["tier"], "tier_he": TIERS[v["tier"]]} for k, v in roles_for(p.tenant_id).items()]}


@router.post("/api/users", status_code=201)
def users_create(body: UserIn, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    return _users_call(s, usermgmt.create_user, p.tenant_id, p.id, body.username, body.display_name, body.role, body.password)


@router.post("/api/users/members", status_code=201)
def users_add_member(body: MemberIn, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    return _users_call(s, usermgmt.add_member, p.tenant_id, p.id, body.username, body.role)


@router.patch("/api/users/{user_id}")
def users_update(user_id: str, body: UserPatch, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    return _users_call(s, usermgmt.update_user, p.tenant_id, p.id, user_id, body.role, body.display_name)


@router.post("/api/users/{user_id}/active")
def users_active(user_id: str, body: ActiveIn, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    return _users_call(s, usermgmt.set_active, p.tenant_id, p.id, user_id, body.active)


@router.post("/api/users/{user_id}/password")
def users_reset(user_id: str, body: ResetIn, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    return _users_call(s, usermgmt.reset_password, p.tenant_id, p.id, user_id, body.password, body.username)


@router.delete("/api/users/{user_id}/membership", status_code=204)
def users_remove(user_id: str, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    _users_call(s, usermgmt.remove_member, p.tenant_id, p.id, user_id)


@router.post("/api/auth/password")
def auth_password(body: PasswordIn, request: Request, account: User = Depends(login_account), s: Session = Depends(get_session)):
    """The signed-in user replaces their own password; other sessions end, this one gets a new cookie."""
    from .. import login
    _users_call(s, usermgmt.change_own_password, account, body.current, body.new)
    r = JSONResponse({"ok": True})
    if settings.login_required:
        hours = float(__import__("os").environ.get("BBP_SESSION_HOURS", "12"))
        r.set_cookie(login.COOKIE, login.make_session(account.id, hours), max_age=int(hours * 3600),
                     httponly=True, secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
                     samesite="lax", path="/")
    return r
