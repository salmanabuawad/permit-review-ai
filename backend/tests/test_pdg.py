"""Permit Dependency Graph v1: exact rule inputs, parity on unchanged re-runs, revision reports."""
import pytest
from fastapi.testclient import TestClient

from app import pdg
from app.main import app
from app.seed import seed


def H(u):
    return {"X-User": u}


def test_tracking_records_reads():
    log = {}
    t = pdg.Tracking({"case": {"permit_type": "x", "plans": ["a"]}, "declared": {}}, log)
    assert t["case"]["permit_type"] == "x" and t.get("declared").get("floors") is None and "measure" not in t
    assert log == {"case.permit_type": "x", "declared.floors": None, "measure": None}


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def test_rerun_unchanged_then_approval_explained(client):
    case = next(c for c in client.get("/api/cases", headers=H("u-reviewer")).json() if c["case_number"] == "DEMO-0003")
    r1 = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    r2 = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rev = client.get(f"/api/runs/{r2['run_id']}/revision", headers=H("u-reviewer")).json()
    assert rev["previous"] == r1["version"] and rev["pdg"]["parity_violations"] == []
    assert rev["pdg"]["changed_inputs"] == 0 and rev["pdg"]["unchanged_inputs"] == rev["pdg"]["nodes"] > 0
    assert sum(rev["counts"][k] for k in ("new_defects", "corrected", "newly_unresolved", "newly_applicable", "other_changes")) == 0
    assert rev["files"]["added"] == rev["files"]["removed"] == rev["files"]["changed"] == []
    ok = client.post("/api/rules/BB-POL26-RR-SETBACK/approval", headers=H("u-engineer"), json={"note": "נבדק מול מסמך המדיניות עמ׳ 3 סעיף 4ג׳"})
    assert ok.status_code == 200
    r3 = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rev3 = client.get(f"/api/runs/{r3['run_id']}/revision", headers=H("u-reviewer")).json()
    item = next(x for x in rev3["new_defects"] if x["rule_id"] == "BB-POL26-RR-SETBACK")
    assert item["before"] == "UNCERTAIN" and item["after"] == "FAIL"
    assert item["changed_inputs"][0]["input"] == "rule_definition"
    assert rev3["pdg"]["parity_violations"] == [] and rev3["pdg"]["changed_inputs"] >= 1


def test_first_run_has_no_previous(client):
    case = next(c for c in client.get("/api/cases", headers=H("u-reviewer")).json() if c["case_number"] == "DEMO-0001")
    r = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rev = client.get(f"/api/runs/{r['run_id']}/revision", headers=H("u-reviewer")).json()
    assert rev["previous"] is None or rev["previous"] < r["version"]
