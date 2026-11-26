"""Learning from decided cases: the decision is compared with the engine's review; the knowledge base learns at once
(decision document, passages, precedent, rule statistics); missing checks become rule drafts awaiting approval."""
import pytest
from fastapi.testclient import TestClient

from app import learning
from app.main import app
from app.seed import seed

ADMIN = {"X-User": "u-admin"}
REVIEWER = {"X-User": "u-reviewer"}

REJECTION = ("הוחלט לדחות את הבקשה מהנימוקים הבאים: 1. הבקשה חורגת מקו הבניין האחורי המותר. "
             "2. לא צורפה הסכמת בעלי הזכויות במגרש. 3. חריגה בשטח העיקרי מעבר לשטחים המותרים.")


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def case(c, number):
    cs = c.get("/api/cases", headers=ADMIN).json()
    x = next(x for x in cs if x["case_number"] == number)
    if not x["last_run"]:
        c.post(f"/api/cases/{x['id']}/run", headers=ADMIN)
    return x


def test_parse_decision_outcome_reasons_and_topics():
    d = learning.parse_decision(REJECTION)
    assert d["outcome"] == "rejected"
    assert [r["no"] for r in d["reasons"] if r["no"]] == ["1", "2", "3"]
    by_no = {r["no"]: r["topics"] for r in d["reasons"]}
    assert "building_lines" in by_no["1"] and "ownership_consent" in by_no["2"] and "rights_area" in by_no["3"]
    assert learning.parse_decision("הוחלט לאשר את הבקשה בתנאים הבאים: 1. תיאום עם תאגיד המים.")["outcome"] == \
        "approved_with_conditions"


def test_only_the_admin_loads_decisions(client):
    x = case(client, "DEMO-0001")
    assert client.post(f"/api/cases/{x['id']}/decision", data={"text": REJECTION}, headers=REVIEWER).status_code == 403
    assert client.post(f"/api/cases/{x['id']}/decision", data={}, headers=ADMIN).status_code == 422
    assert client.post(f"/api/cases/{x['id']}/decision", data={"text": REJECTION, "outcome": "maybe"},
                       headers=ADMIN).status_code == 422


def test_rejection_is_learned_into_the_knowledge_base(client):
    x = case(client, "DEMO-0001")                          # the engine finds the building-line deviation
    r = client.post(f"/api/cases/{x['id']}/decision", data={"text": REJECTION}, headers=ADMIN)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["status"] == "done" and rec["outcome"] == "rejected"
    res = rec["result"]
    assert any("building_lines" in f["topics"] for f in res["confirmed"])          # engine and committee agree
    missed = {t for m in res["missed"] for t in m["topics"]}
    assert "ownership_consent" in missed                                         # the engine did not check it
    assert res["drafts_created"] == len(res["missed"]) >= 1
    # missing checks are drafts in the existing workflow — never active rules
    drafts = client.get(f"/api/source-monitor/documents/{rec['source_document_id']}/drafts", headers=ADMIN).json()
    reasons = [d for d in drafts if d["kind"] == "committee_reason"]
    assert reasons and all(d["status"] == "open" for d in reasons)
    # the decision text is searchable knowledge of this authority (unverified)
    hits = client.get("/api/knowledge/candidates?q=הסכמת בעלי הזכויות", headers=ADMIN).json()
    assert any(h["document_id"] == rec["source_document_id"] for h in hits)
    # rule statistics: the building-line rule was confirmed by a committee
    stats = client.get("/api/learning", headers=ADMIN).json()["rule_stats"]
    assert any(v["confirmed"] >= 1 for v in stats.values())


def test_precedent_shown_on_a_similar_request_and_correction_supersedes(client):
    other = case(client, "DEMO-0002")                      # shares plan DEMO/1 with DEMO-0001
    p = client.get(f"/api/cases/{other['id']}/decision", headers=REVIEWER).json()
    assert p["record"] is None
    assert any(x["case_number"] == "DEMO-0001" and "DEMO/1" in x["plans"] and not x["approved"] for x in p["precedents"])
    x = case(client, "DEMO-0001")
    r = client.post(f"/api/cases/{x['id']}/decision", data={"text": "הוחלט לאשר את הבקשה."}, headers=ADMIN).json()
    assert r["outcome"] == "approved" and r["result"]["missed"] == []          # approval: nothing missed
    assert len([y for y in client.get("/api/learning", headers=ADMIN).json()["records"]
                if y["case_id"] == x["id"]]) == 1                                # the earlier record is superseded


def test_learning_waits_for_the_review(client):
    """A case still being processed is learned later by the worker, not compared with a partial review."""
    from app.db import SessionLocal
    from app.models import LearningRecord, PermitCase
    x = case(client, "DEMO-0003")
    with SessionLocal() as s:
        c = s.get(PermitCase, x["id"])
        rec = learning.record_decision(s, c, "u-admin", "d.txt", REJECTION.encode())
        import app.services as services
        orig = services.processing_status
        services.processing_status = lambda case: {"ready": False, "pending": ["x"]}
        try:
            assert learning.process(s, rec) is False and rec.status == "pending"
        finally:
            services.processing_status = orig
        s.commit()
        assert learning.process_pending(s) >= 1
        assert s.get(LearningRecord, rec.id).status == "done"
