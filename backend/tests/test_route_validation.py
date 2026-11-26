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


def _ev():
    spec = importlib.util.spec_from_file_location("ev", ROOT / "scripts/evaluate_blind.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    return ev


@pytest.mark.skipif(not (_ev().eval_store() / "ground_truth/20210885.yaml").exists(),
                    reason="evaluation store not on this machine (ground truth is kept outside the repository)")
def test_20210885_evaluation_scores_after_the_engine():
    ev = _ev()
    engine = ev.run_engine(CASE)
    truth = ev.load_truth("20210885")
    sc = ev.score(engine, truth)
    assert sc["counts"] == {"DETECTED": 0, "FLAGGED": 2, "MISSED": 0} and sc["false_positives"] == []
    assert all(v["match"] for v in ev.rights_check(truth).values())    # the engine read the plan's rights as the committee did


def test_blind_inputs_are_allowlisted_and_scanned(tmp_path):
    ev = _ev()
    import shutil
    case = tmp_path / "20210885"
    shutil.copytree(CASE, case)
    ev.check_inputs(case)                                                   # the curated case passes
    (case / "notes.txt").write_text("x")
    with pytest.raises(SystemExit, match="allowlist"):
        ev.check_inputs(case)                                               # an unlisted file stops the run
    (case / "notes.txt").unlink()
    f = case / "register_facts.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["request_text"] += " החלטת הוועדה: סירוב"
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="changed"):
        ev.check_inputs(case)                                               # hash no longer matches the curation
    import hashlib
    allow = yaml.safe_load((case / "allowlist.yaml").read_text(encoding="utf-8"))
    allow["inputs"][0]["sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()
    (case / "allowlist.yaml").write_text(yaml.safe_dump(allow, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SystemExit, match="decision vocabulary"):
        ev.check_inputs(case)                                               # a relabelled decision is still caught


def test_score_refuses_without_a_frozen_result(tmp_path, monkeypatch):
    ev = _ev()
    monkeypatch.setattr(ev, "RESULTS", tmp_path)
    with pytest.raises(SystemExit, match="frozen"):
        ev.load_frozen("X")
    ev.freeze("X", {"verdict": "ROUTE_OK", "checks": []})
    assert ev.load_frozen("X")["verdict"] == "ROUTE_OK"
    (tmp_path / "X.engine.json").write_text('{"verdict": "WRONG_ROUTE", "checks": []}')
    with pytest.raises(SystemExit, match="changed after"):
        ev.load_frozen("X")                                                 # no editing results after the reveal


def test_ground_truth_is_not_in_the_repository():
    assert not (ROOT / "validation/ground_truth").exists() or not list((ROOT / "validation/ground_truth").glob("*.yaml"))
    assert ROOT not in _ev().eval_store().resolve().parents


# ---------------------------------------------------------------- short track: gross vs net (Karmiya, dev dataset)

def _karmiya(**kw):
    f = json.loads((ROOT / "validation/dev_cases/20260265/facts.json").read_text(encoding="utf-8"))
    base = dict(application_id="20260265", submission_date=dt.date(2026, 4, 13), plans=f["plans"], selected_route="SHORT",
                short_item=f["short_track_item"]["text_he"], short_item_limit_m2=f["short_track_item"]["limit_m2"],
                short_item_limit_source=f["short_track_item"]["limit_source"],
                declared_addition_m2=f["form_addition_area_m2"], gross_added_m2=f["gross_added_m2_from_description"],
                gross_added_source="applicant description", cancelled_unbuilt_m2=f["cancelled_unbuilt_m2_from_description"])
    return R.Proposal(**{**base, **kw})


def test_short_track_judged_on_gross_not_net():
    by = {c.topic: c for c in R.check_short_track(_karmiya())}
    assert by["short_track_size"].status == "WITHIN" and by["short_track_size"].measured == 18.0
    assert not by["short_track_size"].confirmable                       # from the description, not measured
    # 1 vs 18: a field discrepancy explained by the net change, never a route deviation
    assert by["short_track_fields"].status == "DOCUMENT_DISCREPANCY" and "18 − 17" in by["short_track_fields"].explanation_he
    assert R.required_route(list(by.values())) == "REGULAR"


def test_short_track_over_the_item_limit_needs_drawings_to_confirm():
    c = R.check_short_track(_karmiya(gross_added_m2=30.0))[0]
    assert c.status == "DEVIATION_UNCLASSIFIED" and not c.confirmable and c.needs
    c = R.check_short_track(_karmiya(gross_added_m2=30.0, gross_added_source="drawings"))[0]
    assert c.confirmable
    assert R.check_short_track(_karmiya(gross_added_m2=None))[0].status == "NOT_CHECKED"
    assert R.check_short_track(_karmiya(selected_route="REGULAR")) == []


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


def test_declared_relief_is_judged_without_a_rights_file():
    """A relief named in the request while filed without reliefs is a wrong route even when the plan's rights are not
    in the knowledge base; the words 'without reliefs' are not a relief."""
    base = dict(application_id="X", submission_date=dt.date(2022, 1, 1), plans=["NO-SUCH-PLAN"], selected_route="REGULAR")
    res = R.validate(R.Proposal(**base, request_text="תוספת חדר + הקלה בקו בניין צידי"))
    assert res.verdict == "WRONG_ROUTE" and res.confirmed
    res = R.validate(R.Proposal(**base, request_text="תוספת חדר ללא הקלות"))
    assert res.verdict == "NO_RIGHTS" and not [c for c in res.checks if c.topic == "declared_relief"]


# ------------------------------------------------------------------ Hof Ashkelon plan rights (knowledge/rights/hof_*)

def _hof(plan, lot, **kw):
    base = dict(application_id="X", submission_date=dt.date(2020, 6, 1), plans=[plan], selected_route="REGULAR", lot=lot,
                main_use="מגורים", total_main_m2=300.0, total_service_m2=100.0)
    return R.validate(R.Proposal(**{**base, **kw}))


def test_netiv_haasara_lot_rights_and_zone():
    res = _hof("2/228/03/6", "12")
    st = {c.topic: (c.status, c.limit) for c in res.checks}
    assert st["aggregate_main"] == ("WITHIN", 640) and st["aggregate_service"] == ("WITHIN", 275)
    assert _hof("2/228/03/6", "12", total_main_m2=700.0).verdict == "WRONG_ROUTE"        # above 640 m² main
    assert _hof("2/228/03/6", "20").verdict == "NO_RIGHTS"                               # lot outside the residential zones
    assert _hof("2/228/03/6", "12", main_use="מבנה חקלאי").verdict == "NO_RIGHTS"         # residential rights only
    assert _hof("2/228/03/6", "246 B").verdict == "NO_RIGHTS"                            # never guessed into a range


def test_nitzan_per_lot_main_area_and_percent_rights():
    def main_lim(lot, **kw):
        return {c.topic: c.limit for c in _hof("291/03/6", lot, **kw).checks}.get("aggregate_main")
    assert main_lim("209") == 178 and main_lim("303") == 352 and main_lim("205") == 354 and main_lim("110") == 357
    assert main_lim("650") == 350
    assert _hof("291/03/6", "50").verdict == "NO_RIGHTS"                                 # % of the lot area, area unknown
    assert main_lim("50", lot_area_m2=500.0) == 275.0                                    # 55% of 500 m²


def test_addition_areas_are_not_compared_with_lot_rights():
    res = _hof("2/228/03/6", "12", areas_scope="addition", total_main_m2=69.0)
    assert [(c.topic, c.status) for c in res.checks if c.topic.startswith("aggregate")] == [("aggregate", "NOT_CHECKED")]
    f = {"application_id": "X", "submission_date": "01/01/2020", "description": "בנייה חדשה",
         "request_text": "אישור בדיעבד לבית מגורים קיים ותוספת שטחים", "land": [{"מספר מגרש": "12"}]}
    assert R.proposal_from_register(f).areas_scope == "addition"
    assert R.proposal_from_register({**f, "request_text": "הקמת בית מגורים הכולל שינוי מפלס 0.00"}).areas_scope == "total"


def test_parcellation_plans_take_the_outline_plan_rights():
    """ד/821 defers to the outline plan 234/02/6: a farm holding gets up to 375 m² gross (2 × 160 + 55)."""
    res = _hof("ד/821", "5", total_main_m2=300.0, total_service_m2=100.0)
    st = {c.topic: (c.status, c.limit) for c in res.checks}
    assert st["aggregate_total"] == ("DEVIATION_UNCLASSIFIED", 375) and "234/02/6" in res.law_notes[0]
    assert _hof("ד/821", "5", total_main_m2=200.0, total_service_m2=60.0).checks[0].status == "WITHIN"
    assert _hof("ד/821", "105").verdict == "NO_RIGHTS"                    # auxiliary farm: no rights in the outline plan
    assert _hof("ד/821", "5", submission_date=dt.date(1985, 1, 1)).verdict == "NO_RIGHTS"   # before 234/02/6
    assert _hof("ד/820", "5").verdict == "NO_RIGHTS"                     # zone table without lot numbers


def test_pre_1989_plan_checks_the_total_only():
    p = R.Proposal(application_id="X", submission_date=dt.date(2020, 1, 1), plans=["2/166/03/6"], selected_route="REGULAR",
                   land_use="אזור מגורים בישוב חקלאי", main_use="מגורים", total_main_m2=300.0, total_service_m2=120.0)
    st = {c.topic: (c.status, c.limit) for c in R.validate(p).checks}
    assert st["aggregate_total"] == ("DEVIATION_UNCLASSIFIED", 400)
    assert "האזור" in R.validate(R.Proposal(**{**p.__dict__, "land_use": None})).law_notes[0]   # zone unknown from the register


def test_half_lot_gets_its_zone_but_not_whole_lot_rights():
    res = _hof("291/03/6", "653 ב'")
    assert res.verdict == "INSUFFICIENT_EVIDENCE"
    assert [(c.topic, c.status) for c in res.checks] == [("aggregate", "NOT_CHECKED"), ("floors", "NOT_CHECKED")]
    assert "דו־משפחתי" in res.checks[0].explanation_he
