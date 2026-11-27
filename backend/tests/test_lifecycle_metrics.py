"""Document life cycle (§12.3), dashboard process metrics (§8.1–8.2), new completeness checks
(§7.1.2) and PDF long-token wrapping."""
import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.knowledge import load_sources
from app.main import app
from app.metrics import stage_stats
from app.reports import _fonts, _split_long, _wrap_logical
from app.rules.engine import evaluate_rule
from app.seed import seed
from app.services import add_months

from .conftest import FIX
from .test_rules_engine import RULES, approved

H = lambda u: {"X-User": u}  # noqa: E731


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def new_case(client, number):
    r = client.post("/api/cases", headers=H("u-secretary"), json={
        "case_number": number, "title": "בדיקת מחזור חיים", "permit_type": "addition_extension",
        "applicable_plans": ["DEMO/1"], "zone": "residential_B"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def upload(client, cid, fname, doc_type):
    r = client.post(f"/api/cases/{cid}/files", headers=H("u-secretary"),
                    files={"file": (fname, (FIX / fname).read_bytes())}, data={"doc_type": doc_type})
    assert r.status_code == 200, r.text
    return next(f for f in r.json()["files"] if f["filename"] == fname)


def finding(client, cid, rule_id):
    run = client.post(f"/api/cases/{cid}/run", headers=H("u-reviewer")).json()
    rep = client.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=H("u-reviewer")).json()
    return next(f for f in rep["findings"] if f["rule_id"] == rule_id)


# ---------------------------------------------------------------- life cycle
def test_archive_excludes_file_from_checks_and_restore_brings_it_back(client):
    cid = new_case(client, "DEMO-LC1")
    f = upload(client, cid, "photos.pdf", "existing_building_photos")
    assert finding(client, cid, "BB-SG16-30.6-PHOTOS")["computed_result"] == "PASS"
    r = client.post(f"/api/files/{f['id']}/lifecycle", headers=H("u-secretary"), json={"state": "ARCHIVED", "note": "גרסה שגויה"})
    assert r.status_code == 200
    assert finding(client, cid, "BB-SG16-30.6-PHOTOS")["computed_result"] == "FAIL"
    client.post(f"/api/files/{f['id']}/lifecycle", headers=H("u-secretary"), json={"state": "ACTIVE", "note": "שוחזר"})
    assert finding(client, cid, "BB-SG16-30.6-PHOTOS")["computed_result"] == "PASS"


def test_controlled_delete(client):
    cid = new_case(client, "DEMO-LC2")
    f = upload(client, cid, "survey_map.pdf", "survey_map")
    with SessionLocal() as s:
        from app.models import CaseFile
        path = Path(s.get(CaseFile, f["id"]).storage_path)
    assert path.exists()
    body = {"state": "DELETED", "note": "הועלה בטעות"}
    assert client.post(f"/api/files/{f['id']}/lifecycle", headers=H("u-planner"), json=body).status_code == 403
    assert client.post(f"/api/files/{f['id']}/lifecycle", headers=H("u-manager"), json={**body, "note": ""}).status_code == 422
    assert client.post(f"/api/files/{f['id']}/lifecycle", headers=H("u-manager"), json=body).status_code == 200
    assert not path.exists()                                            # bytes purged
    assert client.get(f"/api/files/{f['id']}/download", headers=H("u-reviewer")).status_code == 410
    again = client.post(f"/api/cases/{cid}/files", headers=H("u-secretary"),
                        files={"file": ("x.pdf", (FIX / "survey_map.pdf").read_bytes())}, data={"doc_type": "survey_map"})
    assert again.status_code == 422 and "נמחק" in again.json()["detail"]
    assert client.post(f"/api/files/{f['id']}/lifecycle", headers=H("u-manager"),
                       json={"state": "ACTIVE", "note": "נסיון"}).status_code == 409   # deletion is final
    audit = client.get("/api/audit", headers=H("u-admin")).json()
    ev = next(e for e in audit["events"] if e["action"] == "file.deleted")
    assert ev["detail"]["sha256"] == f["sha256"] and audit["chain_ok"]


# ---------------------------------------------------------------- dashboard metrics
def test_stage_metrics_and_waiting_external(client):
    cid = new_case(client, "DEMO-ST1")
    upload(client, cid, "case2_extension_ok.dxf", "architectural_plan")
    client.post(f"/api/cases/{cid}/run", headers=H("u-reviewer"))
    assert client.post(f"/api/cases/{cid}/workflow", headers=H("u-reviewer"),
                       json={"status": "WAITING_EXTERNAL", "note": "מכון בקרה"}).status_code == 200
    d = client.get("/api/dashboard", headers=H("u-manager")).json()
    assert d["stages"]["waiting_external"] >= 1
    assert "INTAKE" in d["stages"]["avg_hours_by_stage"] and "IN_REVIEW" in d["stages"]["avg_hours_by_stage"]
    assert d["cost_per_month"] and "u-reviewer" in d["cost_per_user"]
    with SessionLocal() as s:
        later = stage_stats(s, "demo", now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10))
    assert any(x["case_number"] == "DEMO-ST1" and x["status"] == "WAITING_EXTERNAL" for x in later["stuck"])


# ---------------------------------------------------------------- §7.1.2 completeness
@pytest.mark.parametrize("start,months,expected", [
    (dt.date(2026, 5, 16), 6, dt.date(2026, 11, 16)),
    (dt.date(2026, 8, 31), 6, dt.date(2027, 2, 28)),
    (dt.date(2027, 8, 31), 6, dt.date(2028, 2, 29)),
])
def test_add_months_is_calendar_based(start, months, expected):
    assert add_months(start, months) == expected


def _survey_facts(survey_date, ref):
    from app.services import add_months as am
    sd, rd = dt.date.fromisoformat(survey_date), dt.date.fromisoformat(ref)
    return {"case": {"permit_type": "addition_extension", "stage": "permit_request", "reference_date": ref},
            "declared": {}, "docs": {"present": {"survey_map": True}},
            "facts_derived": {"survey_map_within_6_months": rd <= am(sd, 6)}}


@pytest.mark.parametrize("survey,ref,expected", [
    ("2026-05-16", "2026-11-16", "PASS"),   # exactly 6 months
    ("2026-05-15", "2026-11-16", "FAIL"),   # 6 months + 1 day
])
def test_survey_map_age_boundary(survey, ref, expected):
    assert evaluate_rule(approved("QA-SURVEY-MAP-AGE"), _survey_facts(survey, ref), load_sources(), False).status == expected


def test_survey_map_date_missing_is_uncertain():
    f = {"case": {"permit_type": "addition_extension", "stage": "permit_request", "reference_date": "2026-11-16"},
         "declared": {}, "docs": {"present": {"survey_map": True}}, "facts_derived": {}}
    r = evaluate_rule(approved("QA-SURVEY-MAP-AGE"), f, load_sources(), False)
    assert r.status == "UNCERTAIN" and "INCOMPLETE" in r.flags


@pytest.mark.parametrize("facts_extra,expected", [
    ({"cad": {"roles": ["SECTION"]}}, "PASS"),
    ({"docs": {"present": {"sections_elevations": True}}}, "PASS"),
    ({"cad": {"roles": ["ELEVATION"]}}, "FAIL"),
])
def test_sections_any_present(facts_extra, expected):
    f = {"case": {"permit_type": "addition_extension", "stage": "permit_request"}, "declared": {},
         "docs": {"present": {}}, "facts_derived": {}, **facts_extra}
    assert evaluate_rule(approved("QA-REQ-SECTIONS"), f, load_sources(), False).status == expected


def test_demo_cases_show_survey_and_sections(client):
    cases = {c["case_number"]: c for c in client.get("/api/cases", headers=H("u-reviewer")).json()}
    def get(num, rule):
        rep = client.get(f"/api/runs/{cases[num]['last_run']['id']}/report/reviewer", headers=H("u-reviewer")).json()
        return next(f for f in rep["findings"] if f["rule_id"] == rule)
    assert get("DEMO-0001", "QA-SURVEY-MAP-AGE")["computed_result"] == "FAIL"
    assert get("DEMO-0002", "QA-SURVEY-MAP-AGE")["computed_result"] == "PASS"
    assert get("DEMO-0002", "QA-REQ-SECTIONS")["computed_result"] == "PASS"
    assert get("DEMO-0001", "QA-REQ-SECTIONS")["computed_result"] == "FAIL"


# ---------------------------------------------------------------- PDF wrapping
def test_long_rule_ids_split_to_fit():
    _fonts()
    from reportlab.pdfbase.pdfmetrics import stringWidth
    pieces = _split_long("DEMO-ADDITION-MAX-AREA", "He", 7.5, 40)
    assert "".join(pieces) == "DEMO-ADDITION-MAX-AREA" and len(pieces) > 1
    assert all(stringWidth(p, "He", 7.5) <= 40 for p in pieces)
    assert pieces[0].endswith("-")                                   # broken at a hyphen, not mid-word
    lines = _wrap_logical("כלל DEMO-ADDITION-MAX-AREA v1.0", "He", 7.5, 40)
    assert all(stringWidth(l, "He", 7.5) <= 40 for l in lines)
