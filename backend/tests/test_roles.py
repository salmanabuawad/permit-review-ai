"""Four user levels: superadmin (platform flag), committee admin, committee user (professional sub-roles), end user
(Permit360 Pro workspace, outside every committee)."""
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Municipality
from app.security import PERMISSIONS, ROLES, TIERS, WORKSPACE_TENANT, roles_for
from app.seed import seed


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BBP_SUPERADMINS", '["u-ha-admin"]')
    seed(reset=True, samples=False)
    with TestClient(app) as c:
        yield c


def test_every_role_has_a_tier_and_tiers_are_four():
    assert set(TIERS) == {"superadmin", "committee_admin", "committee_user", "end_user"}
    assert all(r["tier"] in TIERS for r in ROLES.values())
    assert ROLES["sysadmin"]["tier"] == "committee_admin" and ROLES["reviewer"]["tier"] == "committee_user"
    assert "end_user" not in roles_for("hof-ashkelon") and set(roles_for(WORKSPACE_TENANT)) == {"end_user", "sysadmin"}
    # end users never approve, decide or manage committee data
    for perm in ("rule.approve", "finding.decide", "case.create", "user.manage", "source.crawl", "case.run"):
        assert "end_user" not in PERMISSIONS[perm]


def test_me_reports_tiers(env, monkeypatch):
    assert env.get("/api/me", headers={"X-User": "u-ha-admin"}).json()["tier"] == "superadmin"
    assert env.get("/api/me", headers={"X-User": "u-ha-reviewer"}).json()["tier"] == "committee_user"
    monkeypatch.setenv("BBP_SUPERADMINS", "[]")
    monkeypatch.setenv("BBP_AUTHORITY_CREATORS", "[]")
    me = env.get("/api/me", headers={"X-User": "u-ha-admin"}).json()
    assert me["tier"] == "committee_admin" and not me["superadmin"] and "end_user" not in me["assignable_roles"]


def test_end_users_live_in_the_workspace(env):
    with SessionLocal() as s:
        assert (s.get(Municipality, WORKSPACE_TENANT).settings or {}).get("kind") == "workspace"
    admin = {"X-User": "u-ha-admin"}
    r = env.post("/api/users", json={"username": "eng.one", "display_name": "מהנדס", "role": "end_user",
                                     "password": "Engineer-2026!"}, headers=admin)
    assert r.status_code == 422                                             # not inside a committee
    ws = {**admin, "X-Authority": WORKSPACE_TENANT}
    me = env.get("/api/me", headers=ws).json()
    assert me["workspace"] and set(me["assignable_roles"]) == {"end_user", "sysadmin"}
    r = env.post("/api/users", json={"username": "eng.one", "display_name": "מהנדס", "role": "end_user",
                                     "password": "Engineer-2026!"}, headers=ws)
    assert r.status_code in (200, 201), r.text
    assert env.post("/api/users", json={"username": "rev.ws", "display_name": "x", "role": "reviewer",
                                        "password": "Reviewer-2026!"}, headers=ws).status_code == 422
    uid = r.json()["id"]
    eng = {"X-User": uid}
    me = env.get("/api/me", headers=eng).json()
    assert me["tier"] == "end_user" and me["tenant_id"] == WORKSPACE_TENANT
    assert env.get("/api/committees/directory?q=חוף", headers=eng).status_code == 200      # Pro features
    assert env.get("/api/cases", headers={**eng, "X-Authority": "hof-ashkelon"}).status_code == 403   # no committee data
    listed = env.get("/api/cases", headers=eng).json()
    rows = listed if isinstance(listed, list) else listed.get("cases", listed.get("items", []))
    assert rows == []                                                       # the workspace holds no applications


def test_committee_has_two_roles_and_legacy_rows_still_work():
    from app.security import LEGACY_ROLES, PERMISSIONS, ROLES, role_of, roles_for
    assert set(roles_for("hof-ashkelon")) == {"sysadmin", "reviewer"}
    assert set(roles_for("pro")) == {"sysadmin", "end_user"}
    assert all(role_of(r) in ROLES for r in LEGACY_ROLES)
    admin_only = {k for k, v in PERMISSIONS.items() if v == {"sysadmin"}}
    assert admin_only == {"ai.configure", "source.schedule", "learning.manage", "user.manage"}
    assert all("reviewer" in v for k, v in PERMISSIONS.items() if k not in admin_only and k != "design.create")
