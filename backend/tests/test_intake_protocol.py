"""Committee-protocol parsing, classification, grounding and AI provider selection — on synthetic
text shaped like the real Complot export (no dependency on the real package)."""
import copy

import yaml

from app.ai.gateway import AIGateway, llm_to_extraction
from app.config import settings
from app.intake import classify as C
from app.intake import protocol as P
from app.intake import text as T
from app.intake.grounding import ground
from app.intake.schemas import ApplicationExtraction

ITEM = """BAKPIRUT00011
:סעיף11
 מספר בקשה :
201600156
 תיק ןי בני    :
61950349
פרוטוקול
  :ועדת משנה  ישיבה מספר20160084
  :בתאריך25/07/2016
 מבקש:
  פלוני אלמוני
 עורך:
  אדריכל בדיקה
וג ס בקשה:
  בקשה להיתר
 כתובת הבנ
י:ין
 ביאליק25
 בני ברק
 שטח :מגרש610.00 מ"ר
 גוש
 :וחלקה:  גוש6195
 :חלקה349
     יעוד: אזור מגורים ג
 מהות
:ופרוט הבקשה
תוספת
. סוכה לדירה בקומה ב' בבניין בן שלש קומות על הקרקע+ חדרי גג
שטחים:
קומה
 ב' קיים-
60.92
.מ"ר
קומת
 גג מוצע-
 חדרי גג35.0
  מדרגות+ מ"ר5.0
  סוכה+ מ"ר7.55
  מרפסת גג+ מ"ר13.37
מ."ר
 הערות
:מחלקת רישוי
9.
 תאום גמר חזיתות מול אגף ההנדסה.
10
. לסמן גובה מעקה.
:הערות מהנדס העיר
1.
.יש להתייחס לניקוז הגגות של חדרי הגג
 החלטה
לאשר
 בהערות מח' רשוי שבסעיפים1-5
 היתר
.יוצא ע"ג תכנית מתוקנת
אין בהחלטה זו כדי למנוע מהמתנגד למצות זכויותיו
"""


def parse(text=ITEM):
    return P.parse_application([(1, T.clean_page(text))], "t.pdf", "x" * 64, {1: 32})


def test_protocol_item_fields():
    e = parse()
    v = lambda f: getattr(e, f).value  # noqa: E731
    assert v("application_number") == "201600156" and v("building_file_number") == "61950349"
    assert v("address") == "ביאליק 25" and v("gush") == "6195" and v("helka") == "349"
    assert v("zone") == "אזור מגורים ג" and v("application_type") == "בקשה להיתר"
    assert v("plot_area_m2") == 610.0
    assert "תוספת סוכה לדירה בקומה ב'" in v("description")
    assert v("permit_type") == "roof_room_addition"                    # roof rooms outrank sukkah
    assert e.meeting_number == "20160084" and e.meeting_date == "2016-07-25" and e.item_number == "11"
    assert e.application_number.source.page == 1 and e.application_number.source.original_page == 32
    assert "פלוני" not in str(e.model_dump())                           # applicant name never extracted


def test_protocol_areas_comments_decision():
    e = parse()
    areas = {(a.label, a.value_m2, a.status) for a in e.areas}
    assert ("חדרי גג", 35.0, "proposed") in areas and ("מרפסת גג", 13.37, "proposed") in areas
    assert any(a.value_m2 == 60.92 and a.status == "existing" for a in e.areas)
    lic = [c for c in e.comments if c.department == "licensing_department"]
    assert [c.item_no for c in lic] == ["9", "10"] and lic[1].text == "לסמן גובה מעקה."
    assert any(c.department == "city_engineer" for c in e.comments)
    assert e.decision.outcome == "approved_with_conditions"
    assert e.decision.text.startswith("לאשר") and "בהחלטה" not in e.decision.text[:20]


def test_decision_label_not_taken_from_bhachlata():
    e = parse(ITEM.replace(" החלטה\nלאשר", " ההחלטה_הוסרה\nלאשר"))
    assert e.decision is None and "לא נמצאה החלטת ועדה" in " ".join(e.warnings)


def test_split_items_separates_applications_and_plans():
    pages = ["front matter", "TBPIRUT00001\nתכנית 501-0330134", "המשך", "BAKPIRUT00001\nמספר בקשה: 1", "BAKPIRUT00002\nמספר בקשה: 2", "המשך 2"]
    items, front = P.split_items(pages)
    assert front == [1]
    assert items == [("planning", [2, 3]), ("application", [4]), ("application", [5, 6])]


def test_classification_by_content():
    proto = C.classify_pdf([ITEM])
    assert proto.doc_class == "committee_protocol" and proto.confidence > 0.7
    form = C.classify_pdf(["טופס בקשה להיתר בנייה\nגוש: 1 חלקה: 2\nמהות הבקשה: תוספת\nחתימת המבקש"])
    assert form.doc_class == "permit_application"
    plan = C.classify_pdf(["הוראות התכנית\nמטרות התכנית\nתכנית מפורטת 501-0330134"])
    assert plan.doc_class == "planning_regulation"
    assert C.classify_file("index.csv", "csv", table_header=["סעיף", "מספר בקשה", "קובץ"]).doc_class == "metadata_index"
    assert C.classify_file("a.dxf", "dxf").doc_class == "architectural_drawing"
    # file name alone does not decide: a protocol named like a form is still a protocol
    assert C.classify_file("application_form.pdf", "pdf", [ITEM]).doc_class == "committee_protocol"


def test_grounding_drops_invented_values():
    payload = {"pages": [(1, T.clean_page(ITEM))], "file": "t.pdf", "sha": None}
    fake_llm = {"application_number": {"value": "201600156", "page": 1}, "address": {"value": "הרצל 99", "page": 1},
                "gush": {"value": "6195"}, "comments": [{"department_he": "מהנדס העיר", "text": "להגיש תצהיר מהנדס קונסטרוקציה"}],
                "decision": {"text": "לאשר בהערות מח' רשוי שבסעיפים1-5"}}
    e = ApplicationExtraction.model_validate(llm_to_extraction(fake_llm, payload, "fake-llm"))
    e, dropped = ground(e, ITEM)
    assert e.application_number.value == "201600156" and e.gush.value == "6195"
    assert e.address is None and "address" in dropped                    # "הרצל 99" is not in the document
    assert e.comments == [] and e.decision is not None


def _gw(mutate=None, impl=None):
    pol = yaml.safe_load((settings.knowledge_dir / "ai_policy.yaml").read_text(encoding="utf-8"))
    pol = copy.deepcopy(pol)
    if mutate:
        mutate(pol)
    return AIGateway(policy=pol, implementations=impl or {})


def test_extraction_provider_selection_local_by_default():
    res = _gw().route("Extraction", "CASE_DOCUMENT", {"kind": "protocol_item", "pages": [(1, T.clean_page(ITEM))], "file": "t.pdf"})
    assert res.outcome == "OK" and res.provider_id == "local_rules"


def test_extraction_cloud_never_used_for_case_documents():
    called = []

    def m(p):
        p["providers"]["cloud_llm_il"].update(approved=True, enabled=True)
        p["policies"] = [x for x in p["policies"] if x["task"] != "Extraction"] + [
            {"task": "Extraction", "data_class": "CASE_DOCUMENT", "mode": "CLOUD", "providers": ["cloud_llm_il", "local_rules"]},
            {"task": "Extraction", "data_class": "PUBLIC_REGULATION", "mode": "HYBRID", "providers": ["cloud_llm_il", "local_rules"]}]
    gw = _gw(m, {"cloud_llm_il": lambda t, p, c: called.append(1) or {"pages": [1]}})
    case = gw.route("Extraction", "CASE_DOCUMENT", {"kind": "protocol_item", "pages": [(1, ITEM)], "file": "t.pdf"})
    assert case.provider_id == "local_rules" and not called                # residency rule beats the policy order
    public = gw.route("Extraction", "PUBLIC_REGULATION", {"kind": "protocol_item", "pages": [(1, ITEM)], "file": "t.pdf"})
    assert public.provider_id == "cloud_llm_il" and called                 # allowed for public planning documents


def test_local_llm_selected_when_enabled_and_first():
    def m(p):
        p["providers"]["local_ollama"]["enabled"] = True
        for x in p["policies"]:
            if x["task"] == "Extraction" and x["data_class"] == "CASE_DOCUMENT":
                x["providers"] = ["local_ollama", "local_rules"]
    gw = _gw(m, {"local_ollama": lambda t, p, c: llm_to_extraction({"gush": {"value": "6195"}}, p, "ollama:test")})
    res = gw.route("Extraction", "CASE_DOCUMENT", {"kind": "protocol_item", "pages": [(1, ITEM)], "file": "t.pdf"})
    assert res.provider_id == "local_ollama" and res.output["gush"]["source"]["provider"] == "ollama:test"
