"""Generate clearly-labelled FICTITIOUS demo input files (DXF, XLSX, PDF).

Nothing here is a real case, parcel or person. Geometry is in millimetres ($INSUNITS=4)
to exercise unit conversion; the balcony is a block INSERT with an arc to exercise
block explosion and arc flattening.
Usage: python scripts/make_fixtures.py [out_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "fixtures" / "demo"
MM = 1000.0


def rect(msp, x, y, w, h, layer):
    pts = [(x * MM, y * MM), ((x + w) * MM, y * MM), ((x + w) * MM, (y + h) * MM), (x * MM, (y + h) * MM)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})


def new_doc():
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4  # mm
    for name in ["PLOT_BOUNDARY", "BLDG_LINE", "EXIST_BUILDING", "PROP_ADDITION", "BALCONY",
                 "SUKKAH", "ROOF_EDGE_FRONT", "ROOF_ROOM", "TEXT_NOTES"]:
        doc.layers.add(name)
    return doc


def base_site(doc):
    msp = doc.modelspace()
    rect(msp, 0, 0, 20, 25, "PLOT_BOUNDARY")            # 500 m² plot
    rect(msp, 3, 5, 14, 17, "BLDG_LINE")                # envelope: front 5 m, sides 3 m, rear 3 m
    rect(msp, 4, 6, 12, 14, "EXIST_BUILDING")           # existing footprint 168 m²
    msp.add_text("DEMO / הדגמה — נתונים פיקטיביים", dxfattribs={"layer": "TEXT_NOTES", "height": 400}).set_placement((0, -1500))
    return msp


def balcony_block(doc):
    blk = doc.blocks.new("BALCONY_R")
    # 3 m x 1.6 m balcony with a rounded outer edge (bulge) — local block coordinates (mm)
    blk.add_lwpolyline([(0, 0, 0), (3000, 0, 0), (3000, 1200, 0.4), (0, 1200, 0)], format="xyb", close=True,
                       dxfattribs={"layer": "BALCONY"})
    return blk


def roof_room(path: Path, setback_m: float):
    doc = new_doc()
    msp = base_site(doc)
    # roof-apartment floor outline = existing; front edge (street side) at y=6
    msp.add_line((4 * MM, 6 * MM), (16 * MM, 6 * MM), dxfattribs={"layer": "ROOF_EDGE_FRONT"})
    rect(msp, 6, 6 + setback_m, 6, 4, "ROOF_ROOM")
    doc.saveas(path)


def sukkah(path: Path, dist_m: float):
    doc = new_doc()
    msp = base_site(doc)
    rect(msp, 20 - dist_m - 2.5, 10, 2.5, 2.2, "SUKKAH")          # sukkah balcony near the east boundary
    doc.saveas(path)


def area_table(path: Path, proposed_main: float, proposed_service: float):
    wb = Workbook()
    ws = wb.active
    ws.title = "טבלת שטחים"
    ws.sheet_view.rightToLeft = True
    ws.append(["טבלת שטחים — הדגמה (פיקטיבי)"])
    ws.append(["תיאור", "קיים/מוצע", "שטח עיקרי (מ\"ר)", "שטחי שירות (מ\"ר)", "סה\"כ"])
    ws.append(["קומת קרקע — דירה 1", "קיים", 84.0, 6.0, 90.0])
    ws.append(["קומה א׳ — דירה 3", "קיים", 84.0, 6.0, 90.0])
    ws.append(["תוספת אגף אחורי", "מוצע", proposed_main, proposed_service, proposed_main + proposed_service])
    ws.append(["סה\"כ", "", None, None, None])
    wb.save(path)


def pdf_doc(path: Path, title: str, lines: list[str]):
    from bidi.algorithm import get_display
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    import os
    font = os.environ.get("BBP_PDF_FONT", r"C:\Windows\Fonts\arial.ttf")
    pdfmetrics.registerFont(TTFont("He", font))
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("He", 18)
    c.drawRightString(w - 50, h - 70, get_display(title))
    c.setFont("He", 11)
    y = h - 110
    for line in lines + ["", "מסמך הדגמה — נתונים פיקטיביים, אינו מסמך רשמי."]:
        c.drawRightString(w - 50, y, get_display(line))
        y -= 20
    c.setFont("He", 60)
    c.setFillGray(0.9)
    c.saveState(); c.translate(w / 2, h / 2); c.rotate(35); c.drawCentredString(0, 0, get_display("הדגמה")); c.restoreState()
    c.save()


def pdf_pages(path: Path, pages: list[tuple[str, list[str]]]):
    """Multi-page PDF, one (title, lines) per page — used for batch-import fixtures."""
    from bidi.algorithm import get_display
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    import os
    pdfmetrics.registerFont(TTFont("He", os.environ.get("BBP_PDF_FONT", r"C:\Windows\Fonts\arial.ttf")))
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    for title, lines in pages:
        c.setFont("He", 16)
        c.drawRightString(w - 50, h - 70, get_display(title))
        c.setFont("He", 11)
        y = h - 110
        for line in lines + ["", "קובץ בדיקה — נתונים פיקטיביים."]:
            c.drawRightString(w - 50, y, get_display(line))
            y -= 20
        c.showPage()
    c.save()


def import_fixtures(out: Path):
    """Batch-import samples: a PDF holding two application forms, and a ZIP with two request
    folders plus a request list. All values are fictitious (gush 9999 does not exist)."""
    import zipfile
    out.mkdir(parents=True, exist_ok=True)
    pdf_pages(out / "two_requests.pdf", [
        ("טופס בקשה להיתר", ["מספר בקשה: T-2026-001", "גוש: 9999 חלקה: 11", "כתובת: רחוב הבדיקה 1",
                             "מהות הבקשה: הרחבת דירה באגף אחורי", "תאריך מדידה: 01/09/2026"]),
        ("נספח לבקשה", ["גוש: 9999 חלקה: 11", "המשך פרטי הבקשה"]),
        ("טופס בקשה להיתר", ["מספר בקשה: T-2026-002", "גוש: 9999 חלקה: 12", "כתובת: רחוב הבדיקה 2",
                             "מהות הבקשה: מרפסת סוכה"]),
    ])
    tmp = out / "_tmp"
    tmp.mkdir(exist_ok=True)
    pdf_doc(tmp / "form_a.pdf", "טופס בקשה להיתר", ["גוש: 9999 חלקה: 21", "מהות הבקשה: הרחבת דירה"])
    pdf_doc(tmp / "survey_a.pdf", "מפת מדידה", ["מודד מוסמך: בדיקה"])
    pdf_doc(tmp / "form_b.pdf", "טופס בקשה להיתר", ["גוש: 9999 חלקה: 22", "מהות הבקשה: חדר יציאה לגג"])
    wb = Workbook()
    ws = wb.active
    ws.append(["תיקייה", "מספר בקשה", "נושא", "סוג בקשה", "גוש", "חלקה", "כתובת", "תכניות"])
    ws.append(["REQ-A", "Z-2026-010", "הרחבת דירה — בקשת בדיקה", "הרחבה", 9999, 21, "רחוב הבדיקה 21", "DEMO/1"])
    ws.append(["REQ-B", "Z-2026-011", "חדר יציאה לגג — בקשת בדיקה", "חדר גג", 9999, 22, "רחוב הבדיקה 22", ""])
    wb.save(tmp / "requests.xlsx")
    with zipfile.ZipFile(out / "two_requests.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp / "requests.xlsx", "requests.xlsx")
        z.write(tmp / "form_a.pdf", "REQ-A/form_a.pdf")
        z.write(tmp / "survey_a.pdf", "REQ-A/survey_a.pdf")
        z.write(OUT / "case2_extension_ok.dxf", "REQ-A/plan.dxf")
        z.write(OUT / "case2_area_table.xlsx", "REQ-A/areas.xlsx")
        z.write(tmp / "form_b.pdf", "REQ-B/form_b.pdf")
        z.write(OUT / "case3_roof_room_249.dxf", "REQ-B/roof.dxf")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Case 1: addition 6 x 5 = 30 m² from y=20 to y=25 -> 3 m beyond the rear building line (y=22);
    # balcony is a block INSERT (with arc) also crossing the building line.
    doc = new_doc(); msp = base_site(doc)
    rect(msp, 6, 20, 6, 5, "PROP_ADDITION")
    balcony_block(doc); msp.add_blockref("BALCONY_R", (12.5 * MM, 20 * MM), dxfattribs={"layer": "BALCONY"})
    doc.saveas(OUT / "case1_extension_exceeds.dxf")
    area_table(OUT / "case1_area_table.xlsx", 26.0, 0.0)            # declared 26 vs drawn 30 -> mismatch
    # Case 2: compliant addition 5 x 4 = 20 m² inside the envelope
    doc = new_doc(); msp = base_site(doc)
    rect(msp, 6, 18, 5, 4, "PROP_ADDITION")
    doc.saveas(OUT / "case2_extension_ok.dxf")
    area_table(OUT / "case2_area_table.xlsx", 18.0, 2.0)
    # Case 3: roof room under policy 13.1.2026 — setback 2.49 m (boundary test)
    roof_room(OUT / "case3_roof_room_249.dxf", 2.49)
    roof_room(OUT / "case3b_roof_room_250.dxf", 2.50)
    # Case 4: sukkah 1.2 m from boundary
    sukkah(OUT / "case4_sukkah.dxf", 1.2)
    # PDFs
    pdf_doc(OUT / "application_form.pdf", "טופס בקשה להיתר — הדגמה",
            ["מבקש: ישראל ישראלי (פיקטיבי)", "גוש: 0000 חלקה: 000 (הדגמה)", "מהות הבקשה: תוספת בנייה"])
    pdf_doc(OUT / "survey_map.pdf", "מפת מדידה — הדגמה", ["מודד מוסמך: דמו (פיקטיבי)", "קנה מידה 1:250"])
    pdf_doc(OUT / "permit_info.pdf", "מידע להיתר — הדגמה", ["תכניות חלות: DEMO/1 (פיקטיבית)"])
    pdf_doc(OUT / "photos.pdf", "תמונות הבניין הקיים — הדגמה", ["צילום חזית קדמית", "צילום חזית אחורית"])
    pdf_doc(OUT / "master_plan.pdf", "תכנית כוללת לבניין — תוספות עתידיות (הדגמה)", ["תוספות עתידיות לכל הדירות"])
    pdf_doc(OUT / "sections.pdf", "חתכים וחזיתות — הדגמה", ["חתך א-א", "חזית צפונית", "חזית דרומית"])
    pdf_doc(OUT / "consents.pdf", "הסכמות בעלי זכויות — הדגמה", ["הסכמת השכנים: 75% (פיקטיבי)"])
    import_fixtures(OUT.parent / "import")
    print("fixtures written to", OUT, "and", OUT.parent / "import")


if __name__ == "__main__":
    main()
