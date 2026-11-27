"""API: login, current user, authorities and user management."""
from fastapi import APIRouter

from ..security import TIERS, WORKSPACE_TENANT, roles_for, superadmin_ids

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
             "role_he": ROLES[u.role]["label_he"]} for u in s.scalars(select(User).where(User.tenant_id == p.tenant_id))]


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
