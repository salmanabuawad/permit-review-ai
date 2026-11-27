"""End-user self sign-up: e-mail verification, superadmin approval, safeguards."""
import re

import pytest
from fastapi.testclient import TestClient

from app import mailer, signup
from app.db import SessionLocal
from app.main import app
from app.models import LoginAccount, User
from app.security import WORKSPACE_TENANT
from app.seed import seed

FORM = {"username": "dana.eng", "display_name": "דנה מהנדסת", "email": "Dana@Example.com", "password": "Long-enough-pw-1",
        "profession": "engineer", "license_number": "12345"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BBP_SUPERADMINS", '["u-ha-admin"]')
    seed(reset=True, samples=False)
    sent = []
    monkeypatch.setattr(mailer, "transport", sent)
    monkeypatch.setenv("BBP_SIGNUP_NOTIFY", "ops@example.org")
    monkeypatch.setenv("BBP_PUBLIC_URL", "https://permit.example.org")
    monkeypatch.setattr(signup, "_hits", {})
    with TestClient(app) as c:
        yield c, sent


def link(msg):
    return re.search(r"https://\S+", msg.get_content()).group(0)


def admin_headers():
    """The superadmin's seat in the Pro workspace (created at startup by ensure_workspace)."""
    from app.models import AuthorityMembership
    from app.security import superadmin_ids
    from sqlalchemy import select
    with SessionLocal() as s:
        assert superadmin_ids() and s.get(AuthorityMembership, ("u-ha-admin", WORKSPACE_TENANT))
    return {"X-User": "u-ha-admin", "X-Authority": WORKSPACE_TENANT}


def test_signup_verify_approve_login(env):
    c, sent = env
    assert c.get("/api/auth/signup").json()["mode"] == "approval"
    r = c.post("/api/auth/signup", json=FORM)
    assert r.status_code == 201 and r.json()["state"] == "EMAIL_PENDING"
    assert sent[0]["To"] == "dana@example.com" and link(sent[0]).startswith("https://permit.example.org/api/auth/signup/verify?t=")
    with SessionLocal() as s:
        a = s.get(LoginAccount, "dana.eng")
        u = s.get(User, a.user_id)
        assert not a.active and u.tenant_id == WORKSPACE_TENANT and u.role == "end_user" and a.signup_info["license_number"] == "12345"
    # cannot log in before verifying, and says why (only with the right password)
    r = c.post("/api/auth/login", json={"username": "dana.eng", "password": FORM["password"]})
    assert r.status_code == 403 and "לאמת" in r.json()["detail"]
    assert c.post("/api/auth/login", json={"username": "dana.eng", "password": "wrong-password-x"}).status_code == 401
    h = admin_headers()
    assert c.post("/api/signups/dana.eng/approve", headers=h).status_code == 409             # not verified yet
    # verification link
    r = c.get(link(sent[0]).replace("https://permit.example.org", ""), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?signup=pending"
    assert sent[-1]["To"] == "ops@example.org"
    r = c.post("/api/auth/login", json={"username": "dana.eng", "password": FORM["password"]})
    assert r.status_code == 403 and "ממתינה" in r.json()["detail"]
    items = c.get("/api/signups", headers=h).json()["items"]
    assert [i["username"] for i in items] == ["dana.eng"] and items[0]["state"] == "APPROVAL_PENDING"
    # activation through the users page is refused; approval is the way
    with SessionLocal() as s:
        uid = s.get(LoginAccount, "dana.eng").user_id
    assert c.post(f"/api/users/{uid}/active", json={"active": True}, headers=h).status_code == 422
    assert c.post("/api/signups/dana.eng/approve", headers=h).status_code == 200
    assert sent[-1]["To"] == "dana@example.com" and "אושר" in sent[-1]["Subject"]
    assert c.post("/api/auth/login", json={"username": "dana.eng", "password": FORM["password"]}).status_code == 200


def test_reject_frees_username_and_bad_links(env):
    c, sent = env
    c.post("/api/auth/signup", json=FORM)
    assert c.get("/api/auth/signup/verify?t=dana.eng|9999999999|bad", follow_redirects=False).headers["location"] == "/?signup=invalid"
    assert c.post("/api/auth/signup", json={**FORM, "username": "other.eng"}).status_code == 409      # same e-mail
    assert c.post("/api/auth/signup", json={**FORM, "email": "x@example.com"}).status_code == 409       # same username
    h = admin_headers()
    assert c.post("/api/signups/dana.eng/reject", json={"reason": "חסר מספר רישיון"}, headers=h).status_code == 204
    assert "לא אושרה" in sent[-1]["Subject"] and "רישיון" in sent[-1].get_content()
    with SessionLocal() as s:
        assert s.get(LoginAccount, "dana.eng") is None
    assert c.post("/api/auth/signup", json=FORM).status_code == 201


def test_safeguards(env, monkeypatch):
    c, sent = env
    assert c.post("/api/auth/signup", json={**FORM, "password": "short"}).status_code == 422
    assert c.post("/api/auth/signup", json={**FORM, "username": "a", "email": "a@b.co"}).status_code == 422
    assert c.post("/api/auth/signup", json={**FORM, "email": "not-an-email"}).status_code == 422
    assert c.post("/api/auth/signup", json={**FORM, "profession": "sysadmin"}).status_code == 422     # no role choice
    monkeypatch.setattr(signup, "_hits", {})
    for i in range(3):
        c.post("/api/auth/signup", json={**FORM, "username": f"u{i}.eng", "email": f"u{i}@example.com"})
    assert c.post("/api/auth/signup", json={**FORM, "username": "u9.eng", "email": "u9@example.com"}).status_code == 429
    # committee administrators cannot see or approve Pro sign-ups
    assert c.get("/api/signups", headers={"X-User": "u-ha-admin", "X-Authority": "hof-ashkelon"}).status_code == 403
    monkeypatch.setattr(signup, "_hits", {})
    monkeypatch.setenv("BBP_SIGNUP", "off")
    assert c.get("/api/auth/signup").json()["mode"] == "off"
    assert c.post("/api/auth/signup", json={**FORM, "username": "z.eng", "email": "z@example.com"}).status_code == 403


def test_open_mode_and_no_mail(env, monkeypatch):
    c, sent = env
    monkeypatch.setenv("BBP_SIGNUP", "open")
    c.post("/api/auth/signup", json=FORM)
    assert c.get(link(sent[0]).replace("https://permit.example.org", ""), follow_redirects=False).headers["location"] == "/?signup=approved"
    assert c.post("/api/auth/login", json={"username": "dana.eng", "password": FORM["password"]}).status_code == 200
    monkeypatch.setattr(mailer, "transport", None)
    monkeypatch.delenv("BBP_SMTP_HOST", raising=False)
    assert c.get("/api/auth/signup").json()["mode"] == "off"                     # no unverified addresses


def test_expired_requests_are_purged(env):
    import datetime as dt
    c, sent = env
    c.post("/api/auth/signup", json=FORM)
    with SessionLocal() as s:
        s.get(LoginAccount, "dana.eng").created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=49)
        s.commit()
        assert signup.purge_expired(s) == 1
        s.commit()
        assert s.get(LoginAccount, "dana.eng") is None
