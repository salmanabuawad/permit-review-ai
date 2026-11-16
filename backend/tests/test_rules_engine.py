"""Rule-engine unit, boundary, applicability and false-positive tests."""
import copy

import pytest

from app.config import settings
from app.knowledge import load_sources
from app.rules.engine import Rule, compare, evaluate, evaluate_rule, load_rules

RULES = {r.id: r for r in load_rules([settings.knowledge_dir / "rules" / f
                                      for f in ("bnei_brak.yaml", "internal_qa.yaml", "demo.yaml")])}
SRC = load_sources()


def roof_facts(setback=2.5, unc=0.0, track="policy_2026_roof_rights", stage="plan_review", **declared):
    return {
        "case": {"permit_type": "roof_room_addition", "track": track, "stage": stage, "zone": "residential_B",
                 "applicable_plans": ["DEMO/1"], "reference_date": "2026-03-01", "building_existing": True},
        "declared": declared, "docs": {"present": {}}, "facts_derived": {},
        "measure": {"roof_room_front_setback_m": {"key": "roof_room_front_setback_m", "value": setback,
                                                  "uncertainty": unc, "units": "m", "method": "test"}},
    }


def approved(rule_id):
    r = Rule(copy.deepcopy(RULES[rule_id].raw))
    r.raw["review_state"] = "PROFESSIONALLY_APPROVED"
    return r


# ---------------------------------------------------------------- boundary tests (policy 13.1.2026 §4ג)
@pytest.mark.parametrize("value,expected", [(2.49, "FAIL"), (2.50, "PASS"), (3.00, "PASS"),
                                            (2.4999999, "PASS"),   # numeric noise below EPS
                                            (2.4989, "FAIL")])
def test_roof_setback_boundaries_when_approved(value, expected):
    res = evaluate_rule(approved("BB-POL26-RR-SETBACK"), roof_facts(value), SRC, False)
    assert res.status == expected, res.explanation_he
    assert res.threshold == 2.5 and res.operator == ">="


def test_unapproved_rule_never_auto_fails():
    res = evaluate_rule(RULES["BB-POL26-RR-SETBACK"], roof_facts(2.49), SRC, False)
    assert res.computed_result == "FAIL"
    assert res.status == "UNCERTAIN"
    assert "RULE_NOT_APPROVED" in res.flags


def test_roof_policy_not_applied_to_regular_permit():
    """2.5 m must NOT become a general roof limit."""
    res = evaluate_rule(approved("BB-POL26-RR-SETBACK"), roof_facts(1.0, track="regular_permit"), SRC, False)
    assert res.status == "NA"


def test_roof_policy_not_applied_at_permit_stage():
    res = evaluate_rule(approved("BB-POL26-RR-SETBACK"), roof_facts(1.0, stage="permit_request"), SRC, False)
    assert res.status == "NA"


def test_roof_policy_not_applied_to_balcony():
    f = roof_facts(1.0)
    f["case"]["permit_type"] = "addition_balcony"
    assert evaluate_rule(approved("BB-POL26-RR-SETBACK"), f, SRC, False).status == "NA"


def test_rule_not_in_force_before_valid_from():
    f = roof_facts(1.0)
    f["case"]["reference_date"] = "2025-12-31"
    assert evaluate_rule(approved("BB-POL26-RR-SETBACK"), f, SRC, False).status == "NA"


def test_uncertainty_band_gives_uncertain():
    res = evaluate_rule(approved("BB-POL26-RR-SETBACK"), roof_facts(2.52, unc=0.05), SRC, False)
    assert res.status == "UNCERTAIN" and "WITHIN_UNCERTAINTY_BAND" in res.flags
    assert evaluate_rule(approved("BB-POL26-RR-SETBACK"), roof_facts(2.60, unc=0.05), SRC, False).status == "PASS"
    assert evaluate_rule(approved("BB-POL26-RR-SETBACK"), roof_facts(2.40, unc=0.05), SRC, False).status == "FAIL"


def test_missing_measurement_is_incomplete_not_fail():
    f = roof_facts()
    f["measure"]["roof_room_front_setback_m"]["value"] = None
    res = evaluate_rule(approved("BB-POL26-RR-SETBACK"), f, SRC, False)
    assert res.status == "UNCERTAIN" and "INCOMPLETE" in res.flags


def test_applicability_unknown_when_fact_missing():
    f = roof_facts()
    del f["case"]["building_existing"]
    res = evaluate_rule(approved("BB-POL26-RR-SETBACK"), f, SRC, False)
    assert res.status == "UNCERTAIN" and "APPLICABILITY_UNKNOWN" in res.flags


# ---------------------------------------------------------------- floors per zone
@pytest.mark.parametrize("zone,floors,expected", [
    ("residential_B", 5, "PASS"), ("residential_B", 6, "FAIL"), ("residential_C", 5, "PASS"),
    ("residential_A", 4, "PASS"), ("residential_A", 5, "FAIL"), ("residential_B1", 5, "FAIL")])
def test_floor_limit_by_zone(zone, floors, expected):
    f = roof_facts(typical_floors_above_entry=floors)
    f["case"]["zone"] = zone
    assert evaluate_rule(approved("BB-POL26-FLOORS"), f, SRC, False).status == expected


def test_floor_limit_unknown_zone_is_uncertain():
    f = roof_facts(typical_floors_above_entry=4)
    f["case"]["zone"] = None
    res = evaluate_rule(approved("BB-POL26-FLOORS"), f, SRC, False)
    assert res.status == "UNCERTAIN"


# ---------------------------------------------------------------- consent 100% / 75% (§4ז)
@pytest.mark.parametrize("attach,pct,expected", [
    ("common_property", 100, "PASS"), ("common_property", 99, "FAIL"),
    ("attached_to_roof_apartment", 75, "PASS"), ("attached_to_roof_apartment", 74, "FAIL")])
def test_consent_threshold_depends_on_attachment(attach, pct, expected):
    f = roof_facts(roof_attachment_status=attach, consent_pct=pct)
    assert evaluate_rule(approved("BB-POL26-CONSENT"), f, SRC, False).status == expected


def test_consent_unknown_attachment_uncertain():
    f = roof_facts(consent_pct=80)
    assert evaluate_rule(approved("BB-POL26-CONSENT"), f, SRC, False).status == "UNCERTAIN"


# ---------------------------------------------------------------- guidance / conditions never auto-fail
def test_qualitative_guideline_never_fails():
    f = roof_facts()
    f["case"]["permit_type"] = "addition_extension"
    res = evaluate_rule(approved("BB-SG16-30.8-FACADE"), f, SRC, False)
    assert res.status == "UNCERTAIN" and "REVIEW_REQUIRED" in res.flags


def test_condition_flagged_not_failed():
    res = evaluate_rule(approved("BB-POL26-BETTERMENT"), roof_facts(), SRC, False)
    assert res.status == "UNCERTAIN" and "CONDITION_FOR_PERMIT" in res.flags


def test_service_guidelines_not_applied_to_additions():
    f = roof_facts()
    f["case"]["permit_type"] = "addition_extension"
    assert evaluate_rule(approved("BB-SERV24-NEW-ONLY"), f, SRC, False).status == "NA"


def test_missing_threshold_in_source_is_uncertain():
    f = roof_facts(building_height_m=30)
    f["case"].update(permit_type="addition_extension", applicable_plans=["בב/105"])
    res = evaluate_rule(approved("BB-B105-MAX-HEIGHT"), f, SRC, False)
    assert res.status == "UNCERTAIN" and "THRESHOLD_SOURCE_MISSING" in res.flags


def test_spatial_scope_unknown_without_plans():
    f = roof_facts(building_height_m=30)
    f["case"].update(permit_type="addition_extension", applicable_plans=[])
    res = evaluate_rule(approved("BB-B105-MAX-HEIGHT"), f, SRC, False)
    assert res.status == "UNCERTAIN" and "APPLICABILITY_UNKNOWN" in res.flags


# ---------------------------------------------------------------- demo isolation + conflicts
def test_demo_rule_inactive_on_real_tenant():
    f = roof_facts()
    f["case"]["permit_type"] = "addition_sukkah"
    f["measure"]["sukkah_to_plot_boundary_m"] = {"value": 0.1, "uncertainty": 0}
    assert evaluate_rule(RULES["DEMO-SUKKAH-MIN-SIDE"], f, SRC, tenant_is_demo=False).status == "NA"
    assert evaluate_rule(RULES["DEMO-SUKKAH-MIN-SIDE"], f, SRC, tenant_is_demo=True).status == "FAIL"


def test_conflicting_sources_raise_conflict_not_decision():
    a = approved("BB-POL26-RR-SETBACK")
    b = Rule(copy.deepcopy(a.raw))
    b.raw["id"] = "OTHER-SOURCE-SETBACK"
    b.raw["check"]["threshold"] = 3.0
    out = evaluate([a, b], roof_facts(2.7), SRC, False)
    conflicts = [r for r in out if r.rule_id.startswith("CONFLICT:")]
    assert len(conflicts) == 1 and conflicts[0].status == "UNCERTAIN"
    assert "SOURCE_CONFLICT" in conflicts[0].flags


def test_every_result_has_citation():
    f = roof_facts(typical_floors_above_entry=5, consent_pct=100, roof_attachment_status="common_property")
    for r in evaluate(list(RULES.values()), f, SRC, True):
        if not r.rule_id.startswith("CONFLICT:"):
            assert r.citations, r.rule_id
            assert all(c["source_id"] in SRC for c in r.citations), r.rule_id


@pytest.mark.parametrize("op,v,t,exp", [(">=", 1, 1, "PASS"), (">", 1, 1, "FAIL"), ("<=", 1, 1, "PASS"),
                                        ("<", 1, 1, "FAIL"), ("==", 1, 1, "PASS"), ("==", 1.1, 1, "FAIL")])
def test_compare_operators(op, v, t, exp):
    assert compare(v, 0, op, t) == exp


def test_rule_schema_complete():
    required = {"id", "version", "title_he", "legal_level", "review_state", "check", "sources"}
    for r in RULES.values():
        assert required <= set(r.raw), r.id
