"""External defects report — דוח ליקויים — for the applicant or architect: Hebrew, RTL, PDF and Word.

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

def render_defects_pdf(rep: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, SimpleDocTemplate, Spacer, Table, TableStyle

    from .reports import _fonts, he
    _fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=rep["title"], author="permit-review")
    W = A4[0] - 28 * mm
    c, rv = rep["case"], rep["revision"]
    ident = (f"{(c['title'] or '')[:70]} · גוש {c['gush'] or '—'} חלקה {c['helka'] or '—'} · תכנית {', '.join(c['plans'] or []) or '—'} · "
             f"גרסת בדיקה {rv['run']} ({rv['at']}, {rv['files']} קבצים) · שלב: {rv['stage_he'] or '—'}")
    head = Table([[he(rep["title"], W, 15, True, in_cell=True)], [he(ident, W, 8.5, in_cell=True)],
                  [he(f"המלצה: {rep['decision_he']}" + (f" — {rep['decision_why']}" if rep.get("decision_why") else ""), W, 10, True, in_cell=True)]],
                 colWidths=[W])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(NEUTRAL)),
                              ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE))]))
    story = [head, Spacer(1, 8)]
    if not rep["items"]:
        story.append(he("לא נמצאו ליקויים בבדיקות שהושלמו.", W, 10, True))
    label_w, body_w = 26 * mm, W - 26 * mm
    for it in rep["items"]:
        bg = colors.HexColor(RED if it["kind"] == "CONFIRMED_DEFECT" else ORANGE)
        data = [[he(f"{KIND_HE[it['kind']]} {it['no']} — {it['title']}", W, 10, True, in_cell=True), ""]]
        for k, v in _rows(it):
            data.append([he(v, body_w, 8.5, in_cell=True), he(k, label_w, 8.5, True, in_cell=True)])   # RTL: label on the right
        t = Table(data, colWidths=[body_w, label_w])
        t.setStyle(TableStyle([("SPAN", (0, 0), (1, 0)), ("BACKGROUND", (0, 0), (-1, 0), bg),
                               ("BACKGROUND", (1, 1), (1, -1), colors.HexColor("#FAFAFB")),
                               ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                               ("INNERGRID", (0, 1), (-1, -1), 0.25, colors.HexColor(LINE)), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        block = [t]
        img = next((p for p in (_image(e) for e in it["evidence"]) if p), None)
        if img:
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(img).getSize()
            w = min(W, 150 * mm)
            block += [Spacer(1, 2), Image(img, width=w, height=w * ih / iw), he("קטע מהמסמך המקורי (ללא שינוי)", W, 7)]
        story += [KeepTogether(block), Spacer(1, 7)]
    lim = Table([[he("גבולות הדוח: " + rep["limitations_he"], W, 8, in_cell=True)]], colWidths=[W])
    lim.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(NEUTRAL)),
                             ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE))]))
    story += [lim, Spacer(1, 4), he(f"הופק {dt.datetime.now(ZoneInfo('Asia/Jerusalem')).strftime('%d.%m.%Y %H:%M')}", W, 7)]
    doc.build(story)
    return buf.getvalue()


# ------------------------------------------------------------------ Word (editable)

def render_defects_docx(rep: dict) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    d = Document()
    for sec in d.sections:
        sec.left_margin = sec.right_margin = Cm(1.6)
        sec.top_margin = sec.bottom_margin = Cm(1.4)
        sec._sectPr.append(OxmlElement("w:bidi"))
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Arial", Pt(10)
    st.element.rPr.rFonts.set(qn("w:cs"), "Arial")

    def rtl(par, text, bold=False, size=None):
        par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        par._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
        run = par.add_run(text)
        run.bold = bold
        rpr = run._r.get_or_add_rPr()
        rpr.append(OxmlElement("w:rtl"))
        if bold:
            rpr.append(OxmlElement("w:bCs"))
        if size:
            run.font.size = Pt(size)
            szcs = OxmlElement("w:szCs")
            szcs.set(qn("w:val"), str(int(size * 2)))
            rpr.append(szcs)
        return par

    def shade(cell, hex_):
        tcpr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), hex_.lstrip("#"))
        tcpr.append(shd)

    def table(rows: int, cols: int):
        t = d.add_table(rows=rows, cols=cols)
        t.style = "Table Grid"
        t._tbl.tblPr.append(OxmlElement("w:bidiVisual"))     # columns run right to left
        return t

    c, rv = rep["case"], rep["revision"]
    h = table(3, 1)
    for cell in h.columns[0].cells:
        shade(cell, NEUTRAL)
    rtl(h.cell(0, 0).paragraphs[0], rep["title"], True, 15)
    rtl(h.cell(1, 0).paragraphs[0], f"{(c['title'] or '')[:70]} · גוש {c['gush'] or '—'} חלקה {c['helka'] or '—'} · "
                                    f"גרסת בדיקה {rv['run']} ({rv['at']}) · שלב: {rv['stage_he'] or '—'}", size=9)
    rtl(h.cell(2, 0).paragraphs[0], f"המלצה: {rep['decision_he']}" + (f" — {rep['decision_why']}" if rep.get("decision_why") else ""), True, 11)
    d.add_paragraph()
    if not rep["items"]:
        rtl(d.add_paragraph(), "לא נמצאו ליקויים בבדיקות שהושלמו.", True)
    for it in rep["items"]:
        rows = _rows(it)
        t = table(len(rows) + 1, 2)
        top = t.cell(0, 0).merge(t.cell(0, 1))
        shade(top, RED if it["kind"] == "CONFIRMED_DEFECT" else ORANGE)
        rtl(top.paragraphs[0], f"{KIND_HE[it['kind']]} {it['no']} — {it['title']}", True, 11)
        for i, (k, v) in enumerate(rows, 1):
            rtl(t.cell(i, 0).paragraphs[0], k, True, 9)          # with bidiVisual, column 0 is on the right
            rtl(t.cell(i, 1).paragraphs[0], v, size=9)
            t.cell(i, 0).width, t.cell(i, 1).width = Cm(3.2), Cm(14.6)
        img = next((p for p in (_image(e) for e in it["evidence"]) if p), None)
        if img:
            d.add_picture(img, width=Cm(16))
            rtl(d.add_paragraph(), "קטע מהמסמך המקורי (ללא שינוי)", size=8)
        d.add_paragraph()
    lim = table(1, 1)
    shade(lim.cell(0, 0), NEUTRAL)
    rtl(lim.cell(0, 0).paragraphs[0], "גבולות הדוח: " + rep["limitations_he"], size=9)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
