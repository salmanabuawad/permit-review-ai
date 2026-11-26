"""V9 update: applicable-regulation resolution, component validation, relief validation, rights by category and floor,
decision taxonomy, version comparison, blind-dataset sanitization, and the known-outcome case 20221189."""
import datetime as dt
import importlib
import io
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from app.blind_sanitizer import BlindDatasetSanitizer
from app.lifecycle import ApplicationVersion, ApplicationVersionComparator, build_lifecycle, classify_decision_text
from app.rules import route as R
from app.rules.applicability import AppContext, ApplicableRegulationResolver
from app.rules.components import Component, Measure, validate_component
from app.rules.relief import ReliefRequest, ReliefValidationEngine

ROOT = Path(__file__).resolve().parents[2]
LAW = yaml.safe_load((ROOT / "knowledge/law/deviation_regulations_2002.yaml").read_text(encoding="utf-8"))


def ctx(plans=("6/123/03/6",), lot="440", date=dt.date(2022, 10, 26), use="מגורים"):
    return AppContext("T", date, list(plans), "3161", "151", lot, use)


@pytest.fixture(scope="module")
def talmei():
    return ApplicableRegulationResolver().resolve(ctx())


def parking(inner=None, outer=None, src="declared", relief=()):
    m = {}
    if inner is not None:
        m["inner_height_m"] = Measure(inner, src)
    if outer is not None:
        m["outer_height_m"] = Measure(outer, src)
    return Component("covered_parking", m, reliefs=list(relief))


def by_attr(fs):
    return {f.attribute: f for f in fs}


# ------------------------------------------------------------------ components: internal vs external height

def test_internal_parking_height_within(talmei):
    f = by_attr(validate_component(parking(inner=2.20), talmei.limits))["inner_height_m"]
    assert f.status == "WITHIN" and f.permitted == 2.2 and f.regulation["plan"] == "633-0928358"


def test_internal_height_exceeds(talmei):
    f = by_attr(validate_component(parking(inner=2.63), talmei.limits))["inner_height_m"]
    assert f.status == "EXCEEDS" and f.deviation_abs == 0.43 and f.deviation_pct == 19.55


def test_external_height_exceeds(talmei):
    fs = by_attr(validate_component(parking(inner=2.10, outer=2.70), talmei.limits))
    assert fs["outer_height_m"].status == "EXCEEDS" and fs["outer_height_m"].permitted == 2.5
    assert fs["inner_height_m"].status == "WITHIN"


def test_internal_and_external_heights_are_never_interchanged(talmei):
    # 2.40 inside is within the 2.5 EXTERNAL limit but above the 2.2 INTERNAL one — it must fail on its own limit
    fs = by_attr(validate_component(parking(inner=2.40, outer=2.40), talmei.limits))
    assert fs["inner_height_m"].status == "EXCEEDS" and fs["inner_height_m"].permitted == 2.2
    assert fs["outer_height_m"].status == "WITHIN" and fs["outer_height_m"].permitted == 2.5


def test_missing_geometric_evidence(talmei):
    fs = by_attr(validate_component(parking(), talmei.limits))
    assert fs["inner_height_m"].status == "NO_MEASUREMENT" and fs["outer_height_m"].status == "NO_MEASUREMENT"
    a = ReliefValidationEngine(LAW).assess(ReliefRequest("covered_parking", "inner_height_m", None), talmei.limits)
    assert a.outcome == "INSUFFICIENT_EVIDENCE" and not a.external
    v = ApplicationVersionComparator().compare(
        ApplicationVersion("original", "app", components={"covered_parking.inner_height_m": 2.63}),
        ApplicationVersion("approved", "permit", geometry_available=False))
    assert v[0].status == "NOT_VERIFIED" and "not inferred" in v[0].evidence


def test_committee_reported_values_are_labelled_not_independent(talmei):
    f = by_attr(validate_component(parking(inner=2.63, src="committee_reported"), talmei.limits))["inner_height_m"]
    assert f.evidence_source == "committee_reported" and not f.independent
    with pytest.raises(ValueError):
        Measure(2.0, "guessed")


# ------------------------------------------------------------------ relief validation

def test_relief_without_justification(talmei):
    a = ReliefValidationEngine(LAW).assess(ReliefRequest("covered_parking", "inner_height_m", 2.63,
                                                         text="הקלה לגובה פנימי לחניה מקורה, מבוקש 2.63"), talmei.limits)
    assert a.outcome == "MISSING_PLANNING_JUSTIFICATION" and a.discretionary and not a.external
    assert a.legally_available == "CONDITIONAL" and a.permitted == 2.2 and a.deviation_pct == 19.55
    assert any("149" in x for x in a.procedural)


def test_relief_with_justification_is_still_discretionary(talmei):
    a = ReliefValidationEngine(LAW).assess(ReliefRequest("covered_parking", "inner_height_m", 2.63,
                                                         justification="שיפוע המגרש מחייב"), talmei.limits)
    assert a.outcome == "DISCRETIONARY_DECISION_REQUIRED" and a.justification == "PROVIDED" and not a.external


def test_unrequested_excess_is_a_violation_only_on_declared_or_measured_values(talmei):
    eng = ReliefValidationEngine(LAW)
    assert eng.assess_violation(parking(inner=2.63), talmei.limits)[0].outcome == "CONFIRMED_VIOLATION"
    v = eng.assess_violation(parking(inner=2.63, src="committee_reported"), talmei.limits)[0]
    assert v.outcome == "INSUFFICIENT_EVIDENCE" and not v.external


# ------------------------------------------------------------------ applicable regulation resolver

def test_additional_plan_applies_to_the_property(talmei):
    st = {s.plan: s.status for s in talmei.sources}
    assert st["633-0928358"] == "APPLIES" and st["6/123/03/6"] == "APPLIES"
    assert talmei.limits[("covered_parking", "area_m2")].plan == "633-0928358"     # 30 m² governs over 31 m²
    assert {x.plan for x in talmei.superseded} == {"6/123/03/6"}


def test_additional_plan_not_applicable_to_the_property():
    zikim = ApplicableRegulationResolver().resolve(ctx(plans=("633-0723718",), lot="368"))
    st = {s.plan: s for s in zikim.sources}
    assert st["633-0928358"].status == "NOT_APPLICABLE" and st["633-0723718"].status == "APPLIES"
    assert "knowledge/rules" in st["633-0723718"].reason
    farm = ApplicableRegulationResolver().resolve(ctx(plans=("ד/822",), lot="5"))
    assert {s.plan: s.status for s in farm.sources}["633-0928358"] == "NOT_APPLICABLE"


def test_historical_applicability():
    old = ApplicableRegulationResolver().resolve(ctx(date=dt.date(2021, 6, 1)))
    st = {s.plan: s for s in old.sources}
    assert st["633-0928358"].status == "NOT_APPLICABLE" and "before it came into force" in st["633-0928358"].reason
    assert old.limits[("covered_parking", "area_m2")].value == 31.0                # the plan's own limit then
    assert ("covered_parking", "inner_height_m") not in old.limits


def test_conflicting_sources_without_a_relation_stay_unresolved(tmp_path):
    k = tmp_path / "knowledge"
    for d in ("rights", "building_provisions", "law"):
        (k / d).mkdir(parents=True)
    (k / "law/deviation_regulations_2002.yaml").write_text((ROOT / "knowledge/law/deviation_regulations_2002.yaml")
                                                           .read_text(encoding="utf-8"), encoding="utf-8")
    r = yaml.safe_load((ROOT / "knowledge/rights/hof_6_123_03_6_talmei_yafe.yaml").read_text(encoding="utf-8"))
    (k / "rights/p.yaml").write_text(yaml.safe_dump(r, allow_unicode=True), encoding="utf-8")
    b = yaml.safe_load((ROOT / "knowledge/building_provisions/hof_633_0928358.yaml").read_text(encoding="utf-8"))
    (k / "building_provisions/b.yaml").write_text(yaml.safe_dump(b, allow_unicode=True), encoding="utf-8")
    res = ApplicableRegulationResolver(k).resolve(ctx())
    assert res.limits[("covered_parking", "area_m2")].status == "GOVERNS"          # relation recorded: changes
    b["changes_plans"] = [{"plan": "6/123/03/6", "lots": ["401-469"]}]            # still a "changes" relation
    b2 = dict(b, plan="X-1", changes_plans=["6/123/03/6"])
    b2["provisions"] = dict(b["provisions"], covered_parking=dict(b["provisions"]["covered_parking"], area_max_m2=28))
    (k / "building_provisions/c.yaml").write_text(yaml.safe_dump(b2, allow_unicode=True), encoding="utf-8")
    res = ApplicableRegulationResolver(k).resolve(ctx())
    lim = res.limits[("covered_parking", "area_m2")]
    assert lim.status == "UNRESOLVED_CONFLICT" and lim.value is None and any("covered_parking.area_m2" in u for u in res.unresolved)


def test_resolution_is_cached_by_property_and_plan_version():
    calls, store = [], {}

    def cache(key, compute):
        if key not in store:
            calls.append(key)
            store[key] = compute()
        return store[key]
    rr = ApplicableRegulationResolver()
    a = rr.resolve(ctx(), cache=cache)
    b = rr.resolve(ctx(), cache=cache)
    assert len(calls) == 1 and a.limits.keys() == b.limits.keys() and rr.kb_version() in calls[0]


# ------------------------------------------------------------------ rights by category and floor

def _p(**kw):
    base = dict(application_id="T", submission_date=dt.date(2022, 10, 26), plans=["6/123/03/6"], lot="440",
                main_use="מגורים", selected_route="RELIEF", total_main_m2=179.61, total_service_m2=97.8)
    return R.Proposal(**{**base, **kw})


def test_total_within_but_basement_excessive():
    st = {c.topic: c.status for c in R.validate(_p(main_above_m2=179.61, main_below_m2=0, service_above_m2=37.8,
                                                   service_below_m2=60.0, split_source="declared")).checks}
    assert st["service_below"] == "DEVIATION_UNCLASSIFIED" and st["service_above"] == "WITHIN"


def test_total_within_but_above_ground_service_excessive():
    st = {c.topic: c.status for c in R.validate(_p(total_service_m2=100.0, main_above_m2=179.61, main_below_m2=0,
                                                   service_above_m2=60.0, service_below_m2=40.0,
                                                   split_source="declared")).checks}
    assert st["service_above"] == "DEVIATION_UNCLASSIFIED" and st["service_below"] == "WITHIN"


def test_unsplit_total_never_proves_compliance():
    st = {c.topic: c.status for c in R.validate(_p()).checks}
    assert st["aggregate_service"] == "NOT_CHECKED" and st["aggregate_main"] == "WITHIN"


# ------------------------------------------------------------------ decisions and lifecycle

def test_relief_refusal_is_not_an_application_rejection():
    assert classify_decision_text("החלטה לסרב להקלה להגבהת גובה החניה. אין כל הצדקה תכנונית") == "RELIEF_REJECTED"
    assert classify_decision_text("החלטה לסרב לבקשה הבקשה נפתחה במסלול לא נכון") == "APPLICATION_REJECTED"


def test_rejected_relief_followed_by_approval():
    hist = [{"description": "החלטה לסרב", "date": "18/04/2023"},
            {"description": "בקרה מרחבית-הוחזר לעורך הבקשה להמשך טיפול", "date": "22/05/2023"},
            {"description": "הפקת היתר", "date": "30/07/2023"}]
    life = build_lifecycle("T", hist, [{"date": "18/04/2023", "meeting": "3_202315",
                                        "text": "החלטה לסרב להקלה להגבהת גובה החניה", "reference": "633-0928358"}])
    types = [d.type for d in life.decisions]
    assert types == ["RELIEF_REJECTED", "RETURNED_FOR_CORRECTIONS", "APPLICATION_APPROVED"]
    assert life.final_status == "PERMIT_ISSUED" and life.decisions[0].subsequent_decision == "RETURNED_FOR_CORRECTIONS"
    assert life.decisions[0].rejected_component == "covered_parking.height"


# ------------------------------------------------------------------ blind dataset sanitization

def _dwf_with_markup() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.xml", '<dwf:Manifest><dwf:Resource role="markup object definition" href="s\\m.xml"/></dwf:Manifest>')
        z.writestr("s\\descriptor.xml", '<ePlot:Page><ePlot:Resource role="markup object definition" mime="text/xml" '
                   'href="s\\m.xml" objectId="1"/><ePlot:Resource role="markup private" href="s\\p.xml" objectId="2"/>'
                   '<ePlot:GraphicResource role="2d streaming graphics" href="s\\k.w2d" objectId="ABCD-1"/>'
                   '<ePlot:GraphicResource role="2d streaming graphics" href="s\\g.w2d" objectId="FFFF-2"/></ePlot:Page>')
        z.writestr("s\\m.xml", '<PageObjectDefinition><Property name="Label" value="יש לציין נימוק להקלה"/></PageObjectDefinition>')
        z.writestr("s\\p.xml", '<MarkupPrivate MarkupW2dId="ABCD-1"/>')
        z.writestr("s\\k.w2d", b"(W2D V06.00)markup")
        z.writestr("s\\g.w2d", b"(W2D V06.00)geometry")
    return b"(DWF V06.20)" + buf.getvalue()


def test_contaminated_dwf_markup_is_quarantined(tmp_path):
    case = tmp_path / "blind" / "CASE_1" / "cad_originals"
    case.mkdir(parents=True)
    src = case / "plan.dwf"
    src.write_bytes(_dwf_with_markup())
    before = src.read_bytes()
    s = BlindDatasetSanitizer(tmp_path / "out")
    rep = s.report(s.run(tmp_path / "blind"))
    f = rep["detail"][0]["files"][0]
    assert f["action"] == "QUARANTINED" and rep["contaminated_cases"] == ["CASE_1"]
    assert {x["type"] for x in f["findings"]} >= {"markup_resources", "markup_graphics_layer"}
    assert src.read_bytes() == before                                              # original untouched
    cand = Path(f["candidate"]).read_bytes()
    z = zipfile.ZipFile(io.BytesIO(cand[cand.find(b"PK"):]))
    assert "s\\g.w2d" in z.namelist() and not {"s\\m.xml", "s\\p.xml", "s\\k.w2d"} & set(z.namelist())
    assert "נימוק" not in str(rep)                                                 # the report holds no annotation text


def test_pdf_annotations_are_stripped_into_a_derivative(tmp_path):
    import pymupdf
    case = tmp_path / "blind" / "CASE_2"
    case.mkdir(parents=True)
    d = pymupdf.open()
    pg = d.new_page()
    pg.insert_text((72, 72), "Ground floor plan 1:100")
    pg.add_text_annot((100, 100), "reviewer note")
    d.save(case / "plan.pdf")
    s = BlindDatasetSanitizer(tmp_path / "out")
    f = s.report(s.run(tmp_path / "blind"))["detail"][0]["files"][0]
    assert f["action"] == "SANITIZED" and len(list(pymupdf.open(f["derivative"])[0].annots() or [])) == 0


def test_known_contaminated_case_is_flagged(tmp_path):
    (tmp_path / "blind" / "CASE_000094").mkdir(parents=True)
    s = BlindDatasetSanitizer(tmp_path / "out", {"CASE_000094": "reviewer information exposed during inspection"})
    assert s.report(s.run(tmp_path / "blind"))["contaminated_cases"] == ["CASE_000094"]


# ------------------------------------------------------------------ known-outcome case 20221189

def test_known_outcome_20221189():
    sys.path.insert(0, str(ROOT / "scripts"))
    ko = importlib.import_module("known_outcome")
    r = ko.run(ROOT / "validation/known_outcome/20221189")
    assert all(x["match"] for x in r["comparison"]), [x for x in r["comparison"] if not x["match"]]
    assert [x["outcome"] for x in r["reliefs"]] == ["MISSING_PLANNING_JUSTIFICATION"]
    assert not [x for x in r["reliefs"] if x["external"]]                         # nothing for the external report
    split = {c["topic"]: c for c in r["route_with_committee_split"]["checks"]}
    assert split["service_below"]["status"] == "WITHIN" and split["service_below"]["confirmable"] is False
    assert split["split_reconciliation"]["status"] == "NOT_CHECKED"                # 24.43 m² not assigned to a floor
    assert "<html lang=\"he\" dir=\"rtl\">" in ko.html_report(r)
