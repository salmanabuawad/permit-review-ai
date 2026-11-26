"""App login: apr1 verification, signed sessions, the /api gate."""
from fastapi.testclient import TestClient

from app import login


def test_apr1_matches_openssl():
    assert login.apr1("test-pass-123", "abcdefgh") == "$apr1$abcdefgh$nWF.F2m3Yfr/9KzmgTlo4."
    assert login.apr1("שלום-עולם", "Zq9.x/AB") == "$apr1$Zq9.x/AB$FGuxVd4.WzVvm1ryLAbHD."


def test_session_roundtrip_and_tamper():
    t = login.make_session("u-ha-admin", 1)
    assert login.read_session(t) == "u-ha-admin"
    assert login.read_session(t.replace("u-ha-admin", "u-other")) is None
    assert login.read_session(login.make_session("u-ha-admin", -1)) is None
    assert login.read_session("junk") is None and login.read_session(None) is None


def test_gate_and_login(tmp_path, monkeypatch):
    import dataclasses

    import app.main as main
    import app.security as security
    from app.main import app
    settings = dataclasses.replace(main.settings, login_required=True)
    ht = tmp_path / "ht"
    ht.write_text("admin:" + login.apr1("test-pass-123", "abcdefgh") + "\n")
    monkeypatch.setenv("BBP_LOGIN_HTPASSWD", str(ht))
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(security, "settings", settings)
    login._fails.clear()
    c = TestClient(app)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/cases").status_code == 401
    assert c.get("/api/me", headers={"X-User": "u-ha-admin"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "admin", "password": "test-pass-123"}).status_code == 200
    me = c.get("/api/me")
    assert me.status_code == 200 and me.json()["id"] == settings.login_user_id
    assert c.post("/api/auth/logout").status_code == 200
    c.cookies.clear()
    assert c.get("/api/me").status_code == 401
    for _ in range(5):
        c.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert c.post("/api/auth/login", json={"username": "admin", "password": "test-pass-123"}).status_code == 429
    login._fails.clear()
