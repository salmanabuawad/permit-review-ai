"""Rules API (create / replace / patch / delete over HTTP, JSON or YAML) and bulk recheck."""
import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed

ENG = {"X-User": "u-engineer"}          # city engineer: rule.manage + rule.approve
REV = {"X-User": "u-reviewer"}          # reviewer: read only for rules

RULE = {
    "id": "BB-TEST-PERGOLA-BEAM",
    "title_he": "רוחב קורת פרגולה ≤ 20 ס״מ",
    "legal_level": "SPATIAL_GUIDELINES",
    "report": "reviewer",
    "severity": "medium",
    "review_state": "SOURCE_VERIFIED",
    "permit_types": ["addition_balcony"],
    "stages": ["plan_review"],
    "check": {"kind": "compare", "operand": "declared.pergola_beam_width_cm", "operator": "<=", "threshold": 20,
              "units": "ס\"מ"},
    "sources": [{"source_id": "BB-SG-2016", "section": "32.3", "page": 16,
                 "quote_he": "רוחב כל קורה בפרגולה לא יעלה על 20 ס\"מ"}],
}


@pytest.fixture(scope="module")
def c():
    seed(reset=True, samples=False)                 # Bnei Brak tenant, no cases
    with TestClient(app) as client:
        yield client


def ids(c, h=ENG):
    return {r["id"]: r for r in c.get("/api/rules", headers=h).json()}


def test_permissions(c):
    assert c.post("/api/rules", json=RULE, headers=REV).status_code == 403
    assert c.delete("/api/rules/BB-TEST-PERGOLA-BEAM", headers={"X-User": "u-planner"}).status_code == 403


def test_create_then_read_json_and_yaml(c):
    r = c.post("/api/rules", json=RULE, headers=ENG, params={"note": "from guidelines 32.3"})
    assert r.status_code == 201, r.text
    assert r.json() == {"id": RULE["id"], "version": "1"}
    assert ids(c)[RULE["id"]]["managed"]["origin"] == "api"
    one = c.get(f"/api/rules/{RULE['id']}", headers=REV).json()
    assert one["check"]["threshold"] == 20 and one["version"] == "1"
    y = c.get(f"/api/rules/{RULE['id']}", params={"format": "yaml"}, headers=REV)
    assert y.headers["content-type"].startswith("application/yaml") and yaml.safe_load(y.text)["id"] == RULE["id"]
    assert c.post("/api/rules", json=RULE, headers=ENG).status_code == 409          # duplicate id


def test_validation_errors_are_specific(c):
    bad = {**RULE, "id": "BB-TEST-BAD", "legal_level": "NOPE", "check": {"kind": "compare", "operand": "x"},
           "sources": [{"source_id": "NOT-REGISTERED"}]}
    r = c.post("/api/rules", json=bad, headers=ENG)
    assert r.status_code == 422
    text = " ".join(r.json()["detail"]["errors"])
    assert "legal_level" in text and "operator" in text and "NOT-REGISTERED" in text
    assert c.post("/api/rules", json={**RULE, "id": "BB-TEST-PT", "permit_types": ["spaceship"]},
                  headers=ENG).status_code == 422
    assert c.post("/api/rules", content=b"not: [valid", headers={**ENG, "Content-Type": "application/yaml"}).status_code == 422


def test_api_cannot_self_approve(c):
    r = c.post("/api/rules", json={**RULE, "id": "BB-TEST-SELF-APPROVED", "review_state": "PROFESSIONALLY_APPROVED"},
               headers=ENG)
    assert r.status_code == 422 and "approval" in r.text
    assert c.post("/api/rules", json={**RULE, "id": "BB-TEST-DEMO", "review_state": "DEMO_FIXTURE"},
                  headers=ENG).status_code == 422                                  # not in a real tenant


def test_patch_bumps_version_and_drops_old_approval(c):
    rid = RULE["id"]
    a = c.post(f"/api/rules/{rid}/approval", json={"note": "checked against guidelines p.16"}, headers=ENG)
    assert a.status_code == 200, a.text
    assert ids(c)[rid]["review_state"] == "PROFESSIONALLY_APPROVED"
    got = c.get(f"/api/rules/{rid}", headers=ENG).json()
    assert got["review_state"] == "SOURCE_VERIFIED" and got["approval"]["state"] == "PROFESSIONALLY_APPROVED"
    r = c.patch(f"/api/rules/{rid}", json={"check": {**RULE["check"], "threshold": 25}}, headers=ENG)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "2" and r.json()["previous_version"] == "1"
    now = ids(c)[rid]
    assert now["check"]["threshold"] == 25 and now["review_state"] == "SOURCE_VERIFIED"   # approval was for v1


def test_put_round_trip_from_get_yaml(c):
    rid = RULE["id"]
    body = yaml.safe_load(c.get(f"/api/rules/{rid}", params={"format": "yaml"}, headers=ENG).text)
    body["title_he"] = "רוחב קורת פרגולה — עד 25 ס״מ"
    r = c.put(f"/api/rules/{rid}", content=yaml.safe_dump(body, allow_unicode=True).encode(),
              headers={**ENG, "Content-Type": "application/yaml"})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "3" and ids(c)[rid]["title_he"].endswith("25 ס״מ")
    assert c.put(f"/api/rules/{rid}", json={**RULE, "id": "OTHER-ID"}, headers=ENG).status_code == 422


def test_override_and_delete_a_file_rule(c):
    file_rule = next(r for r in ids(c).values() if "managed" not in r and r["review_state"] != "PROFESSIONALLY_APPROVED")
    rid = file_rule["id"]
    r = c.patch(f"/api/rules/{rid}", json={"severity": "low"}, headers=ENG)
    assert r.status_code == 200, r.text
    assert ids(c)[rid]["managed"]["origin"] == "api_override" and ids(c)[rid]["severity"] == "low"
    d = c.delete(f"/api/rules/{rid}", params={"note": "superseded"}, headers=ENG)
    assert d.status_code == 200 and d.json()["deleted"]
    assert rid not in ids(c)
    assert c.get(f"/api/rules/{rid}", headers=ENG).status_code == 404
    assert c.delete(f"/api/rules/{rid}", headers=ENG).status_code == 404
    hist = c.get(f"/api/rules/{rid}/history", headers=ENG).json()
    assert [h["action"] for h in hist] == ["update", "delete"] and hist[1]["note"] == "superseded"
    restored = c.post("/api/rules", json={k: v for k, v in hist[0]["body"].items() if k != "version"}, headers=ENG)
    assert restored.status_code == 201 and rid in ids(c)


def test_bulk_create_from_yaml_file_is_all_or_nothing(c):
    good = {**RULE, "id": "BB-TEST-BULK-1"}
    bad = {**RULE, "id": "BB-TEST-BULK-2", "report": "nonsense"}
    doc = yaml.safe_dump({"rules": [good, bad]}, allow_unicode=True).encode()
    r = c.post("/api/rules", content=doc, headers={**ENG, "Content-Type": "application/yaml"})
    assert r.status_code == 422 and "rules[1]" in r.text
    assert "BB-TEST-BULK-1" not in ids(c)
    doc = yaml.safe_dump({"rules": [good, {**bad, "report": "rights"}]}, allow_unicode=True).encode()
    r = c.post("/api/rules", content=doc, headers={**ENG, "Content-Type": "application/yaml"})
    assert r.status_code == 201 and len(r.json()["created"]) == 2


def test_export_and_tenant_isolation(c):
    y = yaml.safe_load(c.get("/api/rules/export", headers=REV).text)
    assert y["jurisdiction"] == "bnei-brak" and any(r["id"] == RULE["id"] for r in y["rules"])
    seed(reset=True)                                  # demo tenant users; bnei-brak rules API data is wiped too
    assert c.get(f"/api/rules/{RULE['id']}", headers={"X-User": "u-reviewer"}).status_code == 404


def test_managed_rule_is_used_by_checks():
    seed(reset=True)                                  # demo tenant with sample cases
    with TestClient(app) as c:
        R = {"X-User": "u-reviewer"}
        case = c.get("/api/cases", headers=R).json()[0]
        rule = {**RULE, "id": "BB-TEST-USED", "permit_types": [], "stages": [], "applicability": None}
        assert c.post("/api/rules", json=rule, headers=ENG).status_code == 201
        run = c.post(f"/api/cases/{case['id']}/run", headers=R).json()
        rep = c.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=R).json()
        assert any(f["rule_id"] == "BB-TEST-USED" for f in rep["findings"])
        assert c.delete("/api/rules/BB-TEST-USED", headers=ENG).status_code == 200
        run2 = c.post(f"/api/cases/{case['id']}/run", headers=R).json()
        rep2 = c.get(f"/api/runs/{run2['run_id']}/report/reviewer", headers=R).json()
        assert not any(f["rule_id"] == "BB-TEST-USED" for f in rep2["findings"])


# ------------------------------------------------------------------ bulk recheck

def test_bulk_recheck_selected_and_all():
    seed(reset=True)
    with TestClient(app) as c:
        R = {"X-User": "u-reviewer"}
        cases = c.get("/api/cases", headers=R).json()
        assert c.post("/api/cases/recheck", json={"case_ids": None}, headers={"X-User": "u-planner"}).status_code == 403
        assert c.post("/api/cases/recheck", json={"case_ids": []}, headers=R).status_code == 422
        one = c.post("/api/cases/recheck", json={"case_ids": [cases[0]["id"]]}, headers=R).json()
        assert one["requested"] == 1 and len(one["done"]) + len(one["skipped"]) == 1
        before = {x["id"]: (x["last_run"] or {}).get("version", 0) for x in cases}
        allr = c.post("/api/cases/recheck", json={"case_ids": None}, headers=R).json()
        assert allr["requested"] == len(cases) and not allr["failed"]
        after = {x["id"]: (x["last_run"] or {}).get("version", 0) for x in c.get("/api/cases", headers=R).json()}
        for d in allr["done"]:
            assert after[d["case_id"]] > before[d["case_id"]]
        assert all(s["reason"] for s in allr["skipped"])
        assert c.post("/api/cases/recheck", json={"case_ids": ["not-a-case"]}, headers=R).json()["requested"] == 0
