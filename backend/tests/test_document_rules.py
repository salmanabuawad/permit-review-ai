"""Document-content rules added after the review of Beit Shemesh application 10000197313.

School for boys on plot 201 (block 34581 parcel 21), submitted 31/08/2022. The committee's
preconditions asked for, among others, an Antiquities Authority approval "and not a payment demand"
and an electric-company approval; the package had 15 "יישלח בהמשך.pdf" placeholders, a HOT letter for
plot 207 (block 34582) filed as the electric-company approval, and an IAA supervision demand.
Text fixtures below are the pymupdf text of the real files (shortened).
"""
import copy

import pymupdf
import pytest

from app.batch_import import guess_doc_type
from app.config import settings
from app.knowledge import load_sources
from app.rules.derived import derive_document_facts
from app.rules.doc_signals import block_numbers, document_signals
from app.rules.engine import Rule, evaluate_rule, load_rules, validate_rule

RULES = {r.id: r for r in load_rules([settings.knowledge_dir / "rules" / "internal_qa.yaml"])}
SRC = load_sources()
NEW = ["QA-DOC-PLACEHOLDER", "QA-APPROVAL-PARCEL-MISMATCH", "QA-APPROVAL-ISSUER-MISMATCH",
       "QA-IAA-DEMAND-NOT-APPROVAL", "QA-LICENCE-EXPIRED"]
REF = "2022-08-31"

HOT_TEXT = """20/7/2022
)תוקף שלוש שנים(
המלצה להיתר בניה256502
לכבוד
הוועדה המקומית לתכנון ובנייה
בית שמש
פרטי היזם / קבלן
טלפון0523209000
עוסק מורשה / ת.ז516327772
פרטי מבנה
גוש
חלקה
מגרש
34582
52
207
,מבנה ספרייה ומועדון נוער 3קומות,חלקה 52
המגרש במקביל לצנרת עבור חברת בזק.
2. יש להכין תשתיות וגומחה עבור ארון HOT
מחלקת תכנון, הוט יקום
http://hot-gis-01/DWMS_BOM/Design/Print/PermitPrint.aspx?ID=256502"""

IAA_TEXT = """www.antiquities.org.il
25/10/2021
סימוכין :
499764
מס' פעילות:
297455
הנדון :
 דרישת
פיקוח באתר עתיקות
 שכונה ד5 בבית שמש
  לא פורסם22278
/0
 נחל האלה ;
27232
/0 "שריעה ,ח 'אל-
 אלא באישור מוקדם מאת רשות העתיקות ובהתאם לתנאי האישור
 מתנה רשות העתיקות את מתן
 האישור בכך שבמשך כל זמן ביצוע עבודות
 עליכם לשאת
בעלות הפיקוח סך
1,550
הידועים כגוש"ח או נ.צ: 624200 196100 623200 ,195100"""

FORM_TEXT = "בקשה להיתר בנייה מס' 10000197313-1\n:תת\xa0גוש34581\xa0:גוש21\xa0:חלקה:תת\xa0חלקה\nבנייני ציבור"
NESACH_TEXT = "העתק רישום מפנקס הזכויות\nגוש: 34581 חלקה: 21\nעיריית בית שמש 7,435.00\nהערה בדבר אתר עתיקות"
LICENCE_TEXT = "רישיון מהנדס/ת / אדריכל/ית\nשם: אלי אליקים\nמספר רישיון 79076\nבתוקף עד 31/03/2021"
RECEIPT_TEXT = "אגרה שנתית - מהנדסים ואדריכלים\nאישור תשלום\nתאריך ההזמנה : 03/03/2022 10:05:19\nסך הכל: 195.00"


def f(filename, doc_type, text):
    return {"filename": filename, "doc_type": doc_type, "doc_label_he": None,
            "signals": document_signals(filename, text)}


def facts(derived):
    return {"case": {"permit_type": "new_building", "stage": "permit_request", "reference_date": REF},
            "declared": {}, "docs": {"present": {}}, "facts_derived": derived, "measure": {}}


def run(rule_id, derived, binding=False):
    r = RULES[rule_id]
    if binding:
        r = Rule(copy.deepcopy(r.raw))
        r.raw["review_state"] = "PROFESSIONALLY_APPROVED"
    return evaluate_rule(r, facts(derived), SRC, False)


def test_new_rules_are_valid_and_cite_registered_sources():
    for rid in NEW:
        raw = RULES[rid].raw
        assert validate_rule(raw) == [], rid
        assert raw["report"] == "completeness"
        assert raw["sources"] and all(s["source_id"] in SRC for s in raw["sources"]), rid


# ------------------------------------------------------------------ signals
@pytest.mark.parametrize("name", ["יישלח בהמשך.pdf", "יישלח בהמשך_23.pdf", "ישלח-בהמשך.pdf", "יוגש בהמשך.pdf"])
def test_placeholder_by_filename(name):
    assert document_signals(name, None)["placeholder"] is True


def test_placeholder_by_short_text_but_not_by_a_real_letter_mentioning_it():
    assert document_signals("x.pdf", "יישלח בהמשך")["placeholder"] is True
    long_letter = "אישור מחלקת תנועה. " * 20 + "תכנית מפורטת יישלח בהמשך"
    assert document_signals("x.pdf", long_letter)["placeholder"] is False
    assert document_signals("נסח טאבו.pdf", NESACH_TEXT)["placeholder"] is False


def test_block_read_after_label_only():
    assert block_numbers(HOT_TEXT) == ["34582"]                  # label and value on different lines
    assert block_numbers(FORM_TEXT) == ["34581"]                 # visual-order form, digits glued to label
    assert block_numbers(NESACH_TEXT) == ["34581"]
    assert block_numbers(IAA_TEXT) == []                         # site numbers / coordinates are not blocks
    assert block_numbers("גוש 2022 חלקה 5") == []                # a year is not a block


def test_issuers_and_iaa_demand():
    hot, iaa = document_signals("256502-text.pdf", HOT_TEXT), document_signals("עתיקות.pdf", IAA_TEXT)
    assert set(hot["issuers"]) == {"hot", "bezeq"} and hot["iaa_demand"] is False
    assert iaa["issuers"] == ["iaa"] and iaa["iaa_demand"] is True


def test_licence_and_fee_receipt_dates():
    assert document_signals("רישיון.pdf", LICENCE_TEXT)["license_valid_until"] == "2021-03-31"
    assert document_signals("תשלום.pdf", RECEIPT_TEXT)["fee_receipt_date"] == "2022-03-03"


def test_scanned_file_gives_no_content_signal():
    assert document_signals("אישור היתר בניה בזק-207.pdf", "") == {"has_text": False, "placeholder": False}


# ------------------------------------------------------------------ the 10000197313 package
PACKAGE = [f("10000197313.pdf", "application_form", FORM_TEXT),
           f("נסח טאבו למרש 201.pdf", "other", NESACH_TEXT),
           f("256502-text.pdf", "electric_company_approval", HOT_TEXT),
           f("אישור היתר בניה בזק-207.pdf", "electric_company_approval", ""),     # scan
           f("דרישת תשלום עתיקות לא אישור.pdf", "antiquities_approval", IAA_TEXT),
           f("יישלח בהמשך.pdf", "other", None), f("יישלח בהמשך_2.pdf", "other", None)]


def test_package_10000197313_findings():
    d = derive_document_facts(PACKAGE, "34581", REF)
    assert len(d["placeholder_docs"]) == 2
    assert d["foreign_parcel_docs"] == ["256502-text.pdf (electric_company_approval): גוש 34582"]
    assert len(d["issuer_mismatch_docs"]) == 1 and "חברת החשמל" in d["issuer_mismatch_docs"][0]
    assert d["antiquities_demand_docs"] == ["דרישת תשלום עתיקות לא אישור.pdf (antiquities_approval)"]
    assert "expired_licence_docs" not in d                       # no licence with a text layer

    for rid in ("QA-DOC-PLACEHOLDER", "QA-APPROVAL-PARCEL-MISMATCH", "QA-APPROVAL-ISSUER-MISMATCH"):
        res = run(rid, d)
        assert res.status == "FAIL", rid                           # internal QA: shown as found
    assert "256502-text.pdf" in run("QA-APPROVAL-PARCEL-MISMATCH", d).explanation_he
    iaa = run("QA-IAA-DEMAND-NOT-APPROVAL", d)
    assert (iaa.computed_result, iaa.status) == ("FAIL", "UNCERTAIN") and "RULE_NOT_APPROVED" in iaa.flags
    assert run("QA-IAA-DEMAND-NOT-APPROVAL", d, binding=True).status == "FAIL"
    assert run("QA-LICENCE-EXPIRED", d).status == "NA"


def test_clean_package_passes():
    good = [f("10000197313.pdf", "application_form", FORM_TEXT), f("נסח.pdf", "other", NESACH_TEXT),
            f("אישור חברת החשמל.pdf", "electric_company_approval", "חברת החשמל לישראל\nגוש 34581 חלקה 21\nמאושר"),
            f("אישור רשות העתיקות.pdf", "antiquities_approval", "רשות העתיקות\nמאושר — חתימה על התכנית\nגוש 34581")]
    d = derive_document_facts(good, "34581", REF)
    for rid in NEW[:4]:
        assert run(rid, d).status == "PASS", rid


def test_expired_licence_unless_a_later_fee_receipt():
    lic = f("רישיון אלי אליקים 2020.pdf", "professional_license", LICENCE_TEXT)
    d = derive_document_facts([lic], "34581", REF)
    assert run("QA-LICENCE-EXPIRED", d, binding=True).status == "FAIL"
    d = derive_document_facts([lic, f("תשלום רישיון אלי 2022.pdf", "professional_license", RECEIPT_TEXT)], "34581", REF)
    assert run("QA-LICENCE-EXPIRED", d, binding=True).status == "PASS"


def test_rules_silent_without_signals_or_block():
    assert derive_document_facts([{"filename": "old.pdf", "doc_type": "other"}], "34581", REF) == {}
    d = derive_document_facts(PACKAGE, None, REF)
    assert "foreign_parcel_docs" not in d
    assert run("QA-APPROVAL-PARCEL-MISMATCH", d).status == "NA"
    assert run("QA-DOC-PLACEHOLDER", {}).status == "NA"


@pytest.mark.parametrize("name,expected", [("דרישת תשלום עתיקות לא אישור.pdf", "antiquities_approval"),
                                           ("אישור חברת חשמל טרפו.pdf", "electric_company_approval"),
                                           ("רשיון שמואל רבין 2023.pdf", "professional_license"),
                                           ("רישיון אלי אליקים 2020.pdf", "professional_license")])
def test_filename_hints(name, expected):
    assert guess_doc_type(name, "pdf", "", None)[0] == expected


# ------------------------------------------------------------------ through upload and run (API)
def _pdf(html: str) -> bytes:
    d = pymupdf.open()
    d.new_page().insert_htmlbox(pymupdf.Rect(40, 40, 560, 800), html)
    return d.tobytes()


def test_upload_and_run_flags_package(tmp_path):
    from pathlib import Path
    if not Path(settings.pdf_font).exists():
        pytest.skip("no Hebrew font for generating test PDFs")
    from fastapi.testclient import TestClient

    from app.main import app
    from app.seed import seed

    seed(reset=True)
    H = {"X-User": "u-secretary"}
    with TestClient(app) as c:
        r = c.post("/api/cases", headers=H, json={"case_number": "BS-10000197313", "title": "בית ספר לבנים מגרש 201",
                                                    "permit_type": "addition_extension", "gush": "34581", "helka": "21"})
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        uploads = [("יישלח בהמשך.pdf", "survey_map", _pdf("<p>יישלח בהמשך</p>")),
                   ("256502-text.pdf", "electric_company_approval",
                    _pdf('<p dir="rtl">המלצה להיתר בניה — HOT</p><p dir="rtl">גוש 34582 חלקה 52 מגרש 207</p>')),
                   ("עתיקות.pdf", "antiquities_approval",
                    _pdf('<p dir="rtl">רשות העתיקות</p><p dir="rtl">הנדון: דרישת פיקוח באתר עתיקות</p>'))]
        for name, dt_, data in uploads:
            up = c.post(f"/api/cases/{cid}/files", headers=H, files={"file": (name, data)}, data={"doc_type": dt_})
            assert up.status_code == 200, up.text
        run_ = c.post(f"/api/cases/{cid}/run", headers={"X-User": "u-reviewer"}).json()
        rep = c.get(f"/api/runs/{run_['run_id']}/report/completeness", headers={"X-User": "u-reviewer"}).json()
    by = {x["rule_id"]: x for x in rep["findings"]}
    assert by["QA-DOC-PLACEHOLDER"]["status"] == "FAIL"
    assert by["QA-REQ-SURVEY"]["computed_result"] == "FAIL"      # the placeholder does not count as a survey map
    assert by["QA-APPROVAL-PARCEL-MISMATCH"]["status"] == "FAIL"
    assert by["QA-APPROVAL-ISSUER-MISMATCH"]["status"] == "FAIL"
    assert by["QA-IAA-DEMAND-NOT-APPROVAL"]["computed_result"] == "FAIL"
