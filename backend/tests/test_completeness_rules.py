"""Completeness rules added after the blind test of Bnei Brak application 202401320.

The committee refused it on 17/06/2025 for missing documents ("אישור ועדת נכים", "השלמת חתימות")
and approved it unchanged on 26/11/2025 after an updated inspection report.
"""
import copy

import pytest

from app.batch_import import guess_doc_type
from app.config import settings
from app.knowledge import load_sources
from app.rules.derived import derive_completeness_facts
from app.rules.engine import Rule, evaluate_rule, load_rules

RULES = {r.id: r for r in load_rules([settings.knowledge_dir / "rules" / f for f in ("bnei_brak.yaml", "internal_qa.yaml")])}
SRC = load_sources()
NEW = ["BB-COMP-DISABLED-UNIT-APPROVAL", "BB-COMP-OWNER-SIGNATURES", "BB-COMP-REG36-NOTICE",
       "BB-COMP-LEGALIZATION-INSPECTION", "QA-OWNER-SIGNATURE-PCT", "QA-PLOT-AREA-VS-CADASTRE"]
TITLE_202401320 = "מוצע הכשרת דירת נכה ( מצב קיים) בקומת הקרקע בבניין בן 3 קומות"


def facts(title=TITLE_202401320, declared=None, docs=()):
    declared = declared or {}
    return {"case": {"permit_type": "addition_extension", "stage": "permit_request", "reference_date": "2024-12-10",
                     "applicable_plans": ["105/ב"], "building_existing": True},
            "declared": declared, "docs": {"present": {d: True for d in docs}},
            "facts_derived": derive_completeness_facts(title, None, declared), "measure": {}}


def approved(rule_id):
    r = Rule(copy.deepcopy(RULES[rule_id].raw))
    r.raw["review_state"] = "PROFESSIONALLY_APPROVED"
    return r


def run(rule_id, f, binding=True):
    return evaluate_rule(approved(rule_id) if binding else RULES[rule_id], f, SRC, False)


def test_new_rules_cite_registered_sources_and_report_as_completeness():
    for rid in NEW:
        r = RULES[rid]
        assert r.raw.get("sources"), rid
        assert all(s["source_id"] in SRC for s in r.raw["sources"]), rid
    for rid in NEW[:4]:
        assert RULES[rid].raw["report"] == "completeness"


# ------------------------------------------------------------------ derived facts
def test_text_inference_for_the_blind_case():
    d = derive_completeness_facts(TITLE_202401320, None, {})
    assert d["disabled_unit_requested"] is True and d["legalization_existing"] is True


def test_declared_values_override_text():
    d = derive_completeness_facts(TITLE_202401320, None, {"disabled_unit": False, "legalization_existing": False})
    assert d["disabled_unit_requested"] is False and d["legalization_existing"] is False


def test_ordinary_roof_room_infers_false_and_no_text_leaves_unset():
    d = derive_completeness_facts("תוספת חדרי גג לדירה בקומה ב'", None, {})
    assert d == {"disabled_unit_requested": False, "legalization_existing": False}
    assert derive_completeness_facts(None, None, {}) == {}


@pytest.mark.parametrize("signed,total,pct,incomplete", [(13, 16, 81.25, True), (16, 16, 100.0, False), (0, 4, 0.0, True)])
def test_signature_percentage(signed, total, pct, incomplete):
    d = derive_completeness_facts("x", None, {"owners_signed": signed, "owners_total": total})
    assert d["owner_signatures_pct"] == pct and d["owner_signatures_incomplete"] is incomplete


@pytest.mark.parametrize("signed,total", [(5, 0), (17, 16), ("?", 16), (None, 16)])
def test_invalid_signature_counts_are_not_derived(signed, total):
    assert "owner_signatures_pct" not in derive_completeness_facts("x", None, {"owners_signed": signed, "owners_total": total})


# ------------------------------------------------------------------ the 202401320 refusal grounds
def test_disabled_unit_without_committee_approval_fails():
    res = run("BB-COMP-DISABLED-UNIT-APPROVAL", facts())
    assert res.status == "FAIL" and "ועדת נכים" in res.explanation_he


def test_disabled_unit_with_committee_approval_passes():
    assert run("BB-COMP-DISABLED-UNIT-APPROVAL", facts(docs=["disabled_committee_approval"])).status == "PASS"


def test_disabled_rule_not_applied_to_ordinary_request():
    assert run("BB-COMP-DISABLED-UNIT-APPROVAL", facts(title="תוספת חדרי גג")).status == "NA"


def test_unapproved_completeness_rule_is_advisory_only():
    res = run("BB-COMP-DISABLED-UNIT-APPROVAL", facts(), binding=False)
    assert res.computed_result == "FAIL" and res.status == "UNCERTAIN" and "RULE_NOT_APPROVED" in res.flags


def test_missing_signatures_flagged_and_notice_proof_required():
    f = facts(declared={"owners_signed": 13, "owners_total": 16})
    sig = run("BB-COMP-OWNER-SIGNATURES", f)
    assert sig.status == "FAIL" and sig.measured_value == 81.25 and sig.threshold == 100
    assert run("BB-COMP-REG36-NOTICE", f).status == "FAIL"
    f["docs"]["present"]["reg36_notice_proof"] = True
    assert run("BB-COMP-REG36-NOTICE", f).status == "PASS"


def test_full_signatures_pass_and_notice_rule_not_applicable():
    f = facts(declared={"owners_signed": 16, "owners_total": 16})
    assert run("BB-COMP-OWNER-SIGNATURES", f).status == "PASS"
    assert run("BB-COMP-REG36-NOTICE", f).status == "NA"


def test_signature_rules_silent_when_counts_not_entered():
    f = facts()
    assert run("BB-COMP-OWNER-SIGNATURES", f).status == "NA"
    assert run("BB-COMP-REG36-NOTICE", f).status == "NA"


def test_legalization_needs_inspection_report():
    assert run("BB-COMP-LEGALIZATION-INSPECTION", facts()).status == "FAIL"
    assert run("BB-COMP-LEGALIZATION-INSPECTION", facts(docs=["inspection_report"])).status == "PASS"
    assert run("BB-COMP-LEGALIZATION-INSPECTION", facts(title="תוספת חדרי גג")).status == "NA"


# ------------------------------------------------------------------ internal QA
def test_stated_signature_percentage_mismatch_202500019():
    """Protocol 20250218: '13 of 16 = 81.12%' — actually 81.25%."""
    f = facts(declared={"owners_signed": 13, "owners_total": 16, "owner_signatures_pct_stated": 81.12})
    assert evaluate_rule(RULES["QA-OWNER-SIGNATURE-PCT"], f, SRC, False).status == "FAIL"
    f["declared"]["owner_signatures_pct_stated"] = 81.25
    f["facts_derived"] = derive_completeness_facts(TITLE_202401320, None, f["declared"])
    assert evaluate_rule(RULES["QA-OWNER-SIGNATURE-PCT"], f, SRC, False).status == "PASS"


def test_plot_area_differs_from_registered_parcel_202401320():
    f = facts(declared={"plot_area_m2": 578, "parcel_registered_area_m2": 502})
    res = evaluate_rule(RULES["QA-PLOT-AREA-VS-CADASTRE"], f, SRC, False)
    assert res.status == "FAIL" and res.report == "rights"
    f["declared"]["parcel_registered_area_m2"] = 578
    assert evaluate_rule(RULES["QA-PLOT-AREA-VS-CADASTRE"], f, SRC, False).status == "PASS"


# ------------------------------------------------------------------ document intake
@pytest.mark.parametrize("name,expected", [("אישור ועדת נכים.pdf", "disabled_committee_approval"),
                                           ("דוח פיקוח 27.02.25.pdf", "inspection_report"),
                                           ("הודעה לבעלים תקנה 36.pdf", "reg36_notice_proof"),
                                           ("מפת מדידה.pdf", "survey_map")])
def test_filename_hints_for_new_doc_types(name, expected):
    assert guess_doc_type(name, "pdf", "", None)[0] == expected
