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


RESOLVERS = {
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


def document_facts(files) -> tuple[list[Doc], dict, list[dict]]:
    docs = load_docs(files)
    facts, evidence = area_table_facts(docs)
    if facts:
        facts["cell_total_pct"] = round(facts["cell_main_pct"] + facts["cell_service_pct"], 2)
    return docs, facts, evidence


def resolve(results: list, docs: list[Doc], declared: dict, title: str, facts_from_docs: dict, area_evidence: list[dict]) -> int:
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
    ctx = Context(docs, declared, title, cell, facts_from_docs, area_evidence)
    n = 0
    for r in results:
        fn = RESOLVERS.get(r.rule_id)
        # open findings, and FAILs of document rules: a document filed under another type ("אחר") is still there
        if not fn or r.status not in ("UNCERTAIN", "FAIL"):
            continue
        res = fn(ctx)
        if not res or (r.status == "FAIL" and not (res.status == "PASS" and res.evidence)):
            continue                # a FAIL is only reversed by a document that shows the requirement is met
        r.computed_result = res.status
        r.status = "UNCERTAIN" if res.status == "FAIL" and "RULE_NOT_APPROVED" in r.flags else res.status
        r.explanation_he = res.explanation_he
        r.evidence = list(r.evidence or []) + res.evidence
        r.flags = [f for f in r.flags if f not in ("REVIEW_REQUIRED", "INCOMPLETE")] + ["RESOLVED_FROM_DOCUMENTS"]
        r.confidence = 0.9 if res.evidence else 0.75
        n += 1
    return n
