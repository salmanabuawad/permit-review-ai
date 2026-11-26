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

import hashlib
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
    status: str                            # PASS | FAIL | NA | UNCERTAIN
    explanation_he: str
    evidence: list[dict] = field(default_factory=list)
    # review status when it is not the default for the rule (services.review_status): CONFIRMED_DEFECT,
    # DOCUMENTED_DISCREPANCY, UNRESOLVED, NOT_CHECKED, FUTURE_STAGE
    review: str | None = None
    # sub-findings, each its own line in the defects report: {review, title_he, found_he, expected_he, diff,
    # where_he, correction_he, impact_he, evidence: [...]}
    items: list[dict] = field(default_factory=list)
    internal: bool = False                 # kept out of the external defects report (stays in the audit record)
    reject_basis: bool = False             # a confirmed substantive ground for a rejection recommendation


def ev(doc: Doc | None, page: int | None, quote: str, source: str | None = None) -> dict:
    return {"type": "document", "file": doc.filename if doc else source, "page": page, "quote": quote,
            "method": "קריאת מסמך בתיק" if doc else "קריאת מקור תכנוני"}


TEXT_ALGORITHM = ("pdf_text", "1")         # pymupdf get_text + repair_shifted_font + norm; bump when that changes


def _pages(path: Path) -> list[str]:
    from ..intake.text import repair_shifted_font          # Rishui Zamin "מידע להיתר" uses a shifted font
    with pymupdf.open(str(path)) as d:
        return [norm(repair_shifted_font(p.get_text())) for p in d]


def load_docs(files, cache=None) -> list[Doc]:
    """Text of every readable case file: PDFs, and DWFX drawings once converted to PDF on the AI PC.
    `cache(sha256, compute) -> dict` (services: the derivation cache) reuses a document's text across runs and cases."""
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
            sha = getattr(f, "sha256", None)
            if cache and sha:
                # a converted DWFX is keyed by the original's hash plus the converted file's name
                key = sha if f.kind == "pdf" else hashlib.sha256((sha + path.name).encode()).hexdigest()
                pages = cache(key, lambda: {"pages": _pages(path)})["pages"]
            else:
                pages = _pages(path)
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
    # each row is printed to 2 decimals, so the sum of n rounded rows may differ from the exact total by up to n × 0.005
    tol = type(rows[0]["main"])("0.005") * len(rows)
    bad = [k for k, d in diffs.items() if d > (0 if k == "units" else tol)]
    if not bad:
        within = [k for k, d in diffs.items() if d and k != "units"]
        note = (f" הפרשים קטנים ({', '.join(f'{k} {diffs[k]}' for k in within)}) בתוך שגיאת העיגול של {len(rows)} שורות "
                f"ב־2 ספרות (עד {tol}).") if within else ""
        return Resolution("PASS", f"סכום {len(rows)} השורות תואם את שורת הסה\"כ ({sums['units']} יח\"ד).{note}", e)
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
        items = [{"review": "DOCUMENTED_DISCREPANCY", "title_he": "פער בין טבלת הזכויות המצטברת לבין מאגר הוועדה",
                  "found_he": c, "where_he": "טבלת חישוב השטחים של מגרש 368; מאגר הבקשות של הוועדה",
                  "impact_he": "הערך משמש במאזן הזכויות המצטבר שצורף לבקשה; לא הוכרע איזה מקור מעודכן. אין לייחס את הפער לעורך הבקשה.",
                  "correction_he": "להציג אסמכתה לערך שבטבלה או לעדכן את הטבלה."} for c in conflicts]
        return Resolution("FAIL", "פער בין טבלת השטחים לבין השטחים הרשומים במאגר הוועדה: " + "; ".join(conflicts) + "." + note, [src],
                          review="DOCUMENTED_DISCREPANCY", items=items)
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
        return Resolution("FAIL", internal=True, review="DOCUMENTED_DISCREPANCY", explanation_he= f"במאגר הוועדה הבקשה ({rec['application_id']}) בסטטוס \"{rec['status']}\" — הבקרה המרחבית של הוועדה "
                                  "קבעה שהבקשה אינה תקינה; הסיבה לא פורסמה במאגר. (סטטוס רשמי — אינו ראיה עצמאית ואינו בסיס להמלצה.)", evidence=e)
    return Resolution("PASS", f"במאגר הוועדה הבקשה ({rec['application_id']}) בסטטוס \"{rec['status']}\".", e, internal=True)


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
                   "area_geometry": read.get("area_geometry"), "screening": read.get("screening"),
                   "floor_geometry": read.get("floor_geometry"), "elevation_geometry": read.get("elevation_geometry"),
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
            if top > float(h["value_m"]):         # the highest value rests on one reading only
                facts["building_height_corroborated_m"] = float(h["value_m"])
            if h.get("roof_type") in ("tiled", "flat"):
                facts["roof_type"] = h["roof_type"]           # the height limit depends on it (9 m tiled, 8 m flat)
            r0 = (h.get("readings") or [{}])[0]
            zero = f" (±0.00 = {h['zero_abs']:.2f})" if h.get("zero_abs") else ""
            also = f"; הרום הגבוה ביותר שנקרא: +{top:.2f}" if top > float(h["value_m"]) else ""
            drawing["evidence"]["building_height_m"] = [{
                "type": "document", "file": f.filename, "page": r0.get("sheet"), "method": "קריאת שרטוט (מודל תמונה מקומי)",
                "quote": f"רום רכס הגג בחתך/חזית: +{h['value_m']:.2f} (נקרא פעמיים){also}{zero}; גג {('רעפים' if h.get('roof_type') == 'tiled' else 'שטוח' if h.get('roof_type') == 'flat' else 'לא זוהה')}"}]
        eg = (read.get("elevation_geometry") or {}).get("summary") or {}
        if eg.get("max_top_above_lowest_slab_m") is not None and eg.get("sections_measured"):
            facts["building_height_geometric_m"] = eg["max_top_above_lowest_slab_m"]
            facts["building_height_geometric_u_m"] = round((eg.get("uncertainty_m") or 0) + (eg.get("finish_allowance_m") or 0), 3)
            drawing["evidence"]["building_height_geometric_m"] = [{
                "type": "measurement", "file": f.filename, "page": None,
                "method": "מדידה גאומטרית בחתכים (elevation_geometry)",
                "quote": f"הנקודה הגבוהה בחתכים: {eg['max_top_above_lowest_slab_m']:.2f} מ׳ מעל פני פלטת קומת הקרקע "
                         f"({eg['sections_measured']} חתכים, {eg.get('slab_levels_max')} מפלסי פלטה, קומה {', '.join(f'{x:.2f}' for x in eg.get('floor_to_floor_m', []))} מ׳)"}]
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


# ------------------------------------------------------------------ areas: declared (A) vs the submitted diagrams (B)

def _fmt(x) -> str:
    return f"{x:.2f}"


def r_area_diagrams(ctx):
    """Three-way area check, sources A and B: the areas declared in the request against the area-calculation diagrams
    measured by agent/area_geometry.py (vector polygons, scale from the DWFX package). Source C — areas reconstructed
    from the floor plans' walls — is not implemented; the result says so."""
    g = (ctx.drawing or {}).get("area_geometry") or {}
    t = g.get("totals")
    main, service = ctx.declared.get("main_area_m2"), ctx.declared.get("service_area_m2")
    if not t or main is None or service is None:
        return None
    diags = [d for s in g.get("sheets", []) for d in s.get("diagrams", [])]
    sheet = next((s for s in g.get("sheets", []) if s.get("diagrams")), {})
    measured = {"main": t["primary"], "service": t["service"], "total": t["total"]}
    declared = {"main": float(main), "service": float(service), "total": round(float(main) + float(service), 2)}
    # declared values are printed to 2 decimals; polygons are exact to the plot's integer units (≪ 0.01 m²)
    tol = {k: 0.01 + 0.00005 * declared[k] for k in declared}
    he = {"main": "עיקרי", "service": "שירות", "total": "סה\"כ"}
    quote = (f"נמדד מ־{len(diags)} תרשימי חישוב שטחים (גיליון {sheet.get('sheet')}, יחידת מודל {sheet.get('model_unit')}): "
             f"עיקרי {measured['main']:.3f} (כולל {t['primary_from_protected_room']:.2f} מרצפת ממ\"ד מעבר ל־9 מ\"ר נטו), "
             f"שירות {measured['service']:.3f} (רצפת ממ\"ד {t['protected_room_floor'] - t['primary_from_protected_room']:.2f}, "
             f"קירות ממ\"ד {t['protected_room_walls']:.3f}, סככות {t['covered_service']:.3f}), סה\"כ {measured['total']:.3f}")
    e = [{"type": "measurement", "file": next((f for f in [ctx.drawing.get("file")] if f), None), "page": sheet.get("sheet"),
          "method": "מדידה גיאומטרית דטרמיניסטית (Shapely) של פוליגוני התרשים; קנ\"מ מטרנספורמציית חבילת ה-DWFX",
          "quote": quote, "algorithm": g.get("algorithm"), "file_sha256": g.get("file_sha256")}]
    items = []
    for k in ("main", "service", "total"):
        d = round(measured[k] - declared[k], 3)
        if abs(d) > tol[k]:
            items.append({"review": "CONFIRMED_DEFECT", "title_he": f"שטח {he[k]} המוצהר אינו תואם את תרשימי חישוב השטחים",
                          "found_he": f"שטח {he[k]} מוצהר {declared[k]:.2f} מ\"ר; נמדד בתרשימים {measured[k]:.3f} מ\"ר",
                          "diff": f"{d:+.3f} מ\"ר", "where_he": f"תרשימי חישוב השטחים, גיליון {sheet.get('sheet')}",
                          "correction_he": "לתקן את טבלת השטחים או את תרשימי החישוב כך שיתאימו.", "evidence": e})
    for i, d in enumerate(diags, 1):
        for o in d.get("overlaps", []):
            items.append({"review": "CONFIRMED_DEFECT", "title_he": "פוליגונים חופפים בתרשים חישוב השטחים",
                          "found_he": f"תרשים {i}: חפיפה של {o['m2']:.3f} מ\"ר בין {o['a']} ל־{o['b']} — שטח שנספר פעמיים",
                          "where_he": f"גיליון {d['sheet']}, תרשים {i}", "correction_he": "לתקן את גבולות הפוליגונים.", "evidence": e})
        for cat, m2 in (d.get("double_counted_m2") or {}).items():
            items.append({"review": "CONFIRMED_DEFECT", "title_he": "שטח שנספר פעמיים בתרשים חישוב השטחים",
                          "found_he": f"תרשים {i}: {m2:.3f} מ\"ר בקטגוריה {cat} מכוסים ביותר מפוליגון אחד",
                          "where_he": f"גיליון {d['sheet']}, תרשים {i}", "correction_he": "להסיר את הכפילות.", "evidence": e})
    # protected-room classification under the committee's own guideline (12.5 m² gross as service): unresolved, internal
    gross = [round(d["area_m2"].get("protected_room_floor", 0) + d["area_m2"].get("protected_room_walls", 0), 2)
             for d in diags if d["area_m2"].get("protected_room_floor")]
    over = [x for x in gross if x > 12.5]
    if over:
        items.append({"review": "UNRESOLVED", "internal": True, "title_he": "סיווג שטח הממ\"ד",
                      "found_he": f"ממ\"ד ברוטו {', '.join(_fmt(x) for x in gross)} מ\"ר; בהנחיות הוועדה (HA-ED8592A090) הממ\"ד נחשב "
                                  "שירות עד 12.5 מ\"ר ברוטו, ובתרשים נחשבו כשירות 9.00 מ\"ר נטו + הקירות. מעמדה המשפטי של "
                                  "ההנחיה ותחולתה לא אומתו — הסיווג לא הוכרע.",
                      "where_he": "תרשימי קומת הקרקע", "evidence": e})
    same = [i for i, d in enumerate(diags, 1) if d.get("same_as")]
    note = (f" {len(same)} מהתרשימים חוזרים על יחידה אחרת (יחידה ראי/העתק) באותם שטחים." if same else "")
    c_note = (" מקור ג׳ — שטחי הקומות מקירות התכניות — נבדק בכלל נפרד (HA-AREA-FLOORPLANS)." if (ctx.drawing or {}).get("floor_geometry")
              else " מקור ג׳ — שחזור השטחים מקירות תכניות הקומות — לא בוצע; התאמה בין המוצהר לתרשימים אינה מוכיחה עמידה בזכויות.")
    if any(x["review"] == "CONFIRMED_DEFECT" for x in items):
        return Resolution("FAIL", "תרשימי חישוב השטחים אינם תואמים את השטחים המוצהרים או מכילים כפילות: " + "; ".join(
            x["found_he"] for x in items if x["review"] == "CONFIRMED_DEFECT") + "." + c_note, e, items=items)
    return Resolution("PASS", f"השטחים המוצהרים תואמים את המדידה הגיאומטרית של {len(diags)} תרשימי חישוב השטחים: "
                              + "; ".join(f"{he[k]} {declared[k]:.2f} מול {measured[k]:.3f}" for k in he)
                              + f"; ללא חפיפות או כפילויות.{note}{c_note}", e, items=items)


# ------------------------------------------------------------------ cumulative table vs the historical permits

def load_permits(gush: str | None, cell: str | None) -> dict | None:
    if not gush or not cell:
        return None
    path = Path(settings.knowledge_dir, "lots", f"hof_ashkelon_{gush}_{cell}_permits.yaml")
    if not path.exists():
        return None
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def r_permit_history(ctx):
    """The request's cumulative rights table against the area tables of the lot's signed historical permits. A row that
    equals a permit's area BEFORE its approved addition is a confirmed defect (an outdated value); any other gap is a
    documented discrepancy (a later permit may explain it)."""
    from decimal import Decimal as D
    hist = load_permits(ctx.gush, ctx.cell)
    rows, printed, where = area_table_rows(ctx.docs)
    if not hist or not rows:
        return None
    by_building = {r["building"]: r for r in rows}
    items, checked = [], 0
    for p in hist["permits"]:
        row = by_building.get(p["building"])
        if not row:
            continue
        checked += 1
        t = {k: D(v) for k, v in p["table"].items()}
        e = [ev(where["doc"], where["page"], f"שורת מבנה {p['building']} בטבלה: עיקרי {row['main']}, שירות {row['service']}, סה\"כ {row['total']}"),
             {"type": "document", "file": f"היתר {p['permit']}, מסמך {p['document']}", "page": None, "url": p["source_url"],
              "method": "טבלת השטחים בתכנית ההיתר החתומה (תמלול מאומת בחשבון הטבלה)", "sha256": p["document_sha256"],
              "image": p.get("evidence_crop"),
              "quote": f"עיקרי קיים {t['primary_existing']} + תוספת {t['primary_added']} = {t['primary_total']}; "
                       f"שירות {t['service_total_stated']} (סכום הרכיבים {t['service_components_sum']}); סה\"כ {t['building_total']}"}]
        open_arith = [a["result"] for a in p.get("arithmetic", []) if not a["closes"]]
        if abs(row["main"] - t["primary_total"]) <= D("0.05") and abs(row["total"] - t["building_total"]) <= D("0.05"):
            continue
        stale = t["primary_added"] > 0 and abs(row["main"] - t["primary_existing"]) <= D("0.05")
        d_main = row["main"] - t["primary_total"]
        d_total = row["total"] - t["building_total"]
        found = (f"בטבלה המצטברת שצורפה לבקשה רשומים למבנה {p['building']} {row['main']} מ\"ר עיקרי ו־{row['service']} מ\"ר שירות "
                 f"(סה\"כ {row['total']}); בתכנית ההיתר {p['permit']} השטח העיקרי הכולל הוא {t['primary_total']} מ\"ר "
                 f"וסה\"כ המבנה {t['building_total']} מ\"ר.")
        if stale:
            found += f" הערך שבטבלה ({row['main']}) הוא השטח העיקרי שלפני התוספת שאושרה בהיתר ({t['primary_added']} מ\"ר)."
        if open_arith:
            found += " בתכנית ההיתר עצמה: " + "; ".join(open_arith) + " — סכום השירות שבה אינו נסגר."
        items.append({
            "review": "CONFIRMED_DEFECT" if stale else "DOCUMENTED_DISCREPANCY",
            "title_he": (f"טעות בטבלת ניצול זכויות הבנייה — מבנה {p['building']}" if stale
                         else f"פער בשטחי מבנה {p['building']} מול ההיתר האחרון שנמצא"),
            "found_he": found, "diff": f"עיקרי {d_main:+} מ\"ר; סה\"כ {d_total:+} מ\"ר",
            "where_he": f"טבלת חישוב השטחים של מגרש 368, שורת מבנה {p['building']}; היתר {p['permit']}, מסמך {p['document']}",
            "impact_he": "השטח הוא חלק ממאזן הזכויות המצטבר של המגרש שצורף לבקשה זו.",
            "correction_he": ("לעדכן את מאזן הזכויות המצטבר לשטח שאושר בהיתר, או להציג אסמכתה מאוחרת המיישבת את ההפרש."
                              if stale else "להציג את ההיתר המאוחר שעליו מבוסס הערך שבטבלה, או לתקן את הטבלה."),
            "evidence": e})
    if not checked:
        return None
    if not items:
        return Resolution("PASS", f"שטחי {checked} מבנים בטבלה תואמים את טבלאות ההיתרים ההיסטוריים שנבדקו.", [])
    return Resolution("FAIL", " ".join(x["found_he"] for x in items), [x for it in items for x in it["evidence"]],
                      review="CONFIRMED_DEFECT" if any(x["review"] == "CONFIRMED_DEFECT" for x in items) else "DOCUMENTED_DISCREPANCY",
                      items=items)


# ------------------------------------------------------------------ land: declared parcel vs the attached extracts

def _form_section_files(doc: "Doc", heading: str) -> list[str]:
    """File names attached under a section of the Rishui Zamin form (names are printed reversed: 'pdf.28 חלקה2832 גוש')."""
    for t in doc.pages:
        flat = re.sub(r"\s+", " ", t)
        m = re.search(heading + r"(.{0,400})", flat)
        if m:
            tail = re.split(r"צירוף |\(\d\) קבצים מצורפים(?=.*צירוף)", m.group(1))[0]
            return re.findall(r"pdf\.(\d+)\s*חלקה\s*(\d{4})\s*גוש", tail)
    return []


def r_land_parcel(ctx):
    form = next((d for d in ctx.docs if d.doc_type == "application_form" and d.find(r"הוכחת בעלות")), None)
    if not form:
        return None
    parcels = {(m[1], m[0]) for m in _form_section_files(form, r"הוכחת בעלות")}
    flat = re.sub(r"\s+", " ", " ".join(form.pages))
    dm = re.search(r"(\d{4}):גוש(\d+) :חלקה", flat) or re.search(r"(\d{4}) :גוש(\d+) :חלקה", flat)
    if not dm or not parcels:
        return None
    gush, helka = dm.group(1), dm.group(2)
    q = form.find(r"הוכחת בעלות")
    e = [ev(form, q[0], q[1])]
    if (gush, helka) in parcels:
        return Resolution("PASS", f"נסח המקרקעין שצורף להוכחת הבעלות הוא לגוש {gush} חלקה {helka}, כמוצהר בבקשה.", e)
    other = ", ".join(f"גוש {g} חלקה {h}" for g, h in sorted(parcels))
    rmi = next((d for d in ctx.docs if d.find(r"אינם\s*תואמים לנתוני החוזה|אינם תואמים לנתוני החוזה")), None)
    if rmi:
        rq = rmi.find(r"אינם\s*תואמים")
        e.append(ev(rmi, rq[0], rq[1]))
    found = (f"בטופס הבקשה מוצהרים גוש {gush} חלקה {helka}, אך בסעיף \"צירוף נסח רישום מקרקעין / הוכחת בעלות\" צורף נסח של {other}."
             + (" במכתב רמ\"י נכתב שנתוני הגושים והחלקות שהוזנו אינם תואמים לנתוני החוזה." if rmi else ""))
    return Resolution("FAIL", found, e, review="DOCUMENTED_DISCREPANCY", items=[{
        "review": "DOCUMENTED_DISCREPANCY", "title_he": "אי־התאמה בפרטי המקרקעין", "found_he": found,
        "where_he": f"טופס הבקשה, עמ׳ {q[0]}" + (f"; {rmi.filename}" if rmi else ""),
        "impact_he": "זיהוי המקרקעין שעליהם מבוקש ההיתר.",
        "correction_he": "לצרף נסח לחלקה המוצהרת או לתקן את פרטי המקרקעין בבקשה, ולהבהיר את הקשר לחלקה שצורפה.", "evidence": e}])


def r_rmi_consent(ctx):
    d = next((x for x in ctx.docs if x.find(r"אינה נותנת את הסכמתה|אינה נותנת הסכמתה")), None)
    if d:
        q = d.find(r"אינה נותנת את הסכמתה|אינה נותנת הסכמתה")
        later = d.find(r"לאחר קבלת החלטת ועדת התכנון")
        e = [ev(d, q[0], q[1])] + ([ev(d, later[0], later[1])] if later else [])
        return Resolution("FAIL", f"רמ\"י הודיעה ({d.filename}) שבשלב זה אינה נותנת הסכמה להיתר; הבקשה להסכמה תוגש לאחר החלטת "
                                  "ועדת התכנון — דרישה לשלב מתן ההיתר, לא ליקוי בשלב הבקרה המרחבית.", e, review="FUTURE_STAGE")
    return None


# ------------------------------------------------------------------ Mekorot lines (5 m)

def r_mekorot_lines(ctx):
    """Mekorot's response to the infrastructure inquiry lists the network items in the request's polygon. Only
    protection radii of wells and no pipeline -> the 5 m line restriction has nothing to apply to."""
    d = next((x for x in ctx.docs if x.find(r"פריטי רשת המים")), None)
    if not d:
        return None
    flat = re.sub(r"\s+", " ", " ".join(d.pages))
    part = flat.split("פריטי רשת המים", 1)[1][:1500]
    radii = re.findall(r"רדיוס מגן [א-ת]", part)
    lines = re.findall(r"קו (?:מים|לחץ|הולכה|מקורות)|צינור", part)
    q = d.find(r"פריטי רשת המים")
    e = [ev(d, q[0], q[1])]
    valid = re.search(r"בתוקף עד\s*ליום\s*(\d{2}/\d{2}/\d{4})", flat)
    if lines:
        return Resolution("UNCERTAIN", f"תשובת מקורות ({d.filename}) מפרטת קווי מים בתחום הבקשה; המרחק של עבודות הפיתוח מהם "
                                       "לא נמדד בשרטוט.", e, review="UNRESOLVED")
    return Resolution("PASS", f"תשובת מקורות ({d.filename}{', בתוקף עד ' + valid.group(1) if valid else ''}) מפרטת בתחום הבקשה "
                              f"רק רדיוסי מגן של קידוחים ({len(radii)} פריטים) ואינה מפרטת קווי מקורות — אין קו שממנו נדרש מרחק 5 מ׳. "
                              "(התיאום מול מקורות לעניין רדיוסי המגן נבדק בנפרד.)", e)


# ------------------------------------------------------------------ technical systems screening (drawing read)

def r_tech_screening(ctx):
    sc = (ctx.drawing or {}).get("screening")
    if not sc:
        return None
    file = ctx.drawing.get("file")
    exposed = sc.get("exposed") or []
    seen = sc.get("screened") or []
    if exposed:
        # the small image model is not reliable enough to establish a defect: what it flags goes to the audit record
        return Resolution("UNCERTAIN", f"מודל התמונה סימן מערכות טכניות שאולי אינן מוסתרות (גיליון {_sheets(exposed)}, אושר בקריאה "
                                       "שנייה); זיהוי של מודל תמונה אינו מספיק לקביעת ליקוי — נדרש אימות.",
                          [_drawing_ev(ctx, exposed[0]["sheet"], f"סימון אפשרי של מערכת לא מוסתרת, גיליון {_sheets(exposed)}")],
                          review="UNRESOLVED", internal=True)
    text = (f"מערכות טכניות מוסתרות במסתור/מעקה (גיליון {_sheets(seen)})" if seen
            else "לא סומנו בחזיתות ובגג מערכות טכניות חשופות")
    roof = (ctx.drawing.get("height") or {}).get("roof_type")
    solar = "; קולטים על גג רעפים פטורים מהסתרה לפי ההוראה" if roof == "tiled" and ctx.drawing.get("solar") else ""
    return Resolution("PASS", f"{text}{solar} ({file}).", [_drawing_ev(ctx, (seen or [{}])[0].get("sheet"), text)])


# ------------------------------------------------------------------ checks the submission cannot answer yet

def r_fences(ctx):
    if not ctx.drawing:
        return None
    return Resolution("UNCERTAIN", "קירות ההפרדה והגדרות בין היחידות לא זוהו כגאומטריה נפרדת בשרטוט (מידות משורטטות כקווים, ללא "
                                   "שכבה ייעודית); אורך ≤ 5.0 מ׳ וגובה ≤ 1.80 מ׳ לא נמדדו.", [], review="NOT_CHECKED")


def r_infiltration(ctx):
    if not ctx.drawing:
        return None
    return Resolution("UNCERTAIN", "בבקשה לא נמצא נתון או פוליגון של שטח חדיר מים, וגבול המגרש הכולל (תא שטח 368) אינו בגיליונות "
                                   "שנמדדו; עמידה ב־15% לא חושבה.", [], review="NOT_CHECKED")


# ------------------------------------------------------------------ areas: source C (floor plans' walls) vs B

ENCLOSED = ("primary", "protected_room_floor", "protected_room_walls")   # B categories that lie inside the walls


def _assign(diagrams: list[float], floors: list[float]) -> list[int] | None:
    """Each area diagram (one unit on one floor) to one floor plan, minimising the total gap. Brute force: the
    diagrams of a request are few (units x floors)."""
    import itertools
    if not floors or not diagrams or len(floors) ** len(diagrams) > 200_000:
        return None
    best = None
    for combo in itertools.product(range(len(floors)), repeat=len(diagrams)):
        sums = [0.0] * len(floors)
        for d, f in zip(diagrams, combo):
            sums[f] += d
        gap = sum(abs(a - b) for a, b in zip(sums, floors))
        if best is None or gap < best[0]:
            best = (gap, combo)
    return list(best[1])


def r_floor_plans(ctx):
    """Source C: each floor's gross area inside the outer face of its cut walls (agent/floor_geometry.py), against
    the area-diagram categories that lie inside the walls (B). Walls enclosing more than B counts is unresolved (an
    attic, a void or an open balcony is not floor area, and room labels are drawn as lines); B counting area that the
    walls do not enclose is a discrepancy."""
    fg = (ctx.drawing or {}).get("floor_geometry") or {}
    ag = (ctx.drawing or {}).get("area_geometry") or {}
    floors = fg.get("floors") or []
    diags = [d for s in ag.get("sheets", []) for d in s.get("diagrams", [])]
    if not floors or not diags:
        return None
    distinct = sum(1 for d in diags if not d.get("same_as"))
    if len(floors) > max(distinct, 1):
        # more plan outlines than distinct floor diagrams: a floor's walls did not close into one outline (the plan
        # is drawn in several viewports, or an opening is wider than any bridge) — partial areas, never a finding
        sizes = ", ".join(f"{f['gross_m2']}" for f in floors)
        return Resolution("UNCERTAIN", f"מקור ג׳ לא הוכרע: בתכניות הקומות נמצאו {len(floors)} מעטפות קירות ({sizes} מ\"ר) "
                                       f"מול {distinct} תרשימי קומה שונים — מעטפת הקומה לא נסגרה לקו אחד; השטחים חלקיים.",
                          [{"type": "measurement", "file": ctx.drawing.get("file"), "page": floors[0].get("sheet"),
                            "method": "מעטפת הקירות בתכניות הקומות", "quote": sizes, "algorithm": fg.get("algorithm")}],
                          review="UNRESOLVED", internal=True)
    enclosed = [sum(d["area_m2"].get(c, 0.0) for c in ENCLOSED) for d in diags]
    combo = _assign(enclosed, [f["gross_m2"] for f in floors])
    if combo is None:
        return None
    file = ctx.drawing.get("file")
    items, lines = [], []
    for i, f in enumerate(floors):
        b = round(sum(e for e, c in zip(enclosed, combo) if c == i), 3)
        n = sum(1 for c in combo if c == i)
        tol = max(0.3, 0.003 * f["gross_m2"]) + f.get("sensitivity_m2", 0) + f.get("copies_spread_m2", 0)
        d = round(f["gross_m2"] - b, 2)
        where = f"גיליון {f['sheet']}, קנ\"מ {f['scale']}; {len(f.get('copies', []))} עותקים של התכנית (פיזור {f.get('copies_spread_m2', 0)} מ\"ר)"
        e = [{"type": "measurement", "file": file, "page": f["sheet"],
              "method": "מעטפת הקירות החתוכים בתכנית הקומה (גישור פתחים עד " + f"{f['bridge_m']} מ׳" + "), קנ\"מ מטרנספורמציית ה-Viewport",
              "quote": f"קומה {i + 1}: {f['size_m'][0]}×{f['size_m'][1]} מ׳, שטח ברוטו בתוך הקירות {f['gross_m2']} מ\"ר; "
                       f"בתרשימי חישוב השטחים ({n} תרשימים): עיקרי+ממ\"ד בתוך הקירות {b} מ\"ר",
              "algorithm": fg.get("algorithm")}]
        lines.append(f"קומה {i + 1}: קירות {f['gross_m2']} מול תרשימים {b} (הפרש {d:+.2f})")
        if abs(d) <= tol:
            continue
        if d > 0:
            items.append({"review": "UNRESOLVED", "internal": True, "title_he": f"שטח בתוך הקירות שאינו נספר — קומה {i + 1}",
                          "found_he": f"הקירות בקומה {i + 1} תוחמים {f['gross_m2']} מ\"ר; בתרשימי חישוב השטחים נספרו בתוכם {b} מ\"ר — "
                                      f"{d:.2f} מ\"ר אינם נספרים. אם אלה עליית גג נמוכה, חלל או מרפסת פתוחה — אינם שטח רצפה; "
                                      "כינויי החדרים משורטטים כקווים ולא נקראו, ולכן הסיווג לא הוכרע.",
                          "diff": f"{d:+.2f} מ\"ר", "where_he": where, "evidence": e})
        else:
            items.append({"review": "DOCUMENTED_DISCREPANCY", "title_he": f"שטח שנספר מחוץ לקירות — קומה {i + 1}",
                          "found_he": f"בתרשימי חישוב השטחים נספרו בקומה {i + 1} {b} מ\"ר בקטגוריות שבתוך המבנה, אך הקירות בתכנית "
                                      f"הקומה תוחמים רק {f['gross_m2']} מ\"ר.",
                          "diff": f"{d:+.2f} מ\"ר", "where_he": where,
                          "correction_he": "להתאים את תרשימי חישוב השטחים לגבולות הקירות בתכנית הקומה.", "evidence": e})
    ev_all = [x for it in items for x in it["evidence"]] or [{
        "type": "measurement", "file": file, "page": floors[0]["sheet"], "method": "מעטפת הקירות בתכניות הקומות",
        "quote": "; ".join(lines), "algorithm": fg.get("algorithm")}]
    canopies = sum(d["area_m2"].get("covered_service", 0.0) for d in diags)
    note = (f" סככות ושטחים מקורים מחוץ לקירות ({canopies:.2f} מ\"ר בתרשימים) לא נמדדו מהתכניות." if canopies else "")
    if any(x["review"] == "DOCUMENTED_DISCREPANCY" for x in items):
        return Resolution("FAIL", "מקור ג׳ (תכניות הקומות): " + "; ".join(lines) + "." + note, ev_all,
                          review="DOCUMENTED_DISCREPANCY", items=items)
    if items:
        return Resolution("UNCERTAIN", "מקור ג׳ (תכניות הקומות): " + "; ".join(lines) + ". " + items[0]["found_he"] + note,
                          ev_all, review="UNRESOLVED", items=items, internal=True)
    return Resolution("PASS", "מקור ג׳ (תכניות הקומות) תואם את תרשימי חישוב השטחים: " + "; ".join(lines) + "." + note, ev_all)


# ------------------------------------------------------------------ licensing route and floor-specific rights

def case_proposal(ctx):
    """The application as the route engine sees it: plans and submission date from the case, the route the applicant
    chose (declared, or the request form: a relief section means the relief route), per-floor areas only when
    declared per floor or measured — never derived from totals."""
    import datetime as _dt
    from . import route as R
    d = ctx.declared or {}
    try:
        sub = _dt.date.fromisoformat(str(d.get("submission_date")))
    except (TypeError, ValueError):
        return None
    route, how = d.get("licensing_route"), "הוצהר בתיק" if d.get("licensing_route") else ""
    if not route:
        form = next((x for x in ctx.docs if x.doc_type == "application_form"), None)
        if form:
            has_relief = bool(form.find(r"הקלות מבוקשות|בקשה להקלה|פירוט ההקלות"))
            route, how = ("RELIEF" if has_relief else "REGULAR"), f"טופס הבקשה ({form.filename}): " + (
                "כולל פרק הקלות" if has_relief else "לא מבוקשות הקלות")
    floors = None                     # "floor_areas": a per-floor area table (declared["floors"] is the number of floors)
    rows = d.get("floor_areas")
    if isinstance(rows, list) and rows and all(isinstance(f, dict) and f.get("name") for f in rows):
        floors = [R.Floor(**{k: v for k, v in f.items() if k in R.Floor.__dataclass_fields__}) for f in rows]
    return R.Proposal(application_id=str(d.get("application_number") or ""), submission_date=sub,
                      plans=list(d.get("plans_declared") or []), land_use=d.get("main_use"), selected_route=route,
                      route_source=how, total_main_m2=d.get("main_area_m2"), total_service_m2=d.get("service_area_m2"),
                      floors=floors, floors_source="טבלת שטחים לפי קומה" if floors else "",
                      request_text=" ".join(str(x) for x in (d.get("description"), ctx.title) if x),
                      zero_level_change_m=d.get("zero_level_change_m"))


def _route_items(res, statuses):
    out = []
    for c in res.checks:
        if c.status not in statuses:
            continue
        review = ("CONFIRMED_DEFECT" if c.confirmable and c.status in ("RELIEF", "DEVIATION_UNCLASSIFIED") else
                  "CONFIRMED_DEFECT" if c.confirmable and c.status == "PROHIBITED" and res.confirmed else "DOCUMENTED_DISCREPANCY")
        out.append({"review": review, "title_he": c.topic_he, "found_he": c.explanation_he,
                    "diff": (f"{c.measured} מול {c.limit} {c.unit}" if c.measured is not None and c.limit is not None else None),
                    "where_he": "תכנית " + (res.rights_source or ""), "correction_he": (
                        "להגיש את הבקשה במסלול הקלות, או להתאים את התכנון לתכנית." if c.status in ("RELIEF", "DEVIATION_UNCLASSIFIED")
                        else "לתקן את התכנון — סטייה ניכרת אינה ניתנת לאישור בהקלה."),
                    "evidence": [{"type": "document", "file": res.rights_source, "page": None,
                                  "quote": c.explanation_he, "method": "מנוע מסלול רישוי" + (f", תקנה {c.reg}" if c.reg else "")}]})
    return out


def _no_proposal(ctx, what_he: str):
    """No submission date: not applicable when no rights file covers the case's plans, else not checked."""
    import datetime as _dt
    from . import route as R
    plans = list((ctx.declared or {}).get("plans_declared") or [])
    rights, _ = R.load_rights(plans, (ctx.declared or {}).get("main_use"), _dt.date.today())
    if rights is None:
        return Resolution("NA", f"אין קובץ זכויות לתכנית החלה — {what_he} לא נבדק.")
    return Resolution("UNCERTAIN", f"חסר תאריך הגשת הבקשה — לא ניתן לקבוע את הדין החל; {what_he} לא נבדק.", [], review="NOT_CHECKED")


def r_licensing_route(ctx):
    from . import route as R
    p = case_proposal(ctx)
    if p is None:
        return _no_proposal(ctx, "מסלול הרישוי")
    res = R.validate(p)
    if res.verdict == "NO_RIGHTS":
        return Resolution("NA", "אין קובץ זכויות לתכנית החלה על הבקשה — מסלול הרישוי לא נבדק. " + "; ".join(res.law_notes))
    text = R.summary_he(res) + (f" ({p.route_source})" if p.route_source else "")
    notes = " | " + "; ".join(res.law_notes)
    if res.verdict == "ROUTE_OK":
        return Resolution("PASS", text + notes)
    if res.verdict == "INSUFFICIENT_EVIDENCE":
        return Resolution("UNCERTAIN", text + notes, review="NOT_CHECKED")
    prohibited = res.verdict == "PROHIBITED_DEVIATION" and res.confirmed
    head = {"review": "CONFIRMED_DEFECT" if res.confirmed else "DOCUMENTED_DISCREPANCY",
            "title_he": "סטייה ניכרת מהתכנית" if res.verdict == "PROHIBITED_DEVIATION" else "מסלול רישוי שגוי",
            "found_he": text, "where_he": p.route_source or None,
            "correction_he": ("לתקן את התכנון — סטייה ניכרת אינה ניתנת לאישור בהקלה" if res.verdict == "PROHIBITED_DEVIATION"
                              else "להגיש את הבקשה מחדש במסלול הקלות (עם פרסום ההקלות הנדרשות)."), "evidence": []}
    return Resolution("FAIL", text + notes, [], review=head["review"], items=[head], reject_basis=prohibited)


def r_floor_rights(ctx):
    from . import route as R
    p = case_proposal(ctx)
    if p is None:
        return _no_proposal(ctx, "זכויות לפי קומה")
    res = R.validate(p)
    if res.verdict == "NO_RIGHTS":
        return Resolution("NA", "אין קובץ זכויות לתכנית החלה — זכויות לפי קומה לא נבדקו.")
    floor_checks = [c for c in res.checks if c.topic in ("floors", "floors_above", "basement_floors", "basement_area", "service_to_main")]
    devs = [c for c in floor_checks if c.status in ("RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED")]
    if devs:
        sub = R.RouteResult(res.application_id, res.selected_route, res.route_needed, res.verdict, res.confirmed, devs,
                            res.law_notes, res.rights_source)
        return Resolution("FAIL", "; ".join(c.explanation_he for c in devs), [], items=_route_items(sub, ("RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED")),
                          review="CONFIRMED_DEFECT" if all(c.confirmable for c in devs) else "DOCUMENTED_DISCREPANCY")
    if any(c.status in ("NOT_CHECKED", "POSSIBLE_DEVIATION") for c in floor_checks):
        return Resolution("UNCERTAIN", "; ".join(c.explanation_he for c in floor_checks), [], review="NOT_CHECKED")
    return Resolution("PASS", "; ".join(c.explanation_he for c in floor_checks), [])


RESOLVERS = {
    "QA-REQ-SECTIONS": _drawing_views("חתכים", "section"), "QA-REQ-ELEVATIONS": _drawing_views("חזיתות", "elevation"),
    "HA-368-REGISTRY-STATUS": r_registry_status, "HA-368-TABLE-ARITHMETIC": r_table_arithmetic,
    "HA-368-TABLE-VS-REGISTRY": r_table_vs_registry,
    "HA-633-PARKING": r_parking, "HA-633-PV-ROOF": r_pv, "HA-633-SHEDS": r_shed,
    "HA-633-ANTIQUITIES": r_antiquities, "HA-633-COND-ELECTRIC": r_electric, "HA-633-COND-WELLS": r_wells,
    "HA-633-COND-HFC": r_hfc, "HA-633-COND-BINUI-PLAN": r_binui_plan, "HA-633-COND-DEMOLITION": r_demolition,
    "HA-633-WASTE-ESTIMATE": r_waste, "HA-633-SEWAGE": r_sewage, "HA-633-BETTERMENT-LEVY": r_betterment,
    "HA-633-TREES-4M": r_trees, "HA-633-BUILDING-FORM": r_building_form, "HA-633-COVERAGE-CELL": r_coverage,
    "HA-AREA-DIAGRAMS": r_area_diagrams, "HA-368-TABLE-VS-PERMITS": r_permit_history, "HA-LAND-PARCEL": r_land_parcel,
    "HA-RMI-CONSENT": r_rmi_consent, "HA-633-MEKOROT-5M": r_mekorot_lines, "HA-633-TECH-SCREENING": r_tech_screening,
    "HA-633-FENCES": r_fences, "HA-633-INFILTRATION": r_infiltration, "HA-AREA-FLOORPLANS": r_floor_plans,
    "QA-LICENSING-ROUTE": r_licensing_route, "QA-FLOOR-RIGHTS": r_floor_rights,
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


def document_facts(files, cache=None) -> tuple[list[Doc], dict, list[dict]]:
    docs = load_docs(files, cache)
    facts, evidence = area_table_facts(docs)
    if facts:
        facts["cell_total_pct"] = round(facts["cell_main_pct"] + facts["cell_service_pct"], 2)
    return docs, facts, evidence


def find_cell(docs: list[Doc]) -> str | None:
    """The plan cell of the request: "משטח מגרש 368" (also extracted as "368 משטח מגרש") or "מגרש 368 מתכנית"."""
    for d in docs:
        for t in d.pages[:3]:
            flat = re.sub(r"\s+", " ", t)
            m = (re.search(r"משטח מגרש\s*(\d{3})", flat) or re.search(r"(\d{3})\s*משטח מגרש", flat)
                 or re.search(r"מגרש\s*(\d{3})\s*מתכנית", flat))
            if m:
                return m.group(1)
    return None


def resolve(results: list, docs: list[Doc], declared: dict, title: str, facts_from_docs: dict, area_evidence: list[dict],
            drawing: dict | None = None, gush: str | None = None) -> int:
    """Answer open findings in place; returns how many were resolved."""
    cell = find_cell(docs)
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
        extra = (([f"REVIEW:{res.review}"] if res.review else []) + (["INTERNAL"] if res.internal else [])
                 + (["REJECT_BASIS"] if res.reject_basis else []))
        if res.status == "UNCERTAIN":
            r.explanation_he = res.explanation_he
            r.evidence = list(r.evidence or []) + res.evidence
            r.flags = ([f for f in r.flags if f != "RESOLVED_FROM_DOCUMENTS"]
                       + (["NEEDS_DRAWING_READ"] if res.review is None else []) + extra)
            continue
        r.explanation_he = res.explanation_he
        r.evidence = list(r.evidence or []) + res.evidence + [{"type": "item", **it} for it in res.items]
        r.flags = [f for f in r.flags if f not in ("REVIEW_REQUIRED", "INCOMPLETE")] + ["RESOLVED_FROM_DOCUMENTS"] + extra
        r.confidence = 0.9 if res.evidence else 0.75
        n += 1
    return n
