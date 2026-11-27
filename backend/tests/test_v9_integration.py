"""V9 integration: required-check coverage, authenticated attestations (fake / stale), derivation cache with
invalidation, run metrics, and the API that exposes them."""
import pytest
from fastapi.testclient import TestClient

from app import attestation as A
from app import coverage as C
from app import derivation_cache as DC
from app import services as S
from app.db import SessionLocal
from app.main import app
from app.models import CheckRun, DerivationCache, ReviewAttestation
from app.seed import seed

from .conftest import FIX


class R:
    def __init__(self, rule_id, status, *flags, evidence=None):
        self.rule_id, self.flags, self.evidence = rule_id, [f"STATUS_{status}", *flags], evidence or []


INV = {"version": 1, "families": {
    "areas": {"label_he": "שטחים", "checks": [
        {"id": "diagrams", "rules": ["HA-AREA-DIAGRAMS"], "independent": True},
        {"id": "plans", "rules": ["HA-AREA-FLOORPLANS"], "independent": True}]},
    "spatial": {"label_he": "בינוי", "checks": [{"id": "building_lines", "rules": ["*-BUILDING-LINE*"]}]}}}


# ------------------------------------------------------------------ coverage

def test_blank_check_list_is_never_compliance():
    cov = C.family_coverage([], INV)
    assert not cov["full_compliance_possible"]
    assert cov["families"]["areas"]["state"] == "NONE"
    assert set(cov["open"]) == {"areas.diagrams", "areas.plans", "spatial.building_lines"}
    assert S.final_decision([], {}, cov)[0] == "INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION"
    # an empty inventory is not a licence either
    assert not C.family_coverage([R("X", "PASS")], {"families": {}})["full_compliance_possible"]


def test_missing_implementation_is_reported():
    res = [R("HA-AREA-DIAGRAMS", "PASS", "RESOLVED_FROM_DOCUMENTS"), R("HA-AREA-FLOORPLANS", "PASS", "RESOLVED_FROM_DOCUMENTS")]
    cov = C.family_coverage(res, INV)
    assert cov["families"]["areas"]["state"] == "COMPLETE"
    assert cov["families"]["spatial"]["checks"][0]["state"] == "NOT_IMPLEMENTED"     # no building-line rule here
    assert not cov["full_compliance_possible"]


def test_declared_value_pass_does_not_satisfy_an_independent_check():
    cov = C.family_coverage([R("HA-AREA-DIAGRAMS", "PASS"), R("HA-AREA-FLOORPLANS", "PASS"),
                             R("DEMO-BUILDING-LINE", "PASS")], INV)
    assert cov["families"]["areas"]["state"] == "NONE"
    m = R("HA-AREA-DIAGRAMS", "PASS", evidence=[{"type": "measurement"}])
    cov = C.family_coverage([m, R("HA-AREA-FLOORPLANS", "UNRESOLVED"), R("DEMO-BUILDING-LINE", "PASS")], INV)
    assert cov["families"]["areas"]["state"] == "PARTIAL"


def test_full_inventory_allows_no_defects_and_future_stage_is_not_open():
    res = [R("HA-AREA-DIAGRAMS", "PASS", "MEASURED"), R("HA-AREA-FLOORPLANS", "FUTURE_STAGE"),
           R("DEMO-BUILDING-LINE", "PASS")]
    cov = C.family_coverage(res, INV)
    assert cov["full_compliance_possible"] and cov["families"]["areas"]["checks"][1]["state"] == "FUTURE_STAGE"


def test_repository_inventory_loads_and_names_every_family():
    inv = C.load_inventory()
    assert {"documents", "land", "areas", "rights", "route", "spatial", "infrastructure_environment"} <= set(inv["families"])
    assert "הדוח" in C.disclaimer_he(C.family_coverage([], inv))


# ------------------------------------------------------------------ API: run, attest, audit, metrics

@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def H(u):
    return {"X-User": u}


def _case_with_run(client, number):
    cid = client.post("/api/cases", headers=H("u-secretary"), json={
        "case_number": number, "title": "V9", "permit_type": "addition_extension",
        "applicable_plans": ["DEMO/1"], "zone": "residential_B"}).json()["id"]
    client.post(f"/api/cases/{cid}/files", headers=H("u-secretary"),
                files={"file": ("survey_map.pdf", (FIX / "survey_map.pdf").read_bytes())}, data={"doc_type": "survey_map"})
    return cid, client.post(f"/api/cases/{cid}/run", headers=H("u-reviewer")).json()["run_id"]


def test_attestation_valid_then_stale_on_new_run(client):
    cid, run1 = _case_with_run(client, "V9-ATT-1")
    r = client.post(f"/api/runs/{run1}/attestations", headers=H("u-reviewer"), json={"decision": "REVIEWED"})
    assert r.status_code == 200 and r.json()["state"] == "VALID"
    assert "signature" not in r.json()                                         # never exposed to clients
    run2 = client.post(f"/api/cases/{cid}/run", headers=H("u-reviewer")).json()["run_id"]
    states = client.get(f"/api/runs/{run1}/attestations", headers=H("u-reviewer")).json()
    assert [a["state"] for a in states] == ["STALE"]                           # stale revision
    late = client.post(f"/api/runs/{run1}/attestations", headers=H("u-reviewer"), json={"decision": "REVIEWED"})
    assert late.status_code == 409                                             # only the latest run can be attested
    assert client.post(f"/api/runs/{run2}/attestations", headers=H("u-planner"),
                       json={"decision": "REVIEWED"}).status_code == 403       # applicant side cannot attest


def test_forged_or_tampered_attestation_is_invalid_or_stale(client):
    cid, run = _case_with_run(client, "V9-ATT-2")
    aid = client.post(f"/api/runs/{run}/attestations", headers=H("u-reviewer"), json={"decision": "REVIEWED"}).json()["id"]
    with SessionLocal() as s:
        a = s.get(ReviewAttestation, aid)
        a.decision = "APPROVED_FOR_REPORT"                                     # someone edits the row
        s.commit()
        assert A.verify(s, a) == "INVALID"
        a.decision = "REVIEWED"
        s.add(ReviewAttestation(tenant_id=a.tenant_id, case_id=a.case_id, run_id=a.run_id, run_version=a.run_version,
                                user_id="u-engineer", role="city_engineer", decision="APPROVED_FOR_REPORT", note="",
                                digest=a.digest, signature="0" * 64))      # a fake row without the server key
        s.commit()
        assert A.verify(s, a) == "VALID"
        run_row = s.get(CheckRun, run)
        run_row.findings[0].status = "PASS" if run_row.findings[0].status != "PASS" else "FAIL"   # a finding changes
        s.commit()
        assert A.verify(s, a) == "STALE"
    states = [x["state"] for x in client.get(f"/api/runs/{run}/attestations", headers=H("u-reviewer")).json()]
    assert states == ["STALE", "INVALID"]


def test_coverage_audit_and_metrics_endpoints(client):
    _, run = _case_with_run(client, "V9-COV-1")
    cov = client.get(f"/api/runs/{run}/coverage", headers=H("u-reviewer")).json()
    assert cov["coverage"]["full_compliance_possible"] is False and cov["coverage"]["open"]
    assert cov["decision"] != "NO_DEFECTS_IDENTIFIED"
    assert client.get(f"/api/runs/{run}/audit", headers=H("u-planner")).status_code == 403   # audit.read only
    audit = client.get(f"/api/runs/{run}/audit", headers=H("u-manager")).json()
    assert len(audit["run"]["digest"]) == 64 and audit["findings"]
    m = client.get(f"/api/runs/{run}/metrics", headers=H("u-manager")).json()["metrics"]
    assert m["wall_ms"] >= 0 and "tokens_in" in m["llm"] and {"hits", "misses"} <= set(m["cache"])


def test_second_run_reuses_document_text(client):
    cid, run1 = _case_with_run(client, "V9-CACHE-1")
    run2 = client.post(f"/api/cases/{cid}/run", headers=H("u-reviewer")).json()["run_id"]
    m = client.get(f"/api/runs/{run2}/metrics", headers=H("u-manager")).json()["metrics"]
    assert m["cache"]["hits"] >= 1 and m["cache"]["misses"] == 0


# ------------------------------------------------------------------ cache

def test_cache_keys_and_invalidation():
    calls = []

    def comp():
        calls.append(1)
        return {"v": len(calls)}
    with SessionLocal() as s:
        sha, other = "a" * 64, "b" * 64
        out, hit = DC.get_or_compute(s, algorithm="t", version="1", sha256=sha, compute=comp)
        assert not hit and out == {"v": 1}
        assert DC.get_or_compute(s, algorithm="t", version="1", sha256=sha, compute=comp) == ({"v": 1}, True)
        assert not DC.get_or_compute(s, algorithm="t", version="2", sha256=sha, compute=comp)[1]   # new version
        case = dict(algorithm="rules", version="r1", sha256=other, scope="case", jurisdiction="hof-ashkelon",
                    revision="10000612352-1", depends_on=[sha])
        assert not DC.get_or_compute(s, compute=comp, **case)[1]
        assert DC.get_or_compute(s, compute=comp, **case)[1]
        assert not DC.get_or_compute(s, compute=comp, **{**case, "revision": "10000612352-2"})[1]  # new revision
        with pytest.raises(ValueError):
            DC.get_or_compute(s, algorithm="t", version="1", sha256=sha, compute=comp, jurisdiction="x")
        assert DC.invalidate(s, sha) == 4            # both versions of the file + both case results that used it
        assert not DC.get_or_compute(s, compute=comp, **case)[1]
        s.query(DerivationCache).delete()
        s.commit()
