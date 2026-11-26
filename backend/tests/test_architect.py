"""Architect360: private designs, pre-submission check, readiness estimate, comparison."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed

from .conftest import FIX


def H(u):
    return {"X-User": u}


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def _design(client, title, extra=None):
    r = client.post("/api/designs", headers=H("u-planner"), json={"title": title, "permit_type": "addition_extension",
                    "applicable_plans": ["DEMO/1"], "declared": extra or {}})
    assert r.status_code == 201, r.text
    d = r.json()
    up = client.post(f"/api/cases/{d['id']}/files", headers=H("u-planner"),
                     files={"file": ("plan.dxf", (FIX / "case1_extension_exceeds.dxf").read_bytes())}, data={"doc_type": "architectural_plan"})
    assert up.status_code == 200, up.text
    return d


def test_design_is_private_and_checked(client):
    d = _design(client, "תוספת — חלופה א")
    assert d["case_number"].startswith("DES-")
    assert all(c["id"] != d["id"] for c in client.get("/api/cases", headers=H("u-reviewer")).json())   # not in the authority list
    assert client.get(f"/api/cases/{d['id']}", headers=H("u-reviewer")).status_code == 404            # not visible to staff
    assert client.get(f"/api/cases/{d['id']}", headers=H("u-admin")).status_code == 200               # system administrator
    assert client.post(f"/api/designs/{d['id']}/check", headers=H("u-reviewer")).status_code == 403
    r = client.post(f"/api/designs/{d['id']}/check", headers=H("u-planner"))
    assert r.status_code == 200, r.text
    rd = r.json()["readiness"]
    assert 0 <= rd["score"] <= 100 and rd["applicable"] > 0 and "note" in rd
    assert rd["ready"] is False and rd["blockers"]                                   # the fixture exceeds the building line
    mine = client.get("/api/designs", headers=H("u-planner")).json()
    assert [x["id"] for x in mine] == [d["id"]]


def test_compare_two_designs(client):
    a = next(x for x in client.get("/api/designs", headers=H("u-planner")).json())
    b = _design(client, "תוספת — חלופה ב")
    assert client.get(f"/api/designs/compare?a={a['id']}&b={b['id']}", headers=H("u-planner")).status_code == 422   # b not checked
    client.post(f"/api/designs/{b['id']}/check", headers=H("u-planner"))
    cmp = client.get(f"/api/designs/compare?a={a['id']}&b={b['id']}", headers=H("u-planner")).json()
    assert set(cmp) >= {"better", "worse", "same_open", "a", "b"} and cmp["a"]["readiness"] and cmp["b"]["readiness"]
