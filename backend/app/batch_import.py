"""Batch intake: find one or more permit requests inside uploaded files and pre-fill cases.

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
PERMIT_TYPE_WORDS = {"הרחבה": "addition_extension", "הרחבת דירה": "addition_extension", "תוספת בנייה": "addition_extension",
                     "מרפסת": "addition_balcony", "סוכה": "addition_sukkah", "מרפסת סוכה": "addition_sukkah",
                     "חדר גג": "roof_room_addition", "חדר יציאה לגג": "roof_room_addition"}

MANIFEST_COLUMNS = {
    "case_number": [r"מס(?:פר|['׳])?\s*(?:בקשה|תיק)", r"case.?number", r"request.?id"],
    "title": [r"נושא", r"מהות", r"תיאור", r"title"],
    "permit_type": [r"סוג\s*(?:ה)?בקשה", r"permit.?type"],
    "gush": [r"^גוש", r"gush", r"block"],
    "helka": [r"^חלקה", r"helka", r"parcel"],
    "address": [r"כתובת", r"address"],
    "applicable_plans": [r"תכני(?:ת|ות)", r"plans?"],
    "folder": [r"תיקי(?:ה|יה)", r"folder", r"קבצים"],
}

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


@dataclass
class DraftFile:
    ref: str                  # staging key
    name: str
    kind: str
    size: int
    doc_type: str
    doc_type_source: str


@dataclass
class Draft:
    key: str
    origin: str               # e.g. "zip:folder/A", "pdf-split:forms.pdf p.1-2", "manifest row 3"
    fields: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    files: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


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


# ------------------------------------------------------------------ request lists

def _norm_permit_type(v: str | None) -> str | None:
    if not v:
        return None
    v = str(v).strip()
    if v in PERMIT_TYPE_WORDS.values():
        return v
    return PERMIT_TYPE_WORDS.get(v) or infer_permit_type(v)


def parse_manifest(name: str, data: bytes) -> list[dict] | None:
    """Rows of a request list, or None when the table is not a request list (e.g. an area table)."""
    rows: list[list] = []
    if name.lower().endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        rows = [r for r in csv.reader(io.StringIO(text))]
    else:
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:  # noqa: BLE001
            return None
        try:
            rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()
    for hi, header in enumerate(rows[:10]):
        cols = {}
        for j, cell in enumerate(header):
            if cell is None:
                continue
            for key, pats in MANIFEST_COLUMNS.items():
                if key not in cols and any(re.search(p, str(cell), re.IGNORECASE) for p in pats):
                    cols[key] = j
                    break
        if ("gush" in cols or "case_number" in cols) and len(cols) >= 2:
            out = []
            for ri, row in enumerate(rows[hi + 1:], start=hi + 2):
                rec = {k: row[j] for k, j in cols.items() if j < len(row) and row[j] not in (None, "")}
                if not rec:
                    continue
                rec = {k: (str(v).strip() if not isinstance(v, float) else str(int(v)) if v.is_integer() else str(v))
                       for k, v in rec.items()}
                if "applicable_plans" in rec:
                    rec["applicable_plans"] = [p.strip() for p in re.split(r"[,;،]", rec["applicable_plans"]) if p.strip()]
                if "permit_type" in rec:
                    rec["permit_type"] = _norm_permit_type(rec["permit_type"])
                rec["_row"] = ri
                out.append(rec)
            return out
    return None


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


def analyze(files: list[tuple[str, bytes]], classify=None) -> tuple[list[Draft], dict[str, bytes], list[str]]:
    """Return (drafts, staged_blobs, global_warnings). Pure function — no database access."""
    items, warnings = unpack(files)
    blobs: dict[str, bytes] = {}
    groups: dict[str, list[tuple[str, bytes]]] = {}
    manifests: list[tuple[str, list[dict]]] = []
    for group, name, data in items:
        ext = PurePosixPath(name).suffix.lower()
        if ext not in SUPPORTED:
            warnings.append(f"סוג קובץ לא נתמך דולג: {name}")
            continue
        if ext in (".xlsx", ".xlsm", ".csv"):
            rows = parse_manifest(name, data)
            if rows is not None:
                manifests.append((name, rows))
                continue
            if ext == ".csv":
                warnings.append(f"CSV שאינו רשימת בקשות דולג: {name}")
                continue
        groups.setdefault(group, []).append((name, data))

    drafts: list[Draft] = []
    by_folder: dict[str, Draft] = {}

    def stage(name: str, data: bytes) -> str:
        ref = uuid.uuid4().hex[:12]
        blobs[ref] = data
        return ref

    def add_file(d: Draft, name: str, data: bytes, doc_type: str | None = None, source: str | None = None, text: str = ""):
        kind = SUPPORTED[PurePosixPath(name).suffix.lower()]
        if doc_type is None:
            doc_type, source = guess_doc_type(name, kind, text, classify)
        d.files.append(asdict(DraftFile(stage(name, data), name, kind, len(data), doc_type, source)))

    def merge(d: Draft, fields: dict, sources: dict):
        for k, v in fields.items():
            if k not in d.fields or (sources[k].confidence > d.sources.get(k, {}).get("confidence", 0)):
                d.fields[k] = v
                d.sources[k] = asdict(sources[k])

    for group, flist in groups.items():
        split_done = False
        if group == "" and len(flist) == 1 and flist[0][0].lower().endswith(".pdf"):
            name, data = flist[0]
            ranges = split_multi_request_pdf(data)
            if ranges:      # one PDF holding several application forms
                texts = pdf_pages_text(data)
                for first, last in ranges:
                    d = Draft(key=uuid.uuid4().hex[:8], origin=f"{name} · עמ׳ {first + 1}–{last + 1}")
                    for p in range(first, last + 1):
                        merge(d, *extract_fields(texts[p], name, p + 1))
                    add_file(d, f"{PurePosixPath(name).stem}_p{first + 1}-{last + 1}.pdf", pdf_subset(data, first, last),
                             "application_form", "פוצל מ־PDF מרובה בקשות")
                    drafts.append(d)
                split_done = True
        if split_done:
            continue
        d = Draft(key=uuid.uuid4().hex[:8], origin=f"תיקייה: {group}" if group else "קבצים בודדים / שורש ה־ZIP")
        for name, data in flist:
            text = ""
            if name.lower().endswith(".pdf"):
                try:
                    pages = pdf_pages_text(data)
                except Exception:  # noqa: BLE001
                    pages = []
                    d.warnings.append(f"לא ניתן לקרוא את {name}")
                text = "\n".join(pages)
                for i, ptxt in enumerate(pages):
                    merge(d, *extract_fields(ptxt, name, i + 1))
                if pages and not any(p.strip() for p in pages):
                    d.warnings.append(f"{name}: ללא שכבת טקסט (סרוק) — השדות לא חולצו ממנו")
            add_file(d, name, data, text=text)
        if group and "title" not in d.fields:
            d.fields["title"] = group
            d.sources["title"] = asdict(Source(group, None, "שם התיקייה", 0.5))
        if "permit_type" not in d.fields:
            pt = infer_permit_type(group, *(f["name"] for f in d.files))
            if pt:
                d.fields["permit_type"] = pt
                d.sources["permit_type"] = asdict(Source(group or d.files[0]["name"], None, "מילות מפתח בשמות התיקייה/הקבצים", 0.5))
        drafts.append(d)
        if group:
            by_folder[group] = d

    for mname, rows in manifests:     # request list rows win over text extraction (explicit data)
        for rec in rows:
            folder = rec.pop("folder", None)
            row = rec.pop("_row")
            target = by_folder.get(folder or "") or by_folder.get(rec.get("case_number", ""))
            if target is None:
                target = Draft(key=uuid.uuid4().hex[:8], origin=f"{mname} · שורה {row}")
                drafts.append(target)
                if folder:
                    target.warnings.append(f"התיקייה '{folder}' שצוינה ברשימה לא נמצאה ב־ZIP")
            for k, v in rec.items():
                if v in (None, "", []):
                    continue
                target.fields[k] = v
                target.sources[k] = asdict(Source(mname, None, f"רשימת בקשות, שורה {row}", 1.0))
    # drop the empty "root" draft when a request list consumed everything else
    drafts = [d for d in drafts if d.files or d.fields]
    for d in drafts:
        for req in ("permit_type", "case_number", "title"):
            if not d.fields.get(req):
                d.warnings.append({"permit_type": "סוג הבקשה לא זוהה — יש לבחור",
                                   "case_number": "מספר בקשה לא נמצא — יוקצה מספר זמני",
                                   "title": "נושא לא נמצא"}[req])
        if any(f["doc_type"] == "other" for f in d.files):
            d.warnings.append("חלק מהקבצים לא סווגו — יש לבחור סוג מסמך")
    return drafts, blobs, warnings
