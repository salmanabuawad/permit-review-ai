"""Rules screen: create / update / delete / restore rules, layered over the YAML catalogue."""
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent
from app.rules.engine import bump_version, validate_rule
from app.seed import seed

H = lambda u: {"X-User": u}  # noqa: E731
NEW = {"id": "BB-TEST-MAX-AREA", "title_he": "שטח תוספת מרבי לבדיקה", "legal_level": "MUNICIPAL_POLICY",
       "report": "rights", "severity": "medium", "review_state": "SOURCE_LOCATED",
       "permit_types": ["addition_extension"],
       "check": {"kind": "compare", "operand": "measure.proposed_addition_area_m2", "operator": "<=",
                 "threshold": 40.0, "units": "מ\"ר"},
       "sources": [{"source_id": "BB-POL-2026-01-13", "section": "סעיף 9", "page": 4}]}


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def rules(client, **kw):
    return {r["id"]: r for r in client.get("/api/rules", headers=H("u-engineer"), params=kw).json()}


def test_validation_catches_broken_rules():
    assert validate_rule(NEW) == []
    assert any("מזהה" in e for e in validate_rule({**NEW, "id": "bad id"}))
    assert any("אופרטור" in e for e in validate_rule({**NEW, "check": {**NEW["check"], "operator": "=>"}}))
    assert any("operand" in e for e in validate_rule({**NEW, "check": {"kind": "compare", "operator": "<="}}))
    assert any("אישור מקצועי" in e for e in validate_rule({**NEW, "review_state": "PROFESSIONALLY_APPROVED"}))
    assert any("YYYY" in e for e in validate_rule({**NEW, "valid_from": "13/1/2026"}))
    assert bump_version("0.1") == "0.2" and bump_version("1.9") == "1.10" and bump_version("3") == "3.1"


def test_only_rule_editors_can_change_rules(client):
    assert client.post("/api/rules", headers=H("u-reviewer"), json={"rule": NEW, "note": "בדיקה"}).status_code == 403
    assert client.get("/api/rules/meta", headers=H("u-reviewer")).json()["can_edit"] is False
    assert client.get("/api/rules/meta", headers=H("u-engineer")).json()["can_edit"] is True


def test_create_update_delete_restore_custom_rule(client):
    assert client.post("/api/rules", headers=H("u-engineer"), json={"rule": NEW, "note": ""}).status_code == 422
    r = client.post("/api/rules", headers=H("u-engineer"), json={"rule": NEW, "note": "כלל חדש לבדיקה"})
    assert r.status_code == 200 and r.json()["version"] == "0.1"
    assert client.post("/api/rules", headers=H("u-engineer"), json={"rule": NEW, "note": "שוב"}).status_code == 409
    got = rules(client)["BB-TEST-MAX-AREA"]
    assert got["origin"] == "custom" and got["check"]["threshold"] == 40.0

    upd = {**got, "check": {**got["check"], "threshold": 35.0}}
    r = client.put("/api/rules/BB-TEST-MAX-AREA", headers=H("u-engineer"), json={"rule": upd, "note": "תיקון סף"})
    assert r.status_code == 200 and r.json()["version"] == "0.2"
    assert rules(client)["BB-TEST-MAX-AREA"]["check"]["threshold"] == 35.0
    assert client.put("/api/rules/BB-TEST-MAX-AREA", headers=H("u-engineer"),
                      json={"rule": upd, "note": "ללא שינוי"}).status_code == 422

    assert client.delete("/api/rules/BB-TEST-MAX-AREA", headers=H("u-engineer"), params={"note": "בוטל"}).status_code == 200
    assert "BB-TEST-MAX-AREA" not in rules(client)
    assert rules(client, include_deleted=True)["BB-TEST-MAX-AREA"]["deleted"] is True
    r = client.post("/api/rules/BB-TEST-MAX-AREA/restore", headers=H("u-engineer"), json={"rule": {}, "note": "הוחזר"})
    assert r.status_code == 200 and rules(client)["BB-TEST-MAX-AREA"]["version"] == "0.3"
    with SessionLocal() as s:
        actions = [a for (a,) in s.query(AuditEvent.action).filter(AuditEvent.entity_id == "BB-TEST-MAX-AREA")]
    assert actions == ["rule.create", "rule.update", "rule.delete", "rule.undelete"]


def test_editing_a_catalogue_rule_needs_a_new_approval(client):
    rid = "BB-POL26-RR-SETBACK"
    assert client.post(f"/api/rules/{rid}/approval", headers=H("u-engineer"),
                       json={"note": "נבדק מול המדיניות עמ׳ 3"}).status_code == 200
    r0 = rules(client)[rid]
    assert r0["review_state"] == "PROFESSIONALLY_APPROVED" and r0["origin"] == "file"
    edited = {**r0, "fix_hint_he": "להרחיק את חדר הגג 2.5 מ׳ לפחות משפת הגג."}
    r = client.put(f"/api/rules/{rid}", headers=H("u-engineer"), json={"rule": edited, "note": "ניסוח"})
    assert r.status_code == 200 and r.json()["version"] == "0.2"
    r1 = rules(client)[rid]
    assert r1["origin"] == "edited" and r1["file_version"] == "0.1"
    assert r1["review_state"] == "SOURCE_VERIFIED"          # the approval was for 0.1, not the edited 0.2
    assert client.post(f"/api/rules/{rid}/restore", headers=H("u-engineer"),
                       json={"rule": {}, "note": "חזרה לנוסח הקטלוג"}).status_code == 200
    r2 = rules(client)[rid]
    assert r2["origin"] == "file" and r2["version"] == "0.1" and r2["review_state"] == "PROFESSIONALLY_APPROVED"


def test_deleted_rule_is_not_checked(client):
    case = next(c for c in client.get("/api/cases", headers=H("u-reviewer")).json() if c["case_number"] == "DEMO-0001")
    assert client.delete("/api/rules/DEMO-ADDITION-MAX-AREA", headers=H("u-engineer"),
                         params={"note": "בדיקת מחיקה"}).status_code == 200
    run = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rep = client.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=H("u-reviewer")).json()
    assert "DEMO-ADDITION-MAX-AREA" not in {f["rule_id"] for f in rep["findings"]}
    assert client.post("/api/rules/DEMO-ADDITION-MAX-AREA/restore", headers=H("u-engineer"),
                       json={"rule": {}, "note": "שחזור"}).status_code == 200
    run = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rep = client.get(f"/api/runs/{run['run_id']}/report/rights", headers=H("u-reviewer")).json()
    assert "DEMO-ADDITION-MAX-AREA" in {f["rule_id"] for f in rep["findings"]}
