"""Hebrew PDF rendering: logical wrapping before bidi, text extractable, numbers not reversed."""
import pymupdf
from bidi.algorithm import get_display

from app.reports import _fonts, _wrap_logical


def test_wrap_keeps_logical_line_order():
    _fonts()
    text = "נסיגת חדר גג חדש מחזית שפת הגג גדולה או שווה ל־2.5 מטר בנוסף לנסיגה בתכנית הגגות"
    lines = _wrap_logical(text, "He", 9, 120)
    assert len(lines) > 1
    assert " ".join(lines) == text            # wrapping happened in logical order
    assert lines[0].startswith("נסיגת")


def test_numbers_and_symbols_survive_bidi():
    vis = get_display("נסיגה ≥ 2.5 מ׳ בגוש 6188 חלקה 12")
    assert "2.5" in vis and "6188" in vis and "12" in vis
    # bidi mirrors "≥" in RTL runs: visual LTR string reads "2.5 ≤ <setback>", i.e. setback ≥ 2.5
    assert "2.5 ≤" in vis and "≥" not in vis


def test_generated_pdf_has_hebrew_text(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.seed import seed
    seed(reset=True)
    with TestClient(app) as c:
        case = next(x for x in c.get("/api/cases", headers={"X-User": "u-reviewer"}).json()
                    if x["case_number"] == "DEMO-0001")
        r = c.get(f"/api/runs/{case['last_run']['id']}/defects.pdf", headers={"X-User": "u-reviewer"})
        assert r.status_code == 200, r.text
        pdf = r.content
    p = tmp_path / "r.pdf"
    p.write_bytes(pdf)
    doc = pymupdf.open(p)
    text = "".join(pg.get_text() for pg in doc)
    # visual-order Hebrew is stored; check a reversed token and the case number
    assert "DEMO-0001" in text
    assert get_display("דוח ליקויים") in text or "דוח ליקויים" in text
