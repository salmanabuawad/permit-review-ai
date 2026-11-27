"""Normalised findings: difference, evidence category, V11 status and accuracy gates from what a run stores."""
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import finding_schema as FS
from app.db import SessionLocal
from app.main import app
from app.models import CheckRun
from app.seed import seed

APPROVED = {"review_state": "PROFESSIONALLY_APPROVED", "check": {"kind": "compare", "operand": "measure.height_m"}}


def F(**kw):
    base = dict(id=1, rule_id="R", rule_version="1", title_he="t", explanation_he="e", severity="high", status="FAIL",
                measured_value=9.6, measured_uncertainty=0.05, threshold=9.0, operator="<=", units="מ׳", confidence=1.0,
                citations=[{"source_id": "S"}], evidence=[{"type": "measurement", "method": "polygon", "source_entities": ["h1"]}],
                overlay_wkt="POINT(0 0)", flags=[], fix_hint_he="להנמיך", reviewer_decision=None)
    base.update(kw)
    return NS(**base)


def test_confirmed_violation_needs_every_mandatory_gate():
    r = FS.normalise(F(), APPROVED)
    assert r["check_status"] == "CONFIRMED_VIOLATION" and r["difference"] == 0.6 and r["external_eligible"]
    assert r["evidence_category"] == "GEOMETRIC_MEASUREMENT" and r["method"] == "polygon"
    assert r["gates"]["exceptions_considered"] == "NOT_EVALUATED"          # not modelled: never reported as passed
    assert FS.normalise(F(flags=["WITHIN_UNCERTAINTY_BAND"]), APPROVED)["check_status"] == "UNRESOLVED"
    assert FS.normalise(F(), {**APPROVED, "review_state": "SOURCE_VERIFIED"})["check_status"] == "UNRESOLVED"
    assert FS.normalise(F(), APPROVED, latest=False)["external_eligible"] is False


def test_other_statuses_and_categories():
    declared = {**APPROVED, "check": {"kind": "compare", "operand": "declared.floors"}}
    r = FS.normalise(F(evidence=[], measured_value=3, threshold=2), declared)
    assert r["evidence_category"] == "DECLARED_VALUE"
    assert FS.normalise(F(status="FAIL"), {"check": {"kind": "consistency"}})["check_status"] == "DECLARATION_MISMATCH"
    assert FS.normalise(F(status="FAIL"), {"check": {"kind": "doc_required"}})["check_status"] == "DOCUMENT_INCONSISTENCY"
    assert FS.normalise(F(status="UNCERTAIN"), {"check": {"kind": "qualitative"}})["check_status"] == "DISCRETIONARY_REVIEW_REQUIRED"
    assert FS.normalise(F(status="NA"), APPROVED)["check_status"] == "NOT_APPLICABLE"
    cov = FS.coverage([FS.normalise(F(), APPROVED), FS.normalise(F(status="NA"), APPROVED)])
    assert cov["applicable"] == 1 and cov["independent_measurement"] == {"numeric_checks": 1, "measured": 1}


def test_endpoint_on_a_real_run():
    seed(reset=True, samples=True)
    c = TestClient(app)
    with SessionLocal() as s:
        run = s.scalars(select(CheckRun)).first()
        if run is None:
            import pytest
            pytest.skip("seed has no runs")
        rid = run.id
    r = c.get(f"/api/runs/{rid}/findings/normalised", headers={"X-User": "u-reviewer"})
    assert r.status_code == 200 and r.json()["coverage"]["checks"] == len(r.json()["findings"])
    assert c.get(f"/api/runs/{rid}/findings/normalised", headers={"X-User": "u-bb-admin"}).status_code in (403, 404)
