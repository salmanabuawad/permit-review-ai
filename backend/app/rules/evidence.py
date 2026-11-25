"""Evidence stage: answer open findings from the case's own documents.

The rule engine returns UNCERTAIN when a value was not measured or a rule is qualitative. Most of those answers are
in the documents of a Rishui Zamin package: the area table, the approval letters, the external bodies' responses
quoted in the permit-information file, the request form itself. This stage reads them and gives each open finding a
final answer — PASS or FAIL — with the file, page and quote it rests on.

Two kinds of output:
* facts: values read from documents (cell totals from the area table) that compare rules then evaluate as usual;
* resolutions: for a qualitative or condition rule, the answer and its evidence.

The engine's safety policy is kept: a resolved FAIL on a rule that is not yet professionally approved has
computed_result FAIL and status UNCERTAIN (shown as the system's answer, not applied as a rejection). Anything a
resolver cannot find stays as the engine left it. Every resolution is flagged RESOLVED_FROM_DOCUMENTS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ..config import settings

BIDI = re.compile(r"[‎‏‪-‮⁦-⁩]")


def norm(t: str) -> str:
    return re.sub(r"[ \t\xa0]+", " ", BIDI.sub("", t or ""))


@dataclass
class Doc:
    filename: str
    doc_type: str
    pages: list[str]                       # normalized text per page
    path: Path

    def find(self, *patterns: str) -> tuple[int, str] | None:
        """(page, quote) of the first page where every pattern matches. Pages are searched flattened (line breaks as
        spaces: PDF text breaks phrases across lines); the quote is ~160 characters around the first pattern."""
        for i, t in enumerate(self.pages, 1):
            flat = re.sub(r"\s+", " ", t)
            if all(re.search(p, flat) for p in patterns):
                m = re.search(patterns[0], flat)
                return i, flat[max(0, m.start() - 70):m.end() + 90].strip()
        return None


@dataclass
class Resolution:
    status: str                            # PASS | FAIL | NA
    explanation_he: str
    evidence: list[dict] = field(default_factory=list)


def ev(doc: Doc | None, page: int | None, quote: str, source: str | None = None) -> dict:
    return {"type": "document", "file": doc.filename if doc else source, "page": page, "quote": quote,
            "method": "קריאת מסמך בתיק" if doc else "קריאת מקור תכנוני"}


def load_docs(files) -> list[Doc]:
    """Text of every readable case file: PDFs, and DWFX drawings once converted to PDF on the AI PC."""
    out = []
    for f in files:
        path = None
        if f.kind == "pdf":
            path = Path(f.storage_path)
        elif f.kind == "dwfx":
            p = ((f.ingest_report or {}).get("conversion") or {}).get("pdf_path")
            path = Path(p) if p else None
        if not path or not path.exists():
            continue
        try:
            from ..intake.text import repair_shifted_font      # Rishui Zamin "מידע להיתר" uses a shifted font
            with pymupdf.open(str(path)) as d:
                pages = [norm(repair_shifted_font(p.get_text())) for p in d]
        except Exception:  # noqa: BLE001 — an unreadable file is simply not evidence
            continue
        out.append(Doc(f.filename, f.doc_type, pages, path))
    return out


# ------------------------------------------------------------------ facts: the area table

def _num(w: str) -> float | None:
    try:
        return float(w.replace("%", "").replace(",", ""))
    except ValueError:
        return None


def area_table_facts(docs: list[Doc]) -> tuple[dict, list[dict]]:
    """Cell totals from an area table ("סה"כ" row under 'עיקרי / אחוז מעיקרי / שירות / אחוז משירות / מס יח"ד').
    Columns are matched by the x position of their headers, not by order (the PDFs are right-to-left)."""
    for doc in docs:
        try:
            pdf = pymupdf.open(str(doc.path))
        except Exception:  # noqa: BLE001
            continue
        with pdf:
            for pno, page in enumerate(pdf, 1):
                words = [(w[0], w[1], w[2], w[3], norm(w[4])) for w in page.get_text("words")]
                def head(rx):
                    hits = [w for w in words if re.search(rx, w[4])]
                    return (hits[0][0] + hits[0][2]) / 2 if hits else None
                # PyMuPDF splits סה"כ / יח"ד at the quote mark: match the first part
                cols = {"main_pct": head(r"מעיקרי"), "service_pct": head(r"משירות"), "units": head(r"^יח(\"?ד)?$")}
                total = [w for w in words if re.fullmatch(r"סה(\"?כ)?", w[4].strip())]
                if not (cols["main_pct"] and cols["service_pct"] and total):
                    continue
                last = max(total, key=lambda w: w[1])                  # the totals row is the bottom one
                ty = (last[1] + last[3]) / 2
                row = [w for w in words if abs((w[1] + w[3]) / 2 - ty) < 4 and _num(w[4]) is not None]
                def at(x, pct):
                    cands = [w for w in row if ("%" in w[4]) == pct]
                    return _num(min(cands, key=lambda w: abs((w[0] + w[2]) / 2 - x))[4]) if cands else None
                main, service = at(cols["main_pct"], True), at(cols["service_pct"], True)
                units = at(cols["units"], False) if cols["units"] else None
                if main is None or service is None:
                    continue
                facts = {"cell_main_pct": main, "cell_service_pct": service}
                if units is not None and float(units).is_integer():
                    facts["cell_units_total"] = int(units)
                title = doc.find(r"משטח מגרש|סה\"?כ שטח")
                quote = f"שורת סה\"כ: עיקרי {main}%, שירות {service}%" + (f", {int(units)} יח\"ד" if "cell_units_total" in facts else "")
                return facts, [ev(doc, pno, quote + (f" ({title[1]})" if title else ""))]
    return {}, []


# ------------------------------------------------------------------ the area table, row by row, and the lot ledger

def area_table_rows(docs: list[Doc]) -> tuple[list[dict], dict | None, dict | None]:
    """(rows, printed_total, where) from an area table "מבנה | מס יח"ד | עיקרי | אחוז | שירות | אחוז | סה"כ" (one row per
    building). Columns are read by position: a row is [total, service%, service, main%, main, units, lot, building]
    left to right. Values are kept as Decimal (source precision)."""
    from decimal import Decimal, InvalidOperation
    for doc in docs:
        if not doc.find(r"אחוז.{0,3}מעיקרי|מעיקרי"):
            continue
        try:
            pdf = pymupdf.open(str(doc.path))
        except Exception:  # noqa: BLE001
            continue
        with pdf:
            for pno, page in enumerate(pdf, 1):
                lines: dict[int, list] = {}
                for w in page.get_text("words"):
                    lines.setdefault(round((w[1] + w[3]) / 6), []).append(w)
                rows, printed = [], None
                for k in sorted(lines):
                    toks = [norm(w[4]) for w in sorted(lines[k], key=lambda w: w[0])]
                    try:
                        if len(toks) == 8 and re.fullmatch(r"\d{2,3}(-\d{2,3})?", toks[7]):
                            rows.append({"building": toks[7], "units": int(toks[5]), "main": Decimal(toks[4]),
                                         "service": Decimal(toks[2]), "total": Decimal(toks[0])})
                        elif rows and toks[-1:] == ["סה"] and len(toks) >= 6:
                            nums = [x for x in toks if re.fullmatch(r"[\d.]+%?", x)]
                            printed = {"total": Decimal(nums[0]), "service": Decimal(nums[2]), "main": Decimal(nums[4]),
                                       "units": int(nums[5])}
                    except (InvalidOperation, ValueError, IndexError):
                        continue
                if len(rows) >= 3:
                    return rows, printed, {"doc": doc, "page": pno}
    return [], None, None


def load_ledger(gush: str | None, cell: str | None) -> dict | None:
    if not gush or not cell:
        return None
    path = Path(settings.knowledge_dir, "lots", f"hof_ashkelon_{gush}_{cell}.yaml")
    if not path.exists():
        return None
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def request_units(ctx) -> tuple[int, int] | None:
    text = " ".join(str(x) for x in (ctx.declared.get("description"), ctx.title) if x)
    m = re.search(r"(?<!\d)(\d{3})\s*[-–+]\s*(\d{3})(?!\d)", text)
    return tuple(sorted((int(m.group(1)), int(m.group(2))))) if m else None


def r_table_arithmetic(ctx):
    rows, printed, where = area_table_rows(ctx.docs)
    if not rows or not printed:
        return None
    sums = {k: sum((r[k] for r in rows), start=type(rows[0][k])(0)) for k in ("main", "service", "total", "units")}
    diffs = {k: abs(sums[k] - printed[k]) for k in sums}
    quote = (f"{len(rows)} שורות: עיקרי {sums['main']}, שירות {sums['service']}, סה\"כ {sums['total']}, {sums['units']} יח\"ד; "
             f"מודפס: עיקרי {printed['main']}, שירות {printed['service']}, סה\"כ {printed['total']}")
    e = [ev(where["doc"], where["page"], quote)]
    bad = [k for k, d in diffs.items() if d > (0 if k == "units" else type(d)("0.05"))]
    if not bad:
        return Resolution("PASS", f"סכום {len(rows)} השורות תואם את שורת הסה\"כ ({sums['units']} יח\"ד).", e)
    he = {"main": "עיקרי", "service": "שירות", "total": "סה\"כ", "units": "יח\"ד"}
    return Resolution("FAIL", "סכום השורות בטבלת השטחים אינו תואם את הסה\"כ המודפס: " + "; ".join(
        f"{he[k]} — סכום {sums[k]} מול {printed[k]} (הפרש {diffs[k]})" for k in bad) + ".", e)


def r_table_vs_registry(ctx):
    ledger = load_ledger(ctx.gush, ctx.cell)
    rows, printed, where = area_table_rows(ctx.docs)
    if not ledger or not rows:
        return None
    from decimal import Decimal
    by_building = {r["building"]: r for r in rows}
    conflicts, checked, misfiled = [], 0, []
    for rec in ledger["records"]:
        if rec["role"] != "new_dwelling" or len(rec.get("units") or []) != 2:
            continue
        row = by_building.get(f"{min(rec['units'])}-{max(rec['units'])}")
        if not row or rec.get("primary_m2") is None:
            continue
        checked += 1
        p = Decimal(rec["primary_m2"])
        if "total_in_primary" in rec.get("flags", []):
            if abs(p - row["total"]) > Decimal("0.05"):
                conflicts.append(f"{row['building']}: במאגר {p} (שדה עיקרי, כנראה סה\"כ) מול סה\"כ {row['total']} בטבלה (בקשה {rec['application_id']})")
            else:
                misfiled.append(row["building"])
            continue
        s = Decimal(rec["service_m2"]) if rec.get("service_m2") is not None else None
        diff = []
        if abs(p - row["main"]) > Decimal("0.05"):
            diff.append(f"עיקרי {row['main']} בטבלה מול {p} במאגר")
        if s is not None and abs(s - row["service"]) > Decimal("0.05"):
            diff.append(f"שירות {row['service']} בטבלה מול {s} במאגר")
        if diff:
            conflicts.append(f"יחידות {row['building']}: " + ", ".join(diff) + f" (בקשה {rec['application_id']})")
    if not checked:
        return None
    src = ev(where["doc"], where["page"], f"השוואת {checked} מבנים חדשים בטבלת השטחים לבקשות במאגר הוועדה (צילום 25.11.2026)")
    note = f" במאגר, שדה השטח העיקרי של {', '.join(misfiled)} מכיל את סה\"כ השטח — רישום שגוי במאגר, ללא סתירה לטבלה." if misfiled else ""
    if conflicts:
        return Resolution("FAIL", "סתירה בין טבלת השטחים לבין השטחים הרשומים במאגר הוועדה: " + "; ".join(conflicts) + "." + note, [src])
    return Resolution("PASS", f"שטחי {checked} המבנים החדשים בטבלה תואמים את הרשום במאגר הוועדה." + note, [src])


def r_registry_status(ctx):
    ledger, units = load_ledger(ctx.gush, ctx.cell), request_units(ctx)
    if not ledger or not units:
        return None
    rec = next((r for r in ledger["records"] if tuple(sorted(r.get("units") or [])) == units), None)
    if not rec:
        return None
    e = [{"type": "document", "file": "מאגר הוועדה", "page": None, "method": "צילום מצב של מאגר הבקשות",
          "quote": f"בקשה {rec['application_id']} (יחידות {units[0]}-{units[1]}): {rec['status']} — {rec['source_url']}"}]
    if "לא תקינה" in (rec["status"] or ""):
        return Resolution("FAIL", f"במאגר הוועדה הבקשה ({rec['application_id']}) בסטטוס \"{rec['status']}\" — הבקרה המרחבית של הוועדה "
                                  "קבעה שהבקשה אינה תקינה; הסיבה לא פורסמה במאגר.", e)
    return Resolution("PASS", f"במאגר הוועדה הבקשה ({rec['application_id']}) בסטטוס \"{rec['status']}\".", e)


# ------------------------------------------------------------------ facts: the survey map's date

def survey_file_date(files) -> tuple[str | None, list[dict]]:
    """Latest date a survey could have been made: a survey DWFX is a ZIP package whose entries carry the time the
    surveyor exported it, and a survey is never newer than its own file. (No rendering — only the ZIP directory.)"""
    import datetime as _dt
    import zipfile
    best = None
    for f in files:
        if f.doc_type != "survey_map" or f.kind != "dwfx":
            continue
        try:
            with zipfile.ZipFile(f.storage_path) as z:
                stamps = [_dt.date(*i.date_time[:3]) for i in z.infolist() if i.date_time[0] >= 2000]
        except (OSError, zipfile.BadZipFile, ValueError):
            continue
        if stamps and (best is None or max(stamps) > best[0]):
            best = (max(stamps), f.filename)
    if not best:
        return None, []
    d, name = best
    return d.isoformat(), [{"type": "document", "file": name, "page": None, "method": "תאריך יצירת קובץ המדידה",
                            "quote": f"קובץ המדידה נוצר ב־{d.strftime('%d.%m.%Y')}; המדידה אינה מאוחרת מתאריך זה"}]


# ------------------------------------------------------------------ the plan's sheets, as read on the AI PC

def drawing_facts(files) -> tuple[dict, dict]:
    """What agent/drawing_reader.py found on the DWFX plan (stored on the file as ingest_report.drawing_read):
    (drawing, facts). drawing = {"file", "views", "parking", "solar", "shed", "height", "evidence": {fact: [...]}}."""
    for f in files:
        read = (f.ingest_report or {}).get("drawing_read") or {}
        if f.doc_type != "architectural_plan" or read.get("state") != "done":
            continue
        drawing = {"file": f.filename, "views": read.get("views") or {}, "parking": read.get("parking") or [],
                   "solar": read.get("solar") or {}, "shed": read.get("shed") or [], "height": read.get("height"),
                   "evidence": {}}
        facts = {}
        h = read.get("height") or {}
        if h.get("value_m") is not None:
            # the accepted ridge (read twice) — but a single higher ridge reading may be the real top that was read
            # only once, so the height checked is the highest plausible ridge read anywhere (never too low)
            single = [x for x in (r.get("ridge") for r in read.get("levels_read") or [])
                      if isinstance(x, (int, float)) and 2 <= x <= 20]
            top = max([float(h["value_m"]), *single])
            facts["building_height_m"] = top
            if h.get("roof_type") in ("tiled", "flat"):
                facts["roof_type"] = h["roof_type"]           # the height limit depends on it (9 m tiled, 8 m flat)
            r0 = (h.get("readings") or [{}])[0]
            zero = f" (±0.00 = {h['zero_abs']:.2f})" if h.get("zero_abs") else ""
            also = f"; הרום הגבוה ביותר שנקרא: +{top:.2f}" if top > float(h["value_m"]) else ""
            drawing["evidence"]["building_height_m"] = [{
                "type": "document", "file": f.filename, "page": r0.get("sheet"), "method": "קריאת שרטוט (מודל תמונה מקומי)",
                "quote": f"רום רכס הגג בחתך/חזית: +{h['value_m']:.2f} (נקרא פעמיים){also}{zero}; גג {('רעפים' if h.get('roof_type') == 'tiled' else 'שטוח' if h.get('roof_type') == 'flat' else 'לא זוהה')}"}]
        return drawing, facts
    return {}, {}


def _sheets(hits: list[dict]) -> str:
    return ", ".join(str(s) for s in sorted({h["sheet"] for h in hits}))


def _drawing_ev(ctx, page, quote):
    return [{"type": "document", "file": ctx.drawing["file"], "page": page, "quote": quote,
             "method": "קריאת שרטוט (מודל תמונה מקומי)"}]


# ------------------------------------------------------------------ resolvers (qualitative / condition rules)

def _first(docs, *patterns, types: tuple[str, ...] | None = None):
    for d in docs:
        if types and d.doc_type not in types:
            continue
        hit = d.find(*patterns)
        if hit:
            return d, hit
    return None, None


def r_antiquities(ctx):
    d, hit = _first(ctx.docs, r"רשות העתיקות", r"אינה מתנגדת|אישור לביצוע עבודות")
    if d:
        q = d.find(r"אינה מתנגדת") or hit
        return Resolution("PASS", f"צורף אישור רשות העתיקות ({d.filename}): הרשות אינה מתנגדת לביצוע העבודות.", [ev(d, q[0], q[1])])
    return None


def r_electric(ctx):
    d, hit = _first(ctx.docs, r"חשמל", r"אינו נדרש כתנאי")
    if d:
        q = d.find(r"אינו נדרש כתנאי")
        return Resolution("PASS", "לפי תגובת חברת החשמל בתיק המידע להיתר, אישורה אינו נדרש כתנאי למתן היתר.", [ev(d, q[0], q[1])])
    d, hit = _first(ctx.docs, r"חברת החשמל|חח\"?י", r"אישור|מאשר", types=("electric_company_approval",))
    if d:
        return Resolution("PASS", f"צורף אישור/תיאום חברת החשמל ({d.filename}).", [ev(d, hit[0], hit[1])])
    return None


def r_wells(ctx):
    resp, hit = _first(ctx.docs, r"רדיוס מגן", r"מקורות")
    if not resp:
        return None
    for d in ctx.docs:      # a Mekorot letter for this request: "אין התנגדות" from Mekorot, dated 2025 or later
        q = d.find(r"(?:לחברת )?['\"]*מקורות['\"]* אין התנגדות|מקורות[^.]{0,60}אין התנגדות")
        if q and re.search(r"20(2[5-9])", " ".join(d.pages)):
            return Resolution("PASS", f"צורף אישור מקורות לבקשה ({d.filename}).", [ev(d, q[0], q[1])])
    arc = next((d for d in ctx.docs if d.find(r"מקורות.{0,200}תנאי לפתיחת בקשה")), None)
    evidence = [ev(resp, hit[0], hit[1])]
    if arc:
        q = arc.find(r"מקורות.{0,200}תנאי לפתיחת בקשה")
        evidence.append(ev(arc, q[0], q[1]))
    return Resolution("FAIL", "המגרש בתחום רדיוסי המגן של קידוחי מקורות (שקמה 7–9); נדרשים אישור מקורות ואישור משרד הבריאות, "
                              "ובתיק אין אישור מקורות בתוקף לבקשה זו.", evidence)


def r_hfc(ctx):
    for d in ctx.docs:      # an approval issued BY the Home Front Command — not a plan or form that requires one
        if d.doc_type in ("permit_info", "planning_regulation", "application_form"):
            continue
        q = d.find(r"פיקוד העורף|פקע\"?ר", r"מאושר|אושר|אישור תכנון|תכנית המיגון אושרה")
        if q and (re.search(r"פקע|פיקוד|\.sign", d.filename) or "פיקוד העורף" in d.pages[0][:600]):
            return Resolution("PASS", f"צורף אישור פיקוד העורף ({d.filename}).", [ev(d, q[0], q[1])])
    arc = next((x for x in ctx.docs if x.find(r"פיקוד העורף לממ.?.?ד")), None)
    q = arc.find(r"פיקוד העורף לממ.?.?ד") if arc else None
    return Resolution("FAIL", "לא צורף אישור פיקוד העורף לפתרון המיגון (ממ\"ד); לפי דרישות הוועדה זהו תנאי בשלב בקרת התכן.",
                      [ev(arc, q[0], q[1])] if arc else [])


def r_binui_plan(ctx):
    d, hit = _first(ctx.docs, r"היתר לפיתוח המגרש\s*\d+")
    if d:
        return Resolution("PASS", "תיק המידע להיתר מציין היתר פיתוח למגרש (תשתיות, גבהים, חנייה, אשפה, תאורה).", [ev(d, hit[0], hit[1])])
    return None


def r_demolition(ctx):
    cell = str(ctx.cell or "")
    plan = sorted(Path(settings.knowledge_dir, "source_texts", "ha_633_0723718", "ocr").glob("approved_2021_p*.txt"))
    for p in plan:
        t = norm(p.read_text(encoding="utf-8"))
        rows = re.findall(r"מבנה להריסה[^\n]*?(\d{3})\s*$", t, re.M)
        if rows:
            page = int(re.search(r"p(\d+)", p.stem).group(1))
            if cell and cell not in rows:
                return Resolution("PASS", f"לפי טבלת ייעודי הקרקע בהוראות התכנית, מבנים להריסה מסומנים רק בתאי שטח {', '.join(sorted(set(rows)))} — "
                                          f"לא בתא {cell}.", [ev(None, page, "; ".join(f"מבנה להריסה — תא {r}" for r in rows), "תכנית 633-0723718 — הוראות (מאושרת)")])
            if cell in rows:
                return Resolution("FAIL", f"בתא שטח {cell} מסומן מבנה להריסה; הריסתו תנאי להיתר.", [ev(None, page, f"מבנה להריסה — תא {cell}", "תכנית 633-0723718 — הוראות (מאושרת)")])
    return None


def r_waste(ctx):
    for d in ctx.docs:      # a waste estimate or disposal contract — not the plan's general sanitation clause
        if d.doc_type in ("permit_info", "planning_regulation"):
            continue
        q = d.find(r"כמות (?:ה)?פסולת|חישוב (?:כמות )?פסולת|פינוי פסולת בניין|עודפי עפר")
        if q:
            return Resolution("PASS", f"צורף חישוב/אישור פינוי פסולת בניין ({d.filename}).", [ev(d, q[0], q[1])])
    return Resolution("FAIL", "לא צורף חישוב מוערך של כמות פסולת בניין ועודפי עפר ואישור פינוי לאתר מוסדר (סעיף 6.1ח בתכנית).")


def r_sewage(ctx):
    d, hit = _first(ctx.docs, r"נספח סניטרי", r"קבצים מצורפים \(1\)|\(1\) קבצים מצורפים|סניטרי", types=("application_form",))
    if d:
        return Resolution("PASS", "טופס הבקשה כולל נספח סניטרי (תכנית חיבור לביוב) לאישור מהנדס הוועדה.", [ev(d, hit[0], hit[1])])
    return None


def r_betterment(ctx):
    d, hit = _first(ctx.docs, r"חבות בהיטל השבחה|מחייבת בתשלום היטל השבחה|היטל השבחה.{0,40}כן")
    if d:
        q = hit
        return Resolution("FAIL", "הבקשה חייבת בהיטל השבחה; התשלום או הבטחתו טרם הוצגו — תנאי למתן היתר.", [ev(d, q[0], q[1])])
    return None


def r_trees(ctx):
    v = ctx.declared.get("trees_within_4m")
    if v is False:
        d, hit = _first(ctx.docs, r"4 מטרים מעץ|מטרים מעץ", types=("application_form",))
        return Resolution("PASS", "בטופס הבקשה הוצהר שאין עבודה בטווח 4 מ׳ מעץ בוגר.", [ev(d, hit[0], hit[1])] if d else [])
    return None


def r_building_form(ctx):
    desc = " ".join(str(x) for x in (ctx.declared.get("description"), ctx.title) if x)
    if re.search(r"דו[ \-]?משפחתי|חד[ \-]?משפחתי|רב[ \-]?משפחתי", desc):
        d, hit = _first(ctx.docs, r"דו משפחתי|חד משפחתי|רב משפחתי", types=("application_form",))
        return Resolution("PASS", "לפי מהות הבקשה: " + desc.strip()[:120], [ev(d, hit[0], hit[1])] if d else [])
    return None


def r_coverage(ctx):
    pct = ctx.facts_from_docs.get("cell_total_pct")
    if pct is not None and pct <= 50:
        return Resolution("PASS", f"סך שטחי הבנייה בתא השטח הם {pct}% משטח התא; התכסית (שטח קומת הקרקע) קטנה מסך השטחים, "
                                  "ולכן אינה עולה על 50%.", ctx.area_evidence)
    return None


def _drawing_views(view_he: str, key: str):
    """Sections / elevations live on the plan's sheets. Once the AI PC has read the plan, they are found or not;
    before that, a DWFX plan (labels drawn as lines, no CAD layers) leaves the item undecided — never "missing"."""
    def r(ctx):
        if ctx.drawing:
            hits = ctx.drawing["views"].get(key) or []
            if len(hits) >= 2 or (hits and any(x.get("sheet") == hits[0]["sheet"] for x in (ctx.drawing.get("height") or {}).get("readings", []))):
                return Resolution("PASS", f"{view_he} מופיעים בתכנית ההגשה ({ctx.drawing['file']}, גיליון {_sheets(hits)}).",
                                  _drawing_ev(ctx, hits[0]["sheet"], f"זוהו {view_he} בגיליון {_sheets(hits)} ({len(hits)} אזורים)"))
            if not hits:
                return Resolution("FAIL", f"לא נמצאו {view_he} בגיליונות תכנית ההגשה ({ctx.drawing['file']}).")
        plan = next((d for d in ctx.docs if d.doc_type == "architectural_plan" and ".converted" in d.path.name), None)
        if plan:
            return Resolution("UNCERTAIN", f"התכנית הוגשה כ־DWFX ({plan.filename}, {len(plan.pages)} גיליונות); "
                                           f"{view_he} מופיעים בגיליונות התכנית ולא כקובץ נפרד — טרם נקראו.")
        return None
    return r


def r_parking(ctx):
    if ctx.drawing and ctx.drawing["parking"]:
        hits = ctx.drawing["parking"]
        return Resolution("PASS", f"מקומות חנייה מסומנים בתכנית (גיליון {_sheets(hits)}).",
                          _drawing_ev(ctx, hits[0]["sheet"], f"זוהו מקומות חנייה מסומנים בגיליון {_sheets(hits)}"))
    return None


def r_pv(ctx):
    if not ctx.drawing:
        return None
    roof, ground = ctx.drawing["solar"].get("roof") or [], ctx.drawing["solar"].get("ground") or []
    if roof and not ground:
        return Resolution("PASS", f"מתקנים פוטו־וולטאיים מסומנים על הגג (גיליון {_sheets(roof)}).",
                          _drawing_ev(ctx, roof[0]["sheet"], f"פאנלים סולריים על הגג, גיליון {_sheets(roof)}"))
    if not roof and not ground:
        return Resolution("PASS", "לא מוצעים מתקנים פוטו־וולטאיים מחוץ לגג; לא זוהו פאנלים בתכנית.")
    return None


def r_shed(ctx):
    if ctx.drawing and not ctx.drawing["shed"]:
        return Resolution("PASS", "לא מוצע מחסן בתכנית ההגשה — אין מחסן לבדוק.")
    return None


RESOLVERS = {
    "QA-REQ-SECTIONS": _drawing_views("חתכים", "section"), "QA-REQ-ELEVATIONS": _drawing_views("חזיתות", "elevation"),
    "HA-368-REGISTRY-STATUS": r_registry_status, "HA-368-TABLE-ARITHMETIC": r_table_arithmetic,
    "HA-368-TABLE-VS-REGISTRY": r_table_vs_registry,
    "HA-633-PARKING": r_parking, "HA-633-PV-ROOF": r_pv, "HA-633-SHEDS": r_shed,
    "HA-633-ANTIQUITIES": r_antiquities, "HA-633-COND-ELECTRIC": r_electric, "HA-633-COND-WELLS": r_wells,
    "HA-633-COND-HFC": r_hfc, "HA-633-COND-BINUI-PLAN": r_binui_plan, "HA-633-COND-DEMOLITION": r_demolition,
    "HA-633-WASTE-ESTIMATE": r_waste, "HA-633-SEWAGE": r_sewage, "HA-633-BETTERMENT-LEVY": r_betterment,
    "HA-633-TREES-4M": r_trees, "HA-633-BUILDING-FORM": r_building_form, "HA-633-COVERAGE-CELL": r_coverage,
}


@dataclass
class Context:
    docs: list[Doc]
    declared: dict
    title: str
    cell: str | None
    facts_from_docs: dict
    area_evidence: list[dict]
    drawing: dict = field(default_factory=dict)
    gush: str | None = None


def document_facts(files) -> tuple[list[Doc], dict, list[dict]]:
    docs = load_docs(files)
    facts, evidence = area_table_facts(docs)
    if facts:
        facts["cell_total_pct"] = round(facts["cell_main_pct"] + facts["cell_service_pct"], 2)
    return docs, facts, evidence


def resolve(results: list, docs: list[Doc], declared: dict, title: str, facts_from_docs: dict, area_evidence: list[dict],
            drawing: dict | None = None, gush: str | None = None) -> int:
    """Answer open findings in place; returns how many were resolved."""
    cell = None                     # the plan cell: "משטח מגרש 368" (also extracted as "368 משטח מגרש") or "מגרש 368 מתכנית"
    for d in docs:
        for t in d.pages[:3]:
            flat = re.sub(r"\s+", " ", t)
            m = (re.search(r"משטח מגרש\s*(\d{3})", flat) or re.search(r"(\d{3})\s*משטח מגרש", flat)
                 or re.search(r"מגרש\s*(\d{3})\s*מתכנית", flat))
            if m:
                cell = m.group(1)
                break
        if cell:
            break
    ctx = Context(docs, declared, title, cell, facts_from_docs, area_evidence, drawing or {}, gush)
    n = 0
    for r in results:
        fn = RESOLVERS.get(r.rule_id)
        # open findings, and FAILs of document rules: a document filed under another type ("אחר") is still there
        if not fn or r.status not in ("UNCERTAIN", "FAIL"):
            continue
        res = fn(ctx)
        if not res:
            continue
        # a FAIL is only reversed by a document that shows the requirement is met, or — for a drawing that the system
        # cannot read yet — made undecided (never PASS without evidence)
        if r.status == "FAIL" and not ((res.status == "PASS" and res.evidence) or res.status == "UNCERTAIN"):
            continue
        r.computed_result = res.status
        r.status = "UNCERTAIN" if res.status == "FAIL" and "RULE_NOT_APPROVED" in r.flags else res.status
        if res.status == "UNCERTAIN":
            r.explanation_he = res.explanation_he
            r.flags = [f for f in r.flags if f != "RESOLVED_FROM_DOCUMENTS"] + ["NEEDS_DRAWING_READ"]
            continue
        r.explanation_he = res.explanation_he
        r.evidence = list(r.evidence or []) + res.evidence
        r.flags = [f for f in r.flags if f not in ("REVIEW_REQUIRED", "INCOMPLETE")] + ["RESOLVED_FROM_DOCUMENTS"]
        r.confidence = 0.9 if res.evidence else 0.75
        n += 1
    return n
