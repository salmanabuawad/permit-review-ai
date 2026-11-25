"""Convert a DWFX drawing (Autodesk's XPS-based plot, as Rishui Zamin delivers plans) into a PDF the app can show
and search. Runs on the AI PC, called by bbp_ai_agent.py — never on the app server.

Each sheet is rendered to an image (at most MAX_PX on its long side) and placed on a PDF page of the sheet's size,
with the sheet's text written on top as an invisible layer, so the app can show, search and classify the plan.
The result is a picture of the drawing: nothing in it is measured (no CAD layers, no scale), and the original DWFX
stays the document of record.

Why render instead of PyMuPDF's convert_to_pdf(): on a real 6-sheet submission (105 MB of XAML on one sheet)
convert_to_pdf() ran for over 10 minutes at 4 GB, while rendering every sheet took about 10 seconds.

Usage: python dwfx_convert.py <in.dwfx> <out.pdf> [font.ttf]     prints a JSON summary; needs PyMuPDF.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

import pymupdf

MAX_PX = 7000            # long side of a rendered sheet
MAX_ZOOM = 2.0           # 144 dpi for small sheets
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"]


class NotDwfx(ValueError):
    pass


HEB_RUN = re.compile(r"[\u0590-\u05ff]+")
FINALS = set("ךםןףץ")         # Hebrew final letters: they only ever end a word in reading order


def sheet_words(pg) -> list[tuple[float, float, float, float, str]]:
    """(x0, y0, x1, y1, word) for every word on a sheet, as the XPS stores it."""
    return [tuple(w[:5]) for w in pg.get_text("words")]


def hebrew_is_reversed(words: list[str]) -> bool:
    """AutoCAD plots often store Hebrew in visual order ("םיטקייורפ"); other files store it in reading order.
    A sheet is consistent, so vote with final letters: one at the start of a Hebrew run means the run is reversed."""
    start = end = 0
    for w in words:
        for run in HEB_RUN.findall(w):
            if len(run) > 1:
                start += run[0] in FINALS
                end += run[-1] in FINALS
    return start > end


def reading_order(word: str, reversed_: bool) -> str:
    return HEB_RUN.sub(lambda m: m.group(0)[::-1], word) if reversed_ else word


class TextWriter:
    """Writes an invisible text layer whose extraction reads in reading order. MuPDF reorders right-to-left runs
    when it extracts text, so what to write is checked once per word shape: write it as is, or with each Hebrew run
    flipped, whichever reads back as intended."""

    def __init__(self, font: str):
        self.font = font
        self.flip: dict[bool, bool] = {}

    def _reads_back(self, text: str) -> str:
        d = pymupdf.open()
        d.new_page().insert_text((20, 40), text, fontsize=10, fontfile=self.font, fontname="F0", render_mode=3)
        return pymupdf.open("pdf", d.tobytes())[0].get_text().strip()

    def text_for(self, wanted: str) -> str:
        if not HEB_RUN.search(wanted):
            return wanted
        flipped = HEB_RUN.sub(lambda m: m.group(0)[::-1], wanted)
        if wanted == flipped:                       # single letters: nothing to decide
            return wanted
        return wanted if self._reads_back(wanted) == wanted else flipped


def check_package(path: Path) -> None:
    """A DWFX is a ZIP (OPC) package with an XPS fixed-document sequence. Classic binary DWF (W2D streams) is not."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise NotDwfx("הקובץ אינו חבילת DWFX תקינה") from exc
    if not any(n.lower().endswith((".fdseq", ".fpage")) for n in names):
        raise NotDwfx("חבילת DWF ללא דפי XPS (DWF בינארי ישן) — לא נתמכת; יש לבקש DWFX, PDF או DWG")


def convert(src: Path, dst: Path, font: str | None = None) -> dict:
    check_package(src)
    font = font or next((f for f in FONTS if Path(f).exists()), None)
    doc = pymupdf.open(str(src), filetype="xps")
    out = pymupdf.open()
    sheets = []
    for pg in doc:
        r = pg.rect
        zoom = min(MAX_ZOOM, MAX_PX / max(r.width, r.height, 1))
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        words = sheet_words(pg)
        reversed_ = hebrew_is_reversed([w[4] for w in words])
        page = out.new_page(width=r.width, height=r.height)
        page.insert_image(page.rect, pixmap=pix)
        written = 0
        if font:
            writer = TextWriter(font)
            for x0, y0, x1, y1, w in words:
                try:
                    page.insert_text((x0, y1), writer.text_for(reading_order(w, reversed_)),
                                     fontsize=max(1.0, (y1 - y0) * 0.8), fontfile=font,
                                     fontname="F0", render_mode=3)          # invisible: searchable, not drawn
                    written += 1
                except Exception:  # noqa: BLE001 — a glyph the font lacks must not lose the sheet
                    pass
        sheets.append({"width_pt": round(r.width, 1), "height_pt": round(r.height, 1),
                       "image_px": [pix.width, pix.height], "words": len(words), "words_written": written,
                       "hebrew_stored_reversed": reversed_})
    out.save(str(dst), garbage=3, deflate=True)
    return {"sheets": sheets, "font": font, "text_layer": bool(font), "bytes": dst.stat().st_size}


if __name__ == "__main__":
    try:
        info = convert(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else None)
    except NotDwfx as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(2)
    print(json.dumps(info, ensure_ascii=False))
