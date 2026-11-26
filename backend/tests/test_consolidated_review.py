"""Consolidated review update: area geometry (sources A/B), historical permit reconciliation, licensing stages and
review statuses, final decision, land parcel, Mekorot, screening, the external defects report (PDF / Word)."""
import importlib.util
import io
import zipfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import services as S
from app.defects_report import build_defects, render_defects_pdf
from app.rules import evidence as E

from .test_evidence import pdf
from .test_lot_ledger import ROWS, table

AGENT = Path(__file__).resolve().parents[2] / "agent"
spec = importlib.util.spec_from_file_location("area_geometry", AGENT / "area_geometry.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
ZIKIM = Path.home() / "Downloads/10000612352/PERMIT 319-320-hagasha20261111.dwfx"


# ---------------------------------------------------------------- geometry (B) and classification

def test_protected_room_beyond_9_net_is_primary():
    d = [{"area_m2": {"primary": 109.73, "protected_room_floor": 9.9, "protected_room_walls": 4.14, "covered_service": 49.48}},
         {"area_m2": {"primary": 72.42, "open_uncounted": 16.22}}]
    t = G.classify(d)
    assert t["primary"] == pytest.approx(109.73 + 72.42 + 0.9) and t["service"] == pytest.approx(9.0 + 4.14 + 49.48)
    assert t["uncounted"] == pytest.approx(16.22) and t["total"] == pytest.approx(t["primary"] + t["service"])


def test_table_strip_vs_diagram():
    from shapely.geometry import box, Polygon
    assert G._is_strip(box(0, 0, 100, 10), [])
    assert not G._is_strip(Polygon([(0, 0), (50, 0), (50, 20), (30, 20), (30, 40), (0, 40)]), [])


@pytest.mark.skipif(not ZIKIM.exists(), reason="Zikim plan not on this machine")
def test_zikim_regression_area_diagrams():
    """Application 10000612352-1: the diagrams measured independently (scale from the package, not from totals)."""
    g = G.measure(ZIKIM)
    t = g["totals"]
    assert g["diagram_count"] == 4 and g["sheets"][-1]["model_unit"] == "cm"
    assert abs(t["primary"] - 366.10) < 0.02 and abs(t["service"] - 125.24) < 0.02 and abs(t["total"] - 491.34) < 0.02
    assert t["protected_room_walls"] == pytest.approx(8.278, abs=0.002) and t["covered_service"] == pytest.approx(98.969, abs=0.002)
    assert all(not d["overlaps"] and not d["double_counted_m2"] for s in g["sheets"] for d in s["diagrams"])
    assert sum(1 for s in g["sheets"] for d in s["diagrams"] if d.get("same_as")) == 2      # two mirrored/copied units


def _geom(primary=366.10, overlaps=()):
    diag = {"sheet": 5, "area_m2": {"primary": primary / 2 - 0.9, "protected_room_floor": 9.9, "protected_room_walls": 4.139,
                                    "covered_service": 49.4845}, "overlaps": list(overlaps), "double_counted_m2": {}}
    diags = [diag, dict(diag)]
    return {"algorithm": G.ALGORITHM, "file_sha256": "x", "sheets": [{"sheet": 5, "model_unit": "cm", "diagrams": diags}],
            "totals": G.classify(diags)}


def test_declared_vs_diagrams():
    ctx = E.Context([], {"main_area_m2": 366.10, "service_area_m2": 125.24}, "", "368", {}, [],
                    {"file": "plan.dwfx", "area_geometry": _geom()})
    r = E.r_area_diagrams(ctx)
    assert r.status == "PASS" and "מקור ג׳" in r.explanation_he           # C not performed is always said
    wrong = E.Context([], {"main_area_m2": 380.00, "service_area_m2": 125.24}, "", "368", {}, [],
                      {"file": "plan.dwfx", "area_geometry": _geom()})
    r = E.r_area_diagrams(wrong)
    assert r.status == "FAIL" and any(i["review"] == "CONFIRMED_DEFECT" and "עיקרי" in i["title_he"] for i in r.items)
    dup = E.Context([], {"main_area_m2": 366.10, "service_area_m2": 125.24}, "", "368", {}, [],
                    {"file": "plan.dwfx", "area_geometry": _geom(overlaps=[{"a": "primary", "b": "covered_service", "m2": 3.2}])})
    assert any("חופפים" in i["title_he"] for i in E.r_area_diagrams(dup).items)


def test_protected_room_classification_is_internal():
    ctx = E.Context([], {"main_area_m2": 366.10, "service_area_m2": 125.24}, "", "368", {}, [],
                    {"file": "plan.dwfx", "area_geometry": _geom()})
    it = [i for i in E.r_area_diagrams(ctx).items if "ממ\"ד" in i["title_he"]]
    assert it and it[0]["review"] == "UNRESOLVED" and it[0]["internal"]     # 14.04 gross > 12.5: not a defect


# ---------------------------------------------------------------- historical permits

PERMITS = {"permits": [
    {"permit": "20210501", "building": "112", "document": "295766", "document_sha256": "a", "source_url": "u",
     "table": {"primary_existing": "265.70", "primary_added": "13.44", "primary_total": "279.14", "service_total_stated": "179.35",
               "service_components_sum": "170.14", "building_total": "449.28"},
     "arithmetic": [{"check": "s", "result": "179.35 ≠ 170.14 (9.21)", "closes": False}]},
    {"permit": "20210495", "building": "114", "document": "295961", "document_sha256": "b", "source_url": "u",
     "table": {"primary_existing": "273.76", "primary_added": "0.00", "primary_total": "273.76", "service_total_stated": "104.38",
               "service_components_sum": "103.76", "building_total": "378.14"}, "arithmetic": []},
    {"permit": "1", "building": "301-302", "document": "1", "document_sha256": "c", "source_url": "u",
     "table": {"primary_existing": "400.00", "primary_added": "0", "primary_total": "400.00", "service_total_stated": "100.00",
               "service_components_sum": "100.00", "building_total": "500.00"}, "arithmetic": []}]}


def test_outdated_historical_value_is_a_defect_other_gap_a_discrepancy(tmp_path, monkeypatch):
    rows = ROWS + [["445.05", "0.1%", "179.35", "0.3%", "265.70", "2", "368", "112"],
                   ["391.49", "0.1%", "107.14", "0.3%", "284.35", "2", "368", "114"]]
    docs = E.load_docs([table(tmp_path, rows, ("2436.54", "586.49", "1850.05", "10"))])
    monkeypatch.setattr(E, "load_permits", lambda g, c: PERMITS)
    r = E.r_permit_history(E.Context(docs, {}, "", "368", {}, [], {}, "2832"))
    by = {i["title_he"]: i for i in r.items}
    b112 = next(i for t, i in by.items() if "112" in t)
    b114 = next(i for t, i in by.items() if "114" in t)
    assert b112["review"] == "CONFIRMED_DEFECT" and "265.70" in b112["found_he"] and "279.14" in b112["found_he"]
    assert "13.44" in b112["found_he"] and "179.35 ≠ 170.14" in b112["found_he"]
    assert b114["review"] == "DOCUMENTED_DISCREPANCY" and "+13.35" in b114["diff"]
    assert not any("301-302" in t for t in by)                               # a matching building is not reported


# ---------------------------------------------------------------- stages, statuses, decision

def _r(rule_id, flags=(), evidence=()):
    return SimpleNamespace(rule_id=rule_id, flags=list(flags), evidence=list(evidence))


def _rule(**raw):
    return SimpleNamespace(raw=raw, severity=raw.get("severity", "medium"))


def test_future_stage_requirement_is_not_a_current_defect():
    assert S.review_status(_rule(licensing_stage="DESIGN_CONTROL"), _r("HFC"), "MISSING", "SPATIAL_REVIEW") == "FUTURE_STAGE"
    assert S.review_status(_rule(licensing_stage="DESIGN_CONTROL"), _r("HFC"), "MISSING", "DESIGN_CONTROL") == "CONFIRMED_DEFECT"
    assert S.review_status(_rule(), _r("X"), "CONFLICT", "SPATIAL_REVIEW") == "DOCUMENTED_DISCREPANCY"
    assert S.review_status(_rule(), _r("X", ["NEEDS_DRAWING_READ"]), "OPEN", "SPATIAL_REVIEW") == "NOT_CHECKED"
    assert S.review_status(_rule(), _r("X", ["REVIEW:UNRESOLVED"]), "OPEN", "SPATIAL_REVIEW") == "UNRESOLVED"
    assert S.review_status(_rule(), _r("X"), "OK", "SPATIAL_REVIEW") == "PASS"


def test_stage_from_register_or_declared():
    case = SimpleNamespace(declared={})
    assert S.licensing_stage(case, "בקרה מרחבית לא תקינה")[0] == "SPATIAL_REVIEW"
    assert S.licensing_stage(SimpleNamespace(declared={"licensing_stage": "DESIGN_CONTROL"}), None)[0] == "DESIGN_CONTROL"
    assert S.licensing_stage(case, None)[0] == "SPATIAL_REVIEW"


def test_decision_engine():
    by = {"A": _rule(severity="high"), "B": _rule(severity="high", reject_basis=True), "C": _rule(severity="high")}
    full = {"full_compliance_possible": True, "open": []}
    assert S.final_decision([_r("A", ["STATUS_PASS"])], by, full)[0] == "NO_DEFECTS_IDENTIFIED"
    # V9: one passing check is not compliance — without the required-check inventory complete, no final "no defects"
    assert S.final_decision([_r("A", ["STATUS_PASS"])], by)[0] == "INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION"
    assert S.final_decision([_r("C", ["STATUS_NOT_CHECKED"])], by)[0] == "INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION"
    assert S.final_decision([_r("A", ["STATUS_CONFIRMED_DEFECT", "EXTERNAL"])], by)[0] == "RETURN_FOR_CORRECTIONS"
    assert S.final_decision([_r("B", ["STATUS_CONFIRMED_DEFECT", "EXTERNAL"])], by)[0] == "REJECT_RECOMMENDATION"
    # the official register status never decides: it is internal, so it adds nothing
    assert S.final_decision([_r("A", ["STATUS_DOCUMENTED_DISCREPANCY", "INTERNAL"])], by, full)[0] == "NO_DEFECTS_IDENTIFIED"


def test_register_status_stays_internal(monkeypatch):
    monkeypatch.setattr(E, "load_ledger", lambda g, c: {"records": [
        {"application_id": "20260611", "units": [319, 320], "status": "בקרה מרחבית לא תקינה", "source_url": "u"}]})
    r = E.r_registry_status(E.Context([], {"description": "יחידות 320 -319"}, "", "368", {}, [], {}, "2832"))
    assert r.internal and r.status == "FAIL"


def test_unrelated_misfiled_register_record_is_not_an_item(tmp_path, monkeypatch):
    docs = E.load_docs([table(tmp_path, ROWS, ("1600.00", "300.00", "1300.00", "6"))])
    monkeypatch.setattr(E, "load_ledger", lambda g, c: {"records": [
        {"application_id": "3", "role": "new_dwelling", "units": [335, 336], "primary_m2": "600.00", "service_m2": None,
         "flags": ["total_in_primary"]}]})
    r = E.r_table_vs_registry(E.Context(docs, {}, "", "368", {}, [], {}, "2832"))
    assert r.status == "PASS" and not r.items                               # a register mapping error, not a defect


# ---------------------------------------------------------------- documents: land, RMI, Mekorot

def test_land_parcel_extract_mismatch(tmp_path):
    """Text as the real Rishui Zamin form extracts (file names printed reversed: 'pdf.28 חלקה2832 גוש')."""
    text = ("פרטי הקרקע | זיקים ישוב / ועדה | 0 :תת גוש2832 :גוש27 :חלקה:תת חלקה\n"
            "נסח טאבו | (2) קבצים מצורפים | pdf.27  חלקה2832 גוש | pdf.28  חלקה2832 גוש\n"
            "צירוף נסח רישום מקרקעין / הוכחת בעלות | נסחי רשום מקרקעין | (1) קבצים מצורפים | pdf.28  חלקה2832 גוש")
    form = E.Doc("form.pdf", "application_form", [text], tmp_path / "form.pdf")
    r = E.r_land_parcel(E.Context([form], {}, "", "368", {}, []))
    assert r.status == "FAIL" and r.review == "DOCUMENTED_DISCREPANCY" and "גוש 2832 חלקה 28" in r.explanation_he
    ok = E.Doc("form.pdf", "application_form", [text.replace("הוכחת בעלות | נסחי רשום מקרקעין | (1) קבצים מצורפים | pdf.28",
                                                            "הוכחת בעלות | נסחי רשום מקרקעין | (1) קבצים מצורפים | pdf.27")],
               tmp_path / "form.pdf")
    assert E.r_land_parcel(E.Context([ok], {}, "", "368", {}, [])).status == "PASS"


def test_rmi_consent_is_future_stage(tmp_path):
    d = E.load_docs([pdf(tmp_path, "rami.pdf", ["בשלב זה רמ\"י אינה נותנת את הסכמתה למתן ההיתר",
                                                "לאחר קבלת החלטת ועדת התכנון המוסמכת"])])
    r = E.r_rmi_consent(E.Context(d, {}, "", "368", {}, []))
    assert r.review == "FUTURE_STAGE"


def test_mekorot_response_without_lines(tmp_path):
    d = E.load_docs([pdf(tmp_path, "mekorot.pdf", ["פריטי רשת המים", "ארז שקמה7 3302035 רדיוס מגן ב 89",
                                                   "ארז שקמה8 3302036 רדיוס מגן ג 167", "מכתב זה בתוקף עד ליום24/05/2027"])])
    r = E.r_mekorot_lines(E.Context(d, {}, "", "368", {}, []))
    assert r.status == "PASS" and "אינה מפרטת קווי מקורות" in r.explanation_he


def test_screening_from_image_model_never_a_defect():
    ctx = E.Context([], {}, "", "368", {}, [], {"file": "p.dwfx", "screening": {"exposed": [{"sheet": 6, "tile": 4}], "screened": []}})
    r = E.r_tech_screening(ctx)
    assert r.status == "UNCERTAIN" and r.internal and r.review == "UNRESOLVED"


# ---------------------------------------------------------------- the external defects report

def _finding(rule_id, flags, explanation="", evidence=(), severity="medium", fix=None, title="נושא"):
    return SimpleNamespace(id=rule_id, rule_id=rule_id, flags=flags, explanation_he=explanation, evidence=list(evidence),
                           severity=severity, fix_hint_he=fix, title_he=title, citations=[{"title_he": "תכנית — x", "section": "4.1"}])


def _run(findings, decision="RETURN_FOR_CORRECTIONS"):
    import datetime as dt
    return SimpleNamespace(version=3, started_at=dt.datetime(2026, 11, 25), input_hashes=[{}] * 34, findings=findings,
                           summary={"review": {"decision": decision, "stage_he": "בקרה מרחבית", "counts": {"NOT_CHECKED": 2}}})


CASE = SimpleNamespace(tenant_id="hof-ashkelon", case_number="10000612352-1", title="קיבוץ זיקים", gush="2832", helka="27", address="", applicable_plans=["633-0723718"])


def test_defects_report_has_only_external_items_defects_first():
    item = {"type": "item", "review": "CONFIRMED_DEFECT", "title_he": "טעות בטבלת ניצול זכויות הבנייה — מבנה 112",
            "found_he": "265.70 מול 279.14", "diff": "13.44", "correction_he": "לעדכן", "evidence": []}
    internal_item = {"type": "item", "review": "UNRESOLVED", "internal": True, "title_he": "סיווג ממ\"ד", "found_he": "x"}
    fs = [_finding("D", ["STATUS_DOCUMENTED_DISCREPANCY", "EXTERNAL"], "פער", title="פער בחלקה"),
          _finding("H", ["STATUS_CONFIRMED_DEFECT", "EXTERNAL"], evidence=[item, internal_item], severity="high"),
          _finding("P", ["STATUS_PASS"], "תקין"), _finding("F", ["STATUS_FUTURE_STAGE"], "פיקוד העורף"),
          _finding("I", ["STATUS_DOCUMENTED_DISCREPANCY", "INTERNAL"], "סטטוס במאגר")]
    rep = build_defects(CASE, _run(fs))
    assert rep["title"] == "דוח ליקויים – בקשה להיתר מס׳ 10000612352-1"
    assert [i["title"] for i in rep["items"]] == ["טעות בטבלת ניצול זכויות הבנייה — מבנה 112", "פער בחלקה"]
    assert [i["no"] for i in rep["items"]] == ["01", "02"] and rep["decision_he"] == "החזרה לתיקון ולהשלמה"
    assert "2 בדיקות לא הושלמו" in rep["limitations_he"]


def test_defects_report_no_defects_does_not_claim_compliance():
    rep = build_defects(CASE, _run([_finding("P", ["STATUS_PASS"])], "INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION"))
    assert not rep["items"] and rep["decision_he"] == "אין די ראיות להמלצה סופית" and "אין לראות בהשמטת נושא" in rep["limitations_he"]


def test_defects_report_pdf_rtl():
    import pymupdf
    item = {"type": "item", "review": "CONFIRMED_DEFECT", "title_he": "טעות בטבלה", "found_he": "265.70 מול 279.14",
            "diff": "13.44 מ\"ר", "correction_he": "לעדכן את המאזן", "evidence": [{"type": "document", "file": "היתר 20210501", "quote": "x"}]}
    rep = build_defects(CASE, _run([_finding("H", ["STATUS_CONFIRMED_DEFECT", "EXTERNAL"], evidence=[item])]))
    text = "".join(p.get_text() for p in pymupdf.open(stream=render_defects_pdf(rep), filetype="pdf"))
    assert "13.44" in text and "10000612352-1" in text
