"""External defects report — דוח ליקויים — for the applicant or architect: Hebrew, RTL, PDF.

Only what the defects-report policy allows: confirmed defects and documented discrepancies that bear directly on the
reviewed application (findings flagged EXTERNAL by services.run_checks), their evidence, the correction required and
the review recommendation. Passed checks, unperformed checks, future-stage requirements, other applications' issues
and internal notes stay in the internal record (the reviewer report / audit), never here.
Colours: light red = confirmed defect, light orange = documented discrepancy, neutral = identification and limits.
"""
from __future__ import annotations

import datetime as dt
import io
import re
from zoneinfo import ZoneInfo
from pathlib import Path

from .config import settings
from .models import CheckRun, PermitCase

EXTERNAL = ("CONFIRMED_DEFECT", "DOCUMENTED_DISCREPANCY")
KIND_HE = {"CONFIRMED_DEFECT": "ליקוי", "DOCUMENTED_DISCREPANCY": "פער לבירור"}
DECISION_HE = {"RETURN_FOR_CORRECTIONS": "החזרה לתיקון ולהשלמה", "REJECT_RECOMMENDATION": "המלצה לדחייה",
               "NO_DEFECTS_IDENTIFIED": "לא נמצאו ליקויים בבדיקות שהושלמו",
               "INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION": "אין די ראיות להמלצה סופית"}
RED, ORANGE, NEUTRAL, LINE = "#FDE2E2", "#FFE8CC", "#F2F4F7", "#C9CED6"
SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _status(f) -> str:
    return next((x[7:] for x in f.flags if x.startswith("STATUS_")), "")


def _image(e: dict) -> str | None:
    p = e.get("image")
    if not p:
        return None
    path = Path(settings.knowledge_dir, "lots", p)
    return str(path) if path.exists() else None


def build_defects(case: PermitCase, run: CheckRun) -> dict:
    """The report's content: header, recommendation, numbered items (defects first), limitation statement."""
    review = (run.summary or {}).get("review") or {}
    items = []
    for f in run.findings:
        if "EXTERNAL" not in f.flags:
            continue
        subs = [e for e in (f.evidence or []) if e.get("type") == "item" and e.get("review") in EXTERNAL and not e.get("internal")]
        if not subs and any(e.get("type") == "item" for e in f.evidence or []):
            continue                                     # every sub-item is internal: nothing for the applicant
        docs = [e for e in (f.evidence or []) if e.get("type") in ("document", "measurement")]
        # the requirement as the case's own jurisdiction states it, when a rule cites more than one source
        cite = next((x for x in f.citations or [] if x.get("jurisdiction") == case.tenant_id), None) or (f.citations or [{}])[0]
        reg = " · ".join(x for x in (cite.get("title_he", "").split(" — ")[0], cite.get("section")) if x) or None
        if subs:
            for it in subs:
                items.append({"kind": it["review"], "severity": f.severity, "title": it["title_he"], "found": it["found_he"],
                              "diff": it.get("diff"), "where": it.get("where_he"), "impact": it.get("impact_he"),
                              "correction": it.get("correction_he") or f.fix_hint_he, "regulation": reg,
                              "evidence": [e for e in it.get("evidence") or [] if e.get("type") in ("document", "measurement")]
                              or docs, "rule_id": f.rule_id, "finding_id": f.id})
        else:
            items.append({"kind": _status(f), "severity": f.severity, "title": f.title_he, "found": f.explanation_he,
                          "diff": None, "where": ", ".join(sorted({f"{e['file']}" + (f", עמ׳ {e['page']}" if e.get("page") else "")
                                                                    for e in docs if e.get("file")})) or None,
                          "impact": None, "correction": f.fix_hint_he, "regulation": reg, "evidence": docs,
                          "rule_id": f.rule_id, "finding_id": f.id})
    items.sort(key=lambda x: (EXTERNAL.index(x["kind"]), SEV.get(x["severity"], 9), x["title"]))
    for i, it in enumerate(items, 1):
        it["no"] = f"{i:02d}"
    dec = review.get("decision") or ("RETURN_FOR_CORRECTIONS" if items else "NO_DEFECTS_IDENTIFIED")
    cnt = review.get("counts") or {}
    open_n = cnt.get("UNRESOLVED", 0) + cnt.get("NOT_CHECKED", 0)
    limits = ("הדוח מפרט ליקויים ופערים מתועדים בלבד, ואינו מונה בדיקות שעברו, בדיקות שלא הושלמו או דרישות לשלבי רישוי "
              f"מאוחרים. {open_n} בדיקות לא הושלמו; אין לראות בהשמטת נושא אישור לתקינותו ואין בדוח אישור הנדסי מלא. "
              "ההמלצה היא של מערכת הבדיקה ואינה החלטת רשות הרישוי.")
    cov = review.get("coverage") or {}
    fams = cov.get("families") or {}
    partial = [f.get("label_he") for f in fams.values() if f.get("state") in ("PARTIAL", "NONE", "NO_CHECKS")]
    if partial:
        limits += " תחומים שלא נבדקו במלואם: " + ", ".join(x for x in partial if x) + "."
    return {
        "title": f"דוח ליקויים – בקשה להיתר מס׳ {case.case_number}",
        "case": {"number": case.case_number, "title": case.title, "gush": case.gush, "helka": case.helka,
                 "address": case.address, "plans": case.applicable_plans},
        "revision": {"run": run.version, "at": run.started_at.strftime("%d.%m.%Y"), "files": len(run.input_hashes or []),
                     "stage_he": review.get("stage_he")},
        "decision": dec, "decision_he": DECISION_HE[dec], "decision_why": review.get("decision_why"),
        "items": items, "limitations_he": limits,
        "counts": {k: sum(1 for x in items if x["kind"] == k) for k in EXTERNAL},
    }


def _evidence_text(it: dict) -> str:
    out = []
    for e in it["evidence"][:3]:
        where = e.get("file") or ""
        if e.get("page"):
            where += f", עמ׳/גיליון {e['page']}"
        q = re.sub(r"[\ue000-\uf8ff\u25a0-\u25ff\ufffd]", "", e.get("quote") or "").strip()   # glyphs the font cannot draw
        out.append(f"{where}: ״{q[:220]}{'…' if len(q) > 220 else ''}״" if q else where)
    return "\n".join(out)


def _rows(it: dict) -> list[tuple[str, str]]:
    rows = [("ממצא", it["found"])]
    if it.get("diff"):
        rows.append(("פער", it["diff"]))
    if it.get("where"):
        rows.append(("היכן", it["where"]))
    ev = _evidence_text(it)
    if ev:
        rows.append(("אסמכתה", ev))
    if it.get("regulation"):
        rows.append(("דרישה", it["regulation"]))
    if it.get("impact"):
        rows.append(("השפעה על הבקשה", it["impact"]))
    rows.append(("תיקון נדרש", it.get("correction") or "לתקן או להבהיר בהתאם לממצא."))
    return rows


# ------------------------------------------------------------------ PDF

BLUE, MAROON, GREY = "#1F4E79", "#A23B3B", "#6B7280"
KIND_SUB = {"CONFIRMED_DEFECT": "ליקוי", "DOCUMENTED_DISCREPANCY": "פער לבירור"}


def _p(text: str, width: float, size: float = 9.5, bold: bool = False, color: str = "#1F2937",
       label: str | None = None, space_after: float = 3):
    """A right-aligned Hebrew paragraph (wrapped in logical order, then reordered per line), optionally starting with a
    bold label such as "תיקון נדרש:"."""
    from bidi.algorithm import get_display
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    from .reports import _wrap_logical
    font = "He-Bold" if bold else "He"
    full = f"{label} {text}" if label else str(text)
    lines = [get_display(l) for l in _wrap_logical(full, font, size, width - 3)]
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = [esc(l) for l in lines]
    if label and lines:
        vis = get_display(label)
        if lines[0].endswith(vis):                 # RTL: the label sits at the visual right end of the first line
            out[0] = esc(lines[0][: -len(vis)]) + f'<font name="He-Bold">{esc(vis)}</font>'
    return Paragraph("<br/>".join(out), ParagraphStyle("p", fontName=font, fontSize=size, leading=size * 1.4,
                                                       alignment=TA_RIGHT, textColor=color, spaceAfter=space_after))


def _ref_text(it: dict) -> str:
    parts = []
    for e in it["evidence"][:3]:
        w = e.get("file") or ""
        if e.get("page"):
            w += f", עמ׳ {e['page']}"
        if w and w not in parts:
            parts.append(w)
    if it.get("regulation"):
        parts.append(it["regulation"])
    return "; ".join(parts)


def render_defects_pdf(rep: dict) -> bytes:
    """Short professional layout: title, one-line identification, one-sentence summary, then per item a numbered
    heading, a category line, the finding in a few lines, the required correction and one reference line."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer

    from .reports import _fonts
    _fonts()
    buf = io.BytesIO()
    c, rv = rep["case"], rep["revision"]
    when = dt.datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%d.%m.%Y")

    def footer(canvas, doc):
        from bidi.algorithm import get_display
        canvas.saveState()
        canvas.setFont("He", 7.5)
        canvas.setFillColor(colors.HexColor(GREY))
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, get_display(f"דוח ליקויים · {when}  |  עמוד {doc.page}"))
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=rep["title"], author="permit-review")
    W = A4[0] - 32 * mm
    place = (c.get("title") or "").split("—")[0].strip()[:60]
    story = [_p(f"בדיקת בקשות להיתר  |  {place}", W, 8, True, BLUE, space_after=2),
             _p("דוח ליקויים", W, 20, True, BLUE, space_after=4),
             _p(f"בקשה {c['number']}" + (f"  |  {c['address']}" if c.get("address") else ""), W, 11, True, "#374151", space_after=2),
             _p(f"גוש {c['gush'] or '—'}, חלקה {c['helka'] or '—'} | תכנית {', '.join(c['plans'] or []) or '—'} | "
                f"גרסת בדיקה {rv['run']} ({rv['at']})", W, 8, False, GREY, space_after=6)]
    n_def, n_disc = rep["counts"].get("CONFIRMED_DEFECT", 0), rep["counts"].get("DOCUMENTED_DISCREPANCY", 0)
    summary = (f"{rep['decision_he']}: {n_def} ליקויים ו־{n_disc} פערים לבירור מחייבים תיקון או הבהרה לפני המשך הטיפול."
               if rep["items"] else "לא נמצאו ליקויים בבדיקות שהושלמו.")
    story += [_p(summary, W, 10, False, space_after=8)]
    for it in rep["items"]:
        block = [_p(f"{it['no']} | {it['title']}", W, 12.5, True, BLUE, space_after=2),
                 _p(KIND_SUB[it["kind"]] + (f" — {it['diff']}" if it.get("diff") else ""), W, 9, True, MAROON, space_after=2),
                 _p(it["found"] + (f" ({it['where']})" if it.get("where") else ""), W, 9.5)]
        block.append(_p(it.get("correction") or "לתקן או להבהיר בהתאם לממצא.", W, 9.5, label="תיקון נדרש:"))
        ref = _ref_text(it)
        if ref:
            block.append(_p("אסמכתה: " + ref, W, 7.5, False, GREY))
        story += [KeepTogether(block), Spacer(1, 8)]
    story.append(_p("הדוח מפרט ליקויים ופערים מתועדים בלבד; אין לראות בהשמטת נושא אישור לתקינותו. "
                    "ההמלצה היא של מערכת הבדיקה ואינה החלטת רשות הרישוי.", W, 7.5, False, GREY))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
