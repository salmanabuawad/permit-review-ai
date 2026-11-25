"""Licensing Route Validation Engine (app/rules/route.py): regular licensing, relief-required, prohibited deviations,
floor-specific violations behind passing aggregates, law as of the submission date, and the blind regression for
application 20210885 (Be'er Ganim) — whose official decision is ground truth only, never an input."""
import datetime as dt
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.rules import evidence as E
from app.rules import route as R

ROOT = Path(__file__).resolve().parents[2]
D = dt.date(2021, 9, 29)


def proposal(**kw):
    base = dict(application_id="T1", submission_date=D, plans=["תמא 39"], land_use="מגורים חד משפחתי", lot_area_m2=502.1,
                selected_route="REGULAR", route_source="test", total_main_m2=219.0, total_service_m2=125.0,
                floors=[R.Floor("קומת קרקע", 140.0, 50.0), R.Floor("קומה א", 79.0, 15.0),
                        R.Floor("מרתף", 0.0, 60.0, below_entrance=True, ceiling_above_ground_m=0.9)],
                floors_source="drawings")
    base.update(kw)
    return R.Proposal(**base)


# ---------------------------------------------------------------- the plan's rights, as read from the plan

def test_rights_file_reads_the_plan():
    r = yaml.safe_load((ROOT / "knowledge/rights/tama39_residential_single.yaml").read_text(encoding="utf-8"))
    rt = r["rights"]
    assert (rt["main_m2"], rt["service_above_m2"], rt["service_below_m2"], rt["total_m2"]) == (220, 70, 60, 350)
    assert rt["main_m2"] + rt["service_above_m2"] + rt["service_below_m2"] == rt["total_m2"]     # the table closes
    ocr = (ROOT / "knowledge/source_texts/tama39/p047.txt").read_text(encoding="utf-8")
    assert "220" in ocr and "60" in ocr and "350" in ocr and "למרתף" in ocr                        # quoted from the source


# ---------------------------------------------------------------- regular licensing

def test_regular_route_within_all_rights():
    res = R.validate(proposal())
    assert res.verdict == "ROUTE_OK" and res.route_needed == "REGULAR"
    assert {c.topic: c.status for c in res.checks}["basement_area"] == "WITHIN"


# ---------------------------------------------------------------- floor-specific violation behind passing aggregates

def _rights(tmp_path, **transfers):
    """A plan like TAMA 39 with a chosen transfer rule, written to a temporary rights folder."""
    r = yaml.safe_load((ROOT / "knowledge/rights/tama39_residential_single.yaml").read_text(encoding="utf-8"))
    r["transfers"] = transfers
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump(r, allow_unicode=True), encoding="utf-8")
    return tmp_path


def test_basement_over_its_limit_while_totals_comply(tmp_path):
    # a plan without transfers: totals 219 / 120 are within 220 / 130, but the basement holds 75 m² > 60 m²
    p = proposal(total_service_m2=120.0, floors=[R.Floor("קומת קרקע", 140.0, 35.0), R.Floor("קומה א", 79.0, 10.0),
                                                R.Floor("מרתף", 0.0, 75.0, below_entrance=True, ceiling_above_ground_m=0.9)])
    res = R.validate(p, rights_folder=_rights(tmp_path, to_basement=False))
    by = {c.topic: c for c in res.checks}
    assert by["aggregate_main"].status == "WITHIN" and by["aggregate_service"].status == "WITHIN"
    assert by["basement_area"].status == "RELIEF" and by["basement_area"].limit == 60
    assert res.verdict == "WRONG_ROUTE" and res.confirmed                 # regular route with a deviation needing relief


def test_transfer_to_basement(tmp_path):
    floors = [R.Floor("קומת קרקע", 140.0, 35.0), R.Floor("קומה א", 55.0, 10.0),
              R.Floor("מרתף", 0.0, 85.0, below_entrance=True, ceiling_above_ground_m=0.5)]
    p = proposal(total_service_m2=130.0, floors=floors)
    st = lambda **t: {c.topic: c.status for c in R.validate(p, rights_folder=_rights(tmp_path, **t)).checks}["basement_area"]
    assert st(to_basement=True, mechanism="by_right") == "WITHIN"          # 85 ≤ 60 + 25 unused above-ground rights
    assert st(to_basement=True, mechanism="relief") == "RELIEF"
    # TAMA 39 itself: "תותר העברה" does not say by right or by relief -> possible deviation, never decided
    res = R.validate(p)
    assert {c.topic: c.status for c in res.checks}["basement_area"] == "POSSIBLE_DEVIATION" and res.verdict == "INSUFFICIENT_EVIDENCE"


def test_raised_basement_is_a_floor():
    p = proposal(floors=[R.Floor("קומת קרקע", 140.0, 50.0), R.Floor("קומה א", 79.0, 15.0),
                         R.Floor("מרתף", 0.0, 60.0, below_entrance=True, ceiling_above_ground_m=1.6)])
    by = {c.topic: c for c in R.validate(p).checks}
    assert by["floors_above"].status == "PROHIBITED" and by["floors_above"].measured == 3 and by["floors_above"].reg == "2(8)"


# ---------------------------------------------------------------- relief-required applications

def test_relief_route_with_relief_deviation_is_ok():
    p = proposal(selected_route="RELIEF", setbacks=[R.Setback("rear", 5.0, 3.6, "wall", openings=False)])
    res = R.validate(p)
    assert {c.topic: c.status for c in res.checks}["setback_rear"] == "RELIEF"     # 28% without openings: reg. 2(7)(c)
    assert res.route_needed == "NOT_REGULAR" and res.verdict != "WRONG_ROUTE"


def test_regular_route_with_relief_deviation_is_wrong_route():
    res = R.validate(proposal(setbacks=[R.Setback("side", 3.0, 2.75, "wall", openings=True)]))  # 8% with openings, ≥2.70
    assert res.verdict == "WRONG_ROUTE" and res.confirmed


# ---------------------------------------------------------------- prohibited deviations

def test_service_area_used_as_main_is_prohibited():
    p = proposal(selected_route="RELIEF", floors=[R.Floor("קומת קרקע", 140.0, 50.0), R.Floor("קומה א", 79.0, 15.0),
                                                 R.Floor("מרתף", 0.0, 60.0, below_entrance=True, ceiling_above_ground_m=0.9,
                                                         service_used_as_main_m2=24.0)])
    res = R.validate(p)
    assert res.route_needed == "PROHIBITED" and res.verdict == "PROHIBITED_DEVIATION"
    assert {c.topic: c.reg for c in res.checks}["service_to_main"] == "2(16)"


def test_prohibited_not_confirmed_when_law_version_unverified():
    # the encoded deviation regulations are consolidated to 2011: a 2021 request cannot get a CONFIRMED prohibition
    res = R.validate(proposal(selected_route="RELIEF", setbacks=[R.Setback("front", 5.0, 3.0, "wall", openings=True)]))
    assert res.verdict == "PROHIBITED_DEVIATION" and not res.confirmed
    assert any("לא אומתו" in n for n in res.law_notes)


def test_prohibited_confirmed_when_law_in_force_is_verified():
    res = R.validate(proposal(submission_date=dt.date(2010, 5, 1), selected_route="RELIEF",
                              setbacks=[R.Setback("front", 5.0, 3.0, "wall", openings=True)]))
    assert res.verdict == "PROHIBITED_DEVIATION" and res.confirmed


def test_regular_route_with_unconfirmed_prohibition_is_still_wrong_route():
    res = R.validate(proposal(setbacks=[R.Setback("front", 5.0, 3.0, "wall", openings=True)]))
    assert res.verdict == "WRONG_ROUTE" and res.confirmed


# ---------------------------------------------------------------- law as of the submission date

def test_plan_not_in_force_on_submission_date():
    res = R.validate(proposal(submission_date=dt.date(2004, 1, 1)))
    assert res.verdict == "NO_RIGHTS" and any("אחרי מועד הגשת הבקשה" in n for n in res.law_notes)


def test_building_line_classification():
    law = yaml.safe_load((ROOT / "knowledge/law/deviation_regulations_2002.yaml").read_text(encoding="utf-8"))
    assert R.classify_setback(R.Setback("front", 5, 4, "balcony", height_m=2.6), law).status == "RELIEF"      # 1 m, 20%
    assert R.classify_setback(R.Setback("front", 5, 2.5, "balcony", height_m=2.6), law).status == "PROHIBITED"  # 2.5 m
    assert R.classify_setback(R.Setback("side", 3, 2.6, "wall", openings=False), law).status == "PROHIBITED"   # < 2.70 m
    assert R.classify_setback(R.Setback("rear", 5, 5, "wall"), law).status == "WITHIN"


# ---------------------------------------------------------------- blind regression: 20210885 (Be'er Ganim)

CASE = ROOT / "validation/cases/20210885"


def test_20210885_blind_engine_result():
    facts = json.loads((CASE / "register_facts.json").read_text(encoding="utf-8"))
    gis = json.loads((CASE / "gis.json").read_text(encoding="utf-8"))
    p = R.proposal_from_register(facts, gis)
    assert p.selected_route == "REGULAR" and p.submission_date == D and p.plans == ["תמא 39"]
    res = R.validate(p)
    by = {c.topic: c for c in res.checks}
    # aggregate rights are met — and that proves nothing about the basement
    assert by["aggregate_main"].status == "WITHIN" and by["aggregate_service"].status == "WITHIN"
    assert by["floors"].status == "NOT_CHECKED" and "תכנית קומת המרתף" in by["floors"].needs
    assert by["zero_level"].status == "POSSIBLE_DEVIATION"
    # no drawings: no confirmed defect, and the missing inputs are named
    assert res.verdict == "INSUFFICIENT_EVIDENCE" and not res.confirmed


def test_20210885_evaluation_scores_after_the_engine():
    spec = importlib.util.spec_from_file_location("ev", ROOT / "scripts/evaluate_blind.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    engine = ev.run_engine(CASE)
    truth = yaml.safe_load((ROOT / "validation/ground_truth/20210885.yaml").read_text(encoding="utf-8"))
    sc = ev.score(engine, truth)
    assert sc["counts"] == {"DETECTED": 0, "FLAGGED": 2, "MISSED": 0} and sc["false_positives"] == []
    assert all(v["match"] for v in ev.rights_check(truth).values())    # the engine read the plan's rights as the committee did


def test_ground_truth_is_never_an_engine_input():
    for py in (ROOT / "backend/app").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "ground_truth" not in text and "validation/" not in text, py
    assert "decision" not in json.loads((CASE / "register_facts.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- inside the review (resolvers)

def _ctx(declared, docs=()):
    return E.Context(list(docs), declared, "", None, {}, [])


def test_resolver_na_without_rights_file():
    r = E.r_licensing_route(_ctx({"submission_date": "2026-11-11", "plans_declared": ["633-0723718"]}))
    assert r.status == "NA"


def test_resolver_wrong_route_is_a_confirmed_defect():
    # per-floor table declared: totals exceed the plan's service rights -> a deviation; filed without reliefs
    floors = [{"name": "קומת קרקע", "main_m2": 140.0, "service_m2": 60.0}, {"name": "קומה א", "main_m2": 79.0, "service_m2": 10.0},
              {"name": "מרתף", "service_m2": 75.0, "below_entrance": True, "ceiling_above_ground_m": 0.9}]
    ctx = _ctx({"submission_date": "2021-09-29", "plans_declared": ["תמא 39"], "main_use": "מגורים חד משפחתי",
                "licensing_route": "REGULAR", "main_area_m2": 219.0, "service_area_m2": 145.0, "floors": 2, "floor_areas": floors})
    r = E.r_licensing_route(ctx)
    assert r.status == "FAIL" and r.review == "CONFIRMED_DEFECT" and r.items[0]["title_he"] == "מסלול רישוי שגוי"
    f = E.r_floor_rights(ctx)
    assert f.status == "FAIL" and any(i["title_he"] == "שטח המרתף" for i in f.items)


def test_resolver_insufficient_without_floors():
    ctx = _ctx({"submission_date": "2021-09-29", "plans_declared": ["תמא 39"], "main_use": "מגורים",
                "licensing_route": "REGULAR", "main_area_m2": 219.45, "service_area_m2": 128.35, "floors": 3})
    assert E.r_licensing_route(ctx).review == "NOT_CHECKED" and E.r_floor_rights(ctx).review == "NOT_CHECKED"
