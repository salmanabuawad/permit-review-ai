"""The evidence stage answers open findings from the case's documents, with file, page and quote."""
from types import SimpleNamespace

import pymupdf

from app.rules import evidence as E

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def stored(s: str) -> str:
    """Hebrew as PDFs store it (visual order): MuPDF reverses it back to reading order on extraction."""
    import re
    return s[::-1] if re.search(r"[\u0590-\u05ff]", s) else s


def pdf(tmp_path, name, lines, table=None):
    d = pymupdf.open()
    p = d.new_page(width=600, height=800)
    y = 60
    for ln in lines:
        p.insert_text((40, y), stored(ln), fontfile=FONT, fontname="F0", fontsize=10)
        y += 18
    if table:   # header row and totals row; columns placed by x
        for row in table:
            y += 18
            for x, cell in row:
                p.insert_text((x, y), stored(cell), fontfile=FONT, fontname="F0", fontsize=10)
    path = tmp_path / name
    d.save(str(path))
    return SimpleNamespace(kind="pdf", storage_path=str(path), filename=name, doc_type="other", ingest_report={})


def test_area_table_totals_are_read_by_column(tmp_path):
    f = pdf(tmp_path, "areas.pdf", ["סהכ שטח - משטח מגרש 368 שהוא 81033 מ\"ר"], table=[
        [(40, "סה\"כ"), (120, "אחוז משירות"), (220, "שירות"), (300, "אחוז מעיקרי"), (400, "עיקרי"), (480, "יח\"ד")],
        [(40, "16240.10"), (120, "5.94%"), (220, "4814.16"), (300, "14.10%"), (400, "11425.8"), (480, "82"), (540, "סה\"כ")],
    ])
    docs, facts, evidence = E.document_facts([f])
    assert facts["cell_main_pct"] == 14.10 and facts["cell_service_pct"] == 5.94 and facts["cell_units_total"] == 82
    assert evidence and evidence[0]["file"] == "areas.pdf" and evidence[0]["page"] == 1


def _ctx(docs, **declared):
    return E.Context(docs, declared, "", "368", {}, [])


def test_antiquities_letter_passes_with_its_quote(tmp_path):
    docs = E.load_docs([pdf(tmp_path, "iaa.pdf", ["הריני מודיעכם כי רשות העתיקות אינה מתנגדת לבקשתכם"])])
    r = E.r_antiquities(_ctx(docs))
    assert r.status == "PASS" and r.evidence[0]["file"] == "iaa.pdf" and "אינה מתנגדת" in r.evidence[0]["quote"]


def test_plan_clause_is_not_taken_as_an_approval(tmp_path):
    """The plan saying 'a condition is the HFC approval' is not the approval; the waste clause is not a waste estimate."""
    info = pdf(tmp_path, "info.pdf", ["ה. תנאי להיתרי בניה יהיה אישור פקע\"ר לפתרונות מיגון בתחום המגרש",
                                      "ג. תברואה: אצירה ופינוי פסולת יהיו בכפוף להנחיות הרשות"])
    info.doc_type = "permit_info"
    docs = E.load_docs([info])
    assert E.r_hfc(_ctx(docs)).status == "FAIL"
    assert E.r_waste(_ctx(docs)).status == "FAIL"


def test_nothing_found_leaves_the_finding_open(tmp_path):
    docs = E.load_docs([pdf(tmp_path, "x.pdf", ["מסמך כללי"])])
    results = [SimpleNamespace(rule_id="HA-633-ANTIQUITIES", status="UNCERTAIN", computed_result="UNCERTAIN",
                               explanation_he="", evidence=[], flags=["REVIEW_REQUIRED"], confidence=0.0)]
    assert E.resolve(results, docs, {}, "", {}, []) == 0 and results[0].status == "UNCERTAIN"


def test_unapproved_rule_keeps_the_safety_policy(tmp_path):
    docs = E.load_docs([pdf(tmp_path, "x.pdf", ["מסמך כללי"])])
    results = [SimpleNamespace(rule_id="HA-633-WASTE-ESTIMATE", status="UNCERTAIN", computed_result="UNCERTAIN",
                               explanation_he="", evidence=[], flags=["RULE_NOT_APPROVED"], confidence=0.0)]
    E.resolve(results, docs, {}, "", {}, [])
    assert results[0].computed_result == "FAIL" and results[0].status == "UNCERTAIN"
    assert "RESOLVED_FROM_DOCUMENTS" in results[0].flags


def test_a_document_filed_as_other_reverses_a_missing_document_fail(tmp_path):
    docs = E.load_docs([pdf(tmp_path, "iaa.pdf", ["הריני מודיעכם כי רשות העתיקות אינה מתנגדת לבקשתכם"])])
    results = [SimpleNamespace(rule_id="HA-633-ANTIQUITIES", status="FAIL", computed_result="FAIL",
                               explanation_he="לא נמצא אישור רשות העתיקות", evidence=[], flags=[], confidence=1.0)]
    assert E.resolve(results, docs, {}, "", {}, []) == 1 and results[0].status == "PASS"
    results[0].status = results[0].computed_result = "FAIL"
    assert E.resolve(results, E.load_docs([pdf(tmp_path, "y.pdf", ["מסמך כללי"])]), {}, "", {}, []) == 0
    assert results[0].status == "FAIL"                       # nothing found: the FAIL stands
