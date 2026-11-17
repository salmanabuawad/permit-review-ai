"""Shared intake helpers: ZIP unpacking with safety limits, application-form field extraction,
multi-request PDF splitting. The import pipeline itself lives in app.intake.pipeline.

(Original description of the first version follows.)
Batch intake: find one or more permit requests inside uploaded files and pre-fill cases.

Supported inputs (any mix, in one upload):
  * ZIP — one folder per request (all files in the folder belong to it). Files at the ZIP root
    form one extra request unless a request list maps them. Nested ZIPs are skipped.
  * Request list (Excel .xlsx / .csv) — one row per request: number, subject, type, gush,
    helka, address, plans, folder. Rows are matched to ZIP folders by folder name or number.
  * PDF with several application forms — split into one PDF per request.
  * Loose PDF/DXF/DWG/XLSX files — one request.

Nothing is created here. analyze() returns an editable preview; every auto-filled field carries
its provenance (file, page, method, confidence). Cases are created only on commit after a person
reviewed the preview. Applicant names / ID numbers are deliberately NOT extracted.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath

import pymupdf
from openpyxl import load_workbook

SUPPORTED = {".pdf": "pdf", ".dxf": "dxf", ".dwg": "dwg", ".xlsx": "xlsx", ".xlsm": "xlsx", ".csv": "csv"}
MAX_ZIP_MEMBERS = 500
MAX_ZIP_TOTAL = 500 * 1024 * 1024          # uncompressed
MAX_ZIP_RATIO = 200                        # zip-bomb guard (uncompressed / compressed per member)

PERMIT_TYPE_HINTS = [   # first match wins — most specific first
    ("roof_room_addition", r"חדר(?:י)?\s*(?:יציאה\s*ל)?גג|חדר\s*על\s*הגג"),
    ("addition_sukkah", r"סוכ(?:ה|ות)"),
    ("addition_balcony", r"מרפס(?:ת|ות)"),
    ("addition_extension", r"הרחב(?:ה|ת)|תוספת|אגף"),
]


FIELD_PATTERNS = {   # value patterns for "label: value" pairs on one line
    "gush": (r"גוש", r"\d{3,6}"),
    "helka": (r"חלקה", r"\d{1,5}"),
    "case_number": (r"(?:מספר|מס['׳]?)\s*(?:ה)?(?:בקשה|תיק)", r"[A-Za-z0-9][A-Za-z0-9\-/]{2,30}"),
    "survey_map_date": (r"תאריך\s*(?:ה)?מדידה", r"\d{1,2}[./]\d{1,2}[./]\d{2,4}"),
}
TEXT_FIELDS = {   # free-text value to the end of the line
    "address": r"כתובת(?:\s*הנכס)?",
    "description": r"מהות\s*(?:ה)?בקשה",
    "applicable_plans": r"תכני(?:ת|ות)\s*חלות?",
}
FORM_START = re.compile(r"(?:טופס\s*)?בקשה\s*להיתר|השקב\s*ספוט")   # also the visual-order spelling


@dataclass
class Source:
    file: str
    page: int | None = None
    method: str = ""
    confidence: float = 1.0


# ------------------------------------------------------------------ text extraction helpers

def _first(text: str, key: str, value: str, file: str, page: int | None) -> tuple[str, Source] | None:
    """Find 'key: value' in normal order or 'value :key' as produced by mixed-direction PDF lines."""
    tries = [
        (rf"{key}\s*[:：]\s*({value})", "תווית: ערך", 0.9),
        (rf"({value})\s*[:：]\s*{key}", "ערך :תווית (שורה במהופך)", 0.7),
        (rf"{key}\s+({value})", "תווית ערך", 0.75),
        (rf"({value})\s+{key}", "ערך תווית (שורה במהופך)", 0.6),
    ]
    for pat, method, conf in tries:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip(), Source(file, page, method, conf)
    return None


def _text_field(lines: list[str], key: str, file: str, page: int | None) -> tuple[str, Source] | None:
    for line in lines:
        # mixed-direction line: a trailing number ("...הבדיקה 1") is extracted at the start ("1 כתובת: ...")
        m = re.search(rf"^\s*([\d][\d\-/]*)\s+{key}\s*[:：]\s*(.+?)\s*$", line)
        if m:
            return f"{m.group(2)} {m.group(1)}", Source(file, page, "תווית: טקסט (מספר הוחזר מתחילת השורה)", 0.6)
        m = re.search(rf"{key}\s*[:：]\s*(.+?)\s*$", line)
        if m and m.group(1):
            return m.group(1), Source(file, page, "תווית: טקסט", 0.85)
        m = re.search(rf"^\s*(.+?)\s*[:：]\s*{key}\s*$", line)
        if m and m.group(1):     # reversed line: restore word order
            return " ".join(reversed(m.group(1).split())), Source(file, page, "טקסט :תווית (שורה במהופך)", 0.55)
    return None


def infer_permit_type(*texts: str) -> str | None:
    blob = " ".join(t for t in texts if t)
    for ptype, pat in PERMIT_TYPE_HINTS:
        if re.search(pat, blob):
            return ptype
    return None


def extract_fields(text: str, file: str, page: int | None = None) -> tuple[dict, dict]:
    fields, sources = {}, {}
    for name, (key, value) in FIELD_PATTERNS.items():
        hit = _first(text, key, value, file, page)
        if hit:
            fields[name], sources[name] = hit
    lines = [l for l in text.splitlines() if l.strip()]
    for name, key in TEXT_FIELDS.items():
        hit = _text_field(lines, key, file, page)
        if hit:
            fields[name], sources[name] = hit
    if "applicable_plans" in fields:
        fields["applicable_plans"] = [p.strip() for p in re.split(r"[,;،]", fields["applicable_plans"]) if p.strip()]
    if "survey_map_date" in fields:
        m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", fields["survey_map_date"])
        if m:
            d, mo, y = (int(x) for x in m.groups())
            y = y + 2000 if y < 100 else y
            fields["survey_map_date"] = f"{y:04d}-{mo:02d}-{d:02d}"
    ptype = infer_permit_type(fields.get("description", ""))
    if ptype:
        fields["permit_type"] = ptype
        sources["permit_type"] = Source(file, page, "מילות מפתח במהות הבקשה", 0.7)
    if fields.get("description"):
        fields["title"] = fields["description"][:200]
        sources["title"] = sources["description"]
    return fields, sources


# ------------------------------------------------------------------ PDFs

def pdf_pages_text(data: bytes) -> list[str]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        return [p.get_text() for p in doc]
    finally:
        doc.close()


def split_multi_request_pdf(data: bytes) -> list[tuple[int, int]]:
    """Return page ranges (0-based, inclusive) when the PDF holds 2+ application forms; else []."""
    texts = pdf_pages_text(data)
    starts = []
    prev_key = None
    for i, t in enumerate(texts):
        if not FORM_START.search(t):
            continue
        g = _first(t, *FIELD_PATTERNS["gush"], "", i)
        h = _first(t, *FIELD_PATTERNS["helka"], "", i)
        key = (g[0] if g else None, h[0] if h else None)
        if not starts or key != prev_key or key == (None, None):
            starts.append(i)
        prev_key = key
    if len(starts) < 2:
        return []
    starts[0] = 0
    return [(s, (starts[k + 1] - 1) if k + 1 < len(starts) else len(texts) - 1) for k, s in enumerate(starts)]


def pdf_subset(data: bytes, first: int, last: int) -> bytes:
    src = pymupdf.open(stream=data, filetype="pdf")
    out = pymupdf.open()
    try:
        out.insert_pdf(src, from_page=first, to_page=last)
        return out.tobytes()
    finally:
        out.close()
        src.close()


# ------------------------------------------------------------------ main entry

def guess_doc_type(name: str, kind: str, text: str, classify) -> tuple[str, str]:
    if kind in ("dxf", "dwg"):
        return "architectural_plan", "סוג הקובץ"
    if kind == "xlsx":
        return "area_table", "סוג הקובץ"
    lower = name.lower()
    for pat, dt in [(r"survey|מדידה", "survey_map"), (r"photo|תמונ", "existing_building_photos"),
                    (r"consent|הסכמ", "consents"), (r"section|elevation|חתך|חזית", "sections_elevations"),
                    (r"info|מידע", "permit_info"), (r"form|בקשה|application", "application_form")]:
        if re.search(pat, lower):
            return dt, "שם הקובץ"
    label = classify(name, text) if classify else None
    return (label, "סיווג לפי תוכן") if label else ("other", "לא זוהה — יש לבחור")


class ImportError_(ValueError):
    pass


def _safe_name(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name
    return "".join(c for c in base if c not in '<>:"/\\|?*') or "file"


def unpack(files: list[tuple[str, bytes]]) -> tuple[list[tuple[str, str, bytes]], list[str]]:
    """Flatten uploads into (group, name, data). group = top-level ZIP folder or '' (root/loose)."""
    out, warnings = [], []
    for name, data in files:
        if name.lower().endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile as exc:
                raise ImportError_(f"קובץ ZIP פגום: {name}") from exc
            infos = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
            if len(infos) > MAX_ZIP_MEMBERS:
                raise ImportError_(f"ב־ZIP יותר מ־{MAX_ZIP_MEMBERS} קבצים")
            if sum(i.file_size for i in infos) > MAX_ZIP_TOTAL:
                raise ImportError_("נפח הקבצים ב־ZIP אחרי חילוץ גדול מדי")
            for i in infos:
                if i.compress_size and i.file_size / i.compress_size > MAX_ZIP_RATIO:
                    raise ImportError_(f"יחס דחיסה חשוד בקובץ {i.filename}")
                parts = [p for p in PurePosixPath(i.filename.replace("\\", "/")).parts if p not in ("", ".")]
                if any(p == ".." for p in parts) or i.filename.startswith("/"):
                    raise ImportError_(f"נתיב לא בטוח ב־ZIP: {i.filename}")
                if parts[-1].lower().endswith(".zip"):
                    warnings.append(f"ZIP מקונן דולג: {i.filename}")
                    continue
                group = parts[0] if len(parts) > 1 else ""
                out.append((group, _safe_name(parts[-1]), z.read(i)))
        else:
            out.append(("", _safe_name(name), data))
    return out, warnings
