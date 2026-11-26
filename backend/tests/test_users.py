"""User management: logins in the database, roles, membership, password changes and revocation."""
from tests.conftest import use_settings
import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import login, users
from app.db import SessionLocal
from app.models import AuthorityMembership, LoginAccount, User
from app.seed import seed

ADMIN_PW = "test-pass-123"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app.main as main
    import app.security as security
    from app.main import app
    seed(reset=True, samples=False)
    settings = dataclasses.replace(main.settings, login_required=True)
    ht = tmp_path / "ht"
    ht.write_text("admin:" + login.apr1(ADMIN_PW, "abcdefgh") + "\n")
    monkeypatch.setenv("BBP_LOGIN_HTPASSWD", str(ht))
    monkeypatch.setenv("BBP_LOGIN_USER_MAP", '{"admin":"u-ha-admin"}')
    use_settings(monkeypatch, settings)
    login._fails.clear()
    yield app
    login._fails.clear()
    with SessionLocal() as s:                      # later test modules use the legacy login
        for a in s.query(LoginAccount).all():
            s.delete(a)
        s.commit()


def client(app, username, password):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


def new_user(admin, username="dana.cohen", role="reviewer", password="Temp-pass-4821"):
    r = admin.post("/api/users", json={"username": username, "display_name": "דנה כהן", "role": role, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_login_must_change_then_work(env):
    admin = client(env, "admin", ADMIN_PW)
    listed = admin.get("/api/users/manage").json()
    assert any(u["id"] == "u-ha-admin" and u["login"] == "legacy" for u in listed["users"])
    u = new_user(admin)
    assert u["username"] == "dana.cohen" and u["must_change"] and u["login"] == "db"
    assert admin.post("/api/users", json={"username": "dana.cohen", "display_name": "x", "role": "reviewer",
                                          "password": "Another-pass-99"}).status_code == 409
    assert admin.post("/api/users", json={"username": "short.pw", "display_name": "x", "role": "reviewer",
                                          "password": "abc"}).status_code == 422
    dana = client(env, "Dana.Cohen", "Temp-pass-4821")          # usernames are case-insensitive
    me = dana.get("/api/me").json()
    assert me["must_change_password"] and me["username"] == "dana.cohen" and me["tenant_id"] == "hof-ashkelon"
    assert dana.get("/api/cases").status_code == 403            # blocked until the password is replaced
    assert dana.post("/api/auth/password", json={"current": "wrong", "new": "Fresh-pass-7319"}).status_code == 422
    assert dana.post("/api/auth/password", json={"current": "Temp-pass-4821", "new": "Fresh-pass-7319"}).status_code == 200
    assert dana.get("/api/cases").status_code == 200            # the new cookie works
    assert dana.get("/api/users/manage").status_code == 403            # a reviewer does not manage users
    assert TestClient(env).post("/api/auth/login", json={"username": "dana.cohen", "password": "Temp-pass-4821"}).status_code == 401


def test_reset_and_deactivate_void_sessions(env):
    admin = client(env, "admin", ADMIN_PW)
    u = new_user(admin)
    dana = client(env, "dana.cohen", "Temp-pass-4821")
    assert dana.get("/api/me").status_code == 200
    assert admin.post(f"/api/users/{u['id']}/password", json={"password": "Reset-pass-5555"}).status_code == 200
    assert dana.get("/api/me").status_code == 401                # old session void
    dana = client(env, "dana.cohen", "Reset-pass-5555")
    assert admin.post(f"/api/users/{u['id']}/active", json={"active": False}).status_code == 200
    assert dana.get("/api/me").status_code == 401
    assert TestClient(env).post("/api/auth/login", json={"username": "dana.cohen", "password": "Reset-pass-5555"}).status_code == 401
    assert admin.post(f"/api/users/{u['id']}/active", json={"active": True}).status_code == 200
    client(env, "dana.cohen", "Reset-pass-5555")


def test_safeguards_and_isolation(env):
    admin = client(env, "admin", ADMIN_PW)
    assert admin.patch("/api/users/u-ha-admin", json={"role": "reviewer"}).status_code == 422   # own role
    assert admin.post("/api/users/u-ha-admin/active", json={"active": False}).status_code == 422
    assert admin.patch("/api/users/u-admin", json={"role": "reviewer"}).status_code == 404   # other authority (demo)
    u = new_user(admin, "second.admin", "sysadmin")
    assert admin.patch(f"/api/users/{u['id']}", json={"role": "dept_manager"}).status_code == 200
    eng = admin.patch("/api/users/u-ha-engineer", json={"display_name": "מהנדס הוועדה"}).json()
    assert eng["display_name"] == "מהנדס הוועדה" and eng["login"] == "none"
    # a user with no login gets one through a reset with a username
    r = admin.post("/api/users/u-ha-engineer/password", json={"password": "Engineer-pass-1", "username": "ha.engineer"})
    assert r.status_code == 200 and r.json()["username"] == "ha.engineer"
    with SessionLocal() as s:     # the last working administrator cannot be demoted, deactivated or removed
        with pytest.raises(ValueError):
            users._keep_an_admin(s, "hof-ashkelon", "u-ha-admin")


def test_member_from_other_authority(env):
    admin = client(env, "admin", ADMIN_PW)
    from app.models import Municipality
    with SessionLocal() as s:     # a login whose home is another authority
        if not s.get(Municipality, "bnei-brak"):
            s.add(Municipality(id="bnei-brak", name_he="בני ברק", is_demo=False, settings={}))
        if not s.get(User, "u-bb-admin"):
            s.add(User(id="u-bb-admin", tenant_id="bnei-brak", display_name="מנהל בני ברק", role="sysadmin"))
        s.flush()
        s.add(LoginAccount(username="bb.admin", user_id="u-bb-admin", password_hash=users.hash_password("Bb-admin-pass-1"),
                           active=True, must_change=False, created_by="test"))
        s.commit()
    r = admin.post("/api/users/members", json={"username": "bb.admin", "role": "reviewer"})
    assert r.status_code == 201 and r.json()["kind"] == "member" and r.json()["home_authority"] == "bnei-brak"
    assert admin.post("/api/users/members", json={"username": "bb.admin", "role": "reviewer"}).status_code == 409
    assert admin.post("/api/users/members", json={"username": "nobody", "role": "reviewer"}).status_code == 404
    actor = r.json()["id"]
    bb = client(env, "bb.admin", "Bb-admin-pass-1")
    assert bb.get("/api/me", headers={"X-Authority": "hof-ashkelon"}).json()["role"] == "reviewer"
    assert admin.post(f"/api/users/{actor}/password", json={"password": "Whatever-pass-1"}).status_code == 422
    assert admin.delete(f"/api/users/{actor}/membership").status_code == 204
    assert bb.get("/api/me", headers={"X-Authority": "hof-ashkelon"}).status_code == 403
    assert all(u["id"] != actor for u in admin.get("/api/users/manage").json()["users"])
    with SessionLocal() as s:     # the actor record stays for the audit trail
        assert s.get(User, actor) and not s.get(AuthorityMembership, ("u-bb-admin", "hof-ashkelon")).active
    r = admin.post("/api/users/members", json={"username": "bb.admin", "role": "dept_manager"})   # re-added
    assert r.status_code == 201 and r.json()["id"] == actor and r.json()["role"] == "dept_manager"
    assert bb.get("/api/me", headers={"X-Authority": "hof-ashkelon"}).json()["role"] == "dept_manager"


def test_legacy_admin_moves_to_database(env):
    admin = client(env, "admin", ADMIN_PW)
    assert admin.post("/api/auth/password", json={"current": ADMIN_PW, "new": "New-secret-pass-77"}).status_code == 200
    with SessionLocal() as s:
        acct = s.get(LoginAccount, "admin")
        assert acct.user_id == "u-ha-admin" and not acct.must_change
    assert TestClient(env).post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW}).status_code == 401
    client(env, "admin", "New-secret-pass-77")


def test_password_hash_and_old_cookies():
    h = users.hash_password("Some-pass-123")
    assert h.startswith("scrypt$") and users.verify_password("Some-pass-123", h) and not users.verify_password("x", h)
    assert not users.verify_password("Some-pass-123", "$apr1$junk")
    import hashlib
    import hmac
    import time
    body = f"u-ha-admin|{int(time.time()) + 600}"          # a cookie issued before issue times were recorded
    old = body + "|" + hmac.new(login._key(), body.encode(), hashlib.sha256).hexdigest()
    assert login.read_session_full(old) == ("u-ha-admin", 0)
