"""Integration tests through the HTTP API (seeded demo tenant)."""
import time

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent
from app.seed import seed

from .conftest import FIX


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def H(user):
    return {"X-User": user}


def demo_case(client, number):
    return next(c for c in client.get("/api/cases", headers=H("u-reviewer")).json() if c["case_number"] == number)


def test_health(client):
    r = client.get("/api/health").json()
    assert r["ok"] and r["integrations_enabled"] is False


def test_integrations_all_planned_and_disconnected(client):
    for i in client.get("/api/integrations").json():
        assert i["status"] == "PLANNED" and i["enabled"] is False and i["connected"] is False


def test_tenant_isolation(client):
    case = demo_case(client, "DEMO-0001")
    assert client.get(f"/api/cases/{case['id']}", headers=H("u-bb-admin")).status_code == 404
    assert client.get("/api/cases", headers=H("u-bb-admin")).json() == []


def test_rbac(client):
    case = demo_case(client, "DEMO-0001")
    assert client.post(f"/api/cases/{case['id']}/run", headers=H("u-planner")).status_code == 403
    assert client.get("/api/audit", headers=H("u-planner")).status_code == 403


def test_full_flow_upload_run_report_pdf(client):
    r = client.post("/api/cases", headers=H("u-secretary"), json={
        "case_number": "DEMO-T1", "title": "בדיקת אינטגרציה", "permit_type": "addition_extension",
        "applicable_plans": ["DEMO/1"], "zone": "residential_B"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    for fname, dt_ in (("case1_extension_exceeds.dxf", "architectural_plan"), ("case1_area_table.xlsx", "area_table"),
                       ("survey_map.pdf", "survey_map")):
        up = client.post(f"/api/cases/{cid}/files", headers=H("u-secretary"),
                         files={"file": (fname, (FIX / fname).read_bytes())}, data={"doc_type": dt_})
        assert up.status_code == 200, up.text
    dup = client.post(f"/api/cases/{cid}/files", headers=H("u-secretary"),
                      files={"file": ("again.pdf", (FIX / "survey_map.pdf").read_bytes())}, data={"doc_type": "survey_map"})
    assert dup.status_code == 422 and "זהה" in dup.json()["detail"]
    t0 = time.perf_counter()
    run = client.post(f"/api/cases/{cid}/run", headers=H("u-reviewer")).json()
    assert time.perf_counter() - t0 < 10, "KPI: regular action ≤ 10 s"
    rep = client.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=H("u-reviewer")).json()
    by_rule = {f["rule_id"]: f for f in rep["findings"]}
    assert by_rule["DEMO-BUILDING-LINE"]["status"] == "FAIL"
    assert by_rule["DEMO-BUILDING-LINE"]["overlay_wkt"].startswith("POLYGON")
    assert by_rule["QA-AREA-CAD-VS-TABLE"]["status"] == "FAIL"
    assert by_rule["QA-REQ-APPLICATION-FORM"]["computed_result"] == "FAIL"
    assert by_rule["QA-REQ-APPLICATION-FORM"]["status"] == "UNCERTAIN"       # rule not yet approved
    assert all(f["citations"] for f in rep["findings"])
    pdf = client.get(f"/api/runs/{run['run_id']}/defects.pdf", headers=H("u-reviewer"))
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    geo = client.get(f"/api/cases/{cid}/geometry", headers=H("u-reviewer")).json()
    assert len(geo["features"]) >= 5 and geo["units"] == "m"


def test_rule_approval_makes_rule_binding(client):
    case = demo_case(client, "DEMO-0003")
    run = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rep = client.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=H("u-reviewer")).json()
    f = next(x for x in rep["findings"] if x["rule_id"] == "BB-POL26-RR-SETBACK")
    assert (f["computed_result"], f["status"]) == ("FAIL", "UNCERTAIN")
    assert client.post("/api/rules/BB-POL26-RR-SETBACK/approval", headers=H("u-planner"),
                       json={"note": "x" * 10}).status_code == 403
    assert client.post("/api/rules/BB-B105-MAX-HEIGHT/approval", headers=H("u-engineer"),
                       json={"note": "אישור ללא מקור"}).status_code == 409
    ok = client.post("/api/rules/BB-POL26-RR-SETBACK/approval", headers=H("u-engineer"),
                     json={"note": "נבדק מול מסמך המדיניות עמ׳ 3 סעיף 4ג׳"})
    assert ok.status_code == 200
    run2 = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rep2 = client.get(f"/api/runs/{run2['run_id']}/report/reviewer", headers=H("u-reviewer")).json()
    f2 = next(x for x in rep2["findings"] if x["rule_id"] == "BB-POL26-RR-SETBACK")
    assert f2["status"] == "FAIL" and run2["version"] == run["version"] + 1


def test_decisions_lock_and_audit_chain(client):
    case = demo_case(client, "DEMO-0002")
    run = client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).json()
    rep = client.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=H("u-reviewer")).json()
    assert client.post(f"/api/cases/{case['id']}/workflow", headers=H("u-reviewer"),
                       json={"status": "LOCK"}).status_code == 409          # undecided findings
    pending = [f for f in rep["findings"] if f["status"] in ("FAIL", "UNCERTAIN")]
    bad = client.post(f"/api/findings/{pending[0]['id']}/decision", headers=H("u-reviewer"),
                      json={"decision": "OVERRIDDEN", "note": ""})
    assert bad.status_code == 422
    for f in pending:
        assert client.post(f"/api/findings/{f['id']}/decision", headers=H("u-reviewer"),
                           json={"decision": "CONFIRMED", "note": "נבדק"}).status_code == 200
    assert client.post(f"/api/cases/{case['id']}/workflow", headers=H("u-reviewer"),
                       json={"status": "LOCK"}).status_code == 200
    assert client.post(f"/api/cases/{case['id']}/run", headers=H("u-reviewer")).status_code == 409
    audit = client.get("/api/audit", headers=H("u-admin")).json()
    assert audit["chain_ok"] is True
    # tamper with one event -> chain must break
    with SessionLocal() as s:
        ev = s.query(AuditEvent).filter_by(tenant_id="demo").order_by(AuditEvent.id).first()
        ev.detail = {**ev.detail, "tampered": True}
        s.commit()
    assert client.get("/api/audit", headers=H("u-admin")).json()["chain_ok"] is False


def test_ai_policy_local_cannot_include_cloud(client):
    r = client.put("/api/ai/policy", headers=H("u-admin"), json={
        "task": "Classification", "data_class": "CASE_DOCUMENT", "mode": "LOCAL",
        "providers": ["cloud_llm_il", "local_keyword"]})
    assert r.status_code == 422
    assert client.put("/api/ai/policy", headers=H("u-reviewer"), json={
        "task": "Classification", "data_class": "CASE_DOCUMENT", "mode": "LOCAL",
        "providers": ["local_keyword"]}).status_code == 403


def test_kb_search_returns_citations(client):
    r = client.get("/api/kb/search", params={"q": "נסיגה חדר גג"}, headers=H("u-reviewer")).json()
    assert r["hits"] and r["hits"][0]["source_id"] == "BB-POL-2026-01-13" and r["hits"][0]["page"] == 3


def test_dashboard(client):
    d = client.get("/api/dashboard", headers=H("u-manager")).json()
    assert d["cases_by_status"] and d["ai_usage"]
    assert d["run_duration_ms"]["max"] < 60_000, "KPI: report ≤ 60 s"
