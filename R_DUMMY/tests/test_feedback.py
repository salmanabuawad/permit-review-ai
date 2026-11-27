"""Professional feedback: override → classified record with a regression candidate → accepted case → regression run."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed


def H(u):
    return {"X-User": u}


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def test_override_feedback_accept_and_regression(client):
    case = next(c for c in client.get("/api/cases", headers=H("u-reviewer")).json() if c["case_number"] == "DEMO-0003")
    run = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rep = client.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=H("u-reviewer")).json()
    f = next(x for x in rep["findings"] if x["status"] in ("FAIL", "UNCERTAIN") and x["rule_id"].startswith(("BB-", "DEMO-")))
    bad = client.post(f"/api/findings/{f['id']}/decision", headers=H("u-reviewer"),
                      json={"decision": "OVERRIDDEN", "note": "המדידה שגויה", "category": "algorithm_defect", "corrected_status": "MAYBE"})
    assert bad.status_code == 422
    r = client.post(f"/api/findings/{f['id']}/decision", headers=H("u-reviewer"),
                    json={"decision": "OVERRIDDEN", "note": "המדידה שגויה — בדקתי בחתך", "category": "algorithm_defect",
                          "corrected_status": "PASS"})
    assert r.status_code == 200 and r.json()["feedback_id"]
    recs = client.get("/api/feedback", headers=H("u-reviewer")).json()["records"]
    rec = next(x for x in recs if x["id"] == r.json()["feedback_id"])
    assert rec["category"] == "algorithm_defect" and rec["has_candidate"] and rec["original"]["status"] == f["status"]
    assert client.post(f"/api/feedback/{rec['id']}/decision", headers=H("u-reviewer"), json={"action": "accept", "note": "כן"}).status_code == 403
    ok = client.post(f"/api/feedback/{rec['id']}/decision", headers=H("u-engineer"), json={"action": "accept", "note": "מקרה בדיקה"})
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    assert client.post(f"/api/feedback/{rec['id']}/decision", headers=H("u-engineer"), json={"action": "dismiss", "note": "שוב"}).status_code == 422
    reg = client.get("/api/feedback/regression", headers=H("u-reviewer")).json()
    assert reg["cases"] == 1 and len(reg["failed"]) == 1 and reg["failed"][0]["expect"] == "PASS"   # the rule is unchanged


def test_application_exception_has_no_candidate(client):
    case = next(c for c in client.get("/api/cases", headers=H("u-reviewer")).json() if c["case_number"] == "DEMO-0003")
    run = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rep = client.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=H("u-reviewer")).json()
    f = next(x for x in rep["findings"] if x["status"] in ("FAIL", "UNCERTAIN"))
    r = client.post(f"/api/findings/{f['id']}/decision", headers=H("u-reviewer"),
                    json={"decision": "OVERRIDDEN", "note": "אושרה הקלה בבקשה זו", "category": "application_exception", "corrected_status": "PASS"})
    rec = next(x for x in client.get("/api/feedback", headers=H("u-reviewer")).json()["records"] if x["id"] == r.json()["feedback_id"])
    assert not rec["has_candidate"]                                       # a case-specific exception is not a general rule
    assert client.post(f"/api/feedback/{rec['id']}/decision", headers=H("u-engineer"), json={"action": "accept", "note": "x x"}).status_code == 422
