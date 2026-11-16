"""Report assembly (JSON) and Hebrew RTL PDF rendering.

PDF: reportlab + python-bidi. Hebrew text is wrapped in *logical* order first and only then
converted to visual order line by line, so multi-line cells keep the correct line order.
Tables are emitted with column order reversed so the first logical column is on the right.
"""
from __future__ import annotations

import datetime as dt
import io

from bidi.algorithm import get_display
from reportlab.graphics.shapes import Drawing, Line, PolyLine, Polygon as RLPolygon, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from shapely import wkt as shapely_wkt
from shapely.geometry import LineString, MultiPolygon, Polygon
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import CadEntity, CaseFile, CheckRun, PermitCase

REPORT_TITLES = {
    "completeness": "דוח שלמות ותנאי סף",
    "rights": "דוח זכויות ותנאים",
    "reviewer": "דוח בודק",
}
STATUS_HE = {"PASS": "עומד", "FAIL": "לא עומד", "UNCERTAIN": "דורש בדיקה", "NA": "לא חל"}
SEV_HE = {"high": "גבוהה", "medium": "בינונית", "low": "נמוכה"}
FLAG_HE = {
    "RULE_NOT_APPROVED": "כלל טרם אושר",
    "INCOMPLETE": "חסר נתון",
    "THRESHOLD_SOURCE_MISSING": "ערך סף חסר במקור",
    "WITHIN_UNCERTAINTY_BAND": "בתחום אי-ודאות המדידה",
    "REVIEW_REQUIRED": "נדרשת הכרעת בודק",
    "CONDITION_FOR_PERMIT": "תנאי להיתר",
    "APPLICABILITY_UNKNOWN": "תחולה לא ידועה",
    "SOURCE_CONFLICT": "סתירת מקורות",
    "DEMO_RULE": "כלל הדגמה",
}

_FONTS_OK = False


def _fonts():
    global _FONTS_OK
    if not _FONTS_OK:
        pdfmetrics.registerFont(TTFont("He", settings.pdf_font))
        pdfmetrics.registerFont(TTFont("He-Bold", settings.pdf_font_bold))
        _FONTS_OK = True


def build_report(s: Session, case: PermitCase, run: CheckRun, kind: str) -> dict:
    findings = [f for f in run.findings if kind == "reviewer" or f.report == kind]
    order = {"FAIL": 0, "UNCERTAIN": 1, "PASS": 2, "NA": 3}
    sev = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f.status, 9), sev.get(f.severity, 9), f.rule_id))
    return {
        "kind": kind, "title_he": REPORT_TITLES[kind],
        "disclaimer_he": "המלצה בלבד. הדוח הופק באופן אוטומטי ואינו מהווה החלטה סטטוטורית; "
                         "ההכרעה בסמכות בודק/גורם מוסמך.",
        "case": {"id": case.id, "case_number": case.case_number, "title": case.title, "gush": case.gush,
                 "helka": case.helka, "address": case.address, "permit_type": case.permit_type,
                 "track": case.track, "zone": case.zone, "plans": case.applicable_plans, "is_demo": case.is_demo},
        "run": {"version": run.version, "at": run.started_at.isoformat(), "ruleset_hash": run.ruleset_hash,
                "inputs": run.input_hashes, "duration_ms": run.duration_ms, "locked": run.locked,
                "ai_summary": run.summary.get("ai_summary")},
        "findings": [{
            "id": f.id, "rule_id": f.rule_id, "rule_version": f.rule_version, "report": f.report,
            "status": f.status, "computed_result": f.computed_result, "severity": f.severity,
            "title_he": f.title_he, "explanation_he": f.explanation_he, "fix_hint_he": f.fix_hint_he,
            "measured_value": f.measured_value, "measured_uncertainty": f.measured_uncertainty,
            "threshold": f.threshold, "operator": f.operator, "units": f.units, "confidence": f.confidence,
            "citations": f.citations, "evidence": f.evidence, "flags": f.flags, "overlay_wkt": f.overlay_wkt,
            "reviewer_decision": f.reviewer_decision, "reviewer_note": f.reviewer_note, "reviewer_id": f.reviewer_id,
        } for f in findings],
        "measurements": run.measurements,
    }


# ------------------------------------------------------------------ PDF

def _wrap_logical(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for para in (text or "").split("\n"):
        cur = ""
        for word in para.split(" "):
            cand = (cur + " " + word).strip()
            if stringWidth(cand, font, size) <= width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


CELL_PADDING = 6   # reportlab Table default LEFTPADDING/RIGHTPADDING


def he(text: str, width: float, size: float = 8.5, bold: bool = False, align=TA_RIGHT, in_cell: bool = False) -> Paragraph:
    """Wrap in logical order to a width the Paragraph will never re-wrap, then reorder each line
    visually. If reportlab re-wrapped an already-visual line, the line order would flip."""
    font = "He-Bold" if bold else "He"
    usable = width - (2 * CELL_PADDING if in_cell else 0) - 3
    lines = [get_display(l) for l in _wrap_logical(str(text), font, size, usable)]
    esc = "<br/>".join(l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for l in lines)
    return Paragraph(esc, ParagraphStyle("he", fontName=font, fontSize=size, leading=size * 1.35, alignment=align))


def _plan_drawing(s: Session, case: PermitCase, findings: list[dict], w: float, h: float) -> Drawing | None:
    files = [f.id for f in case.files if f.kind in ("dxf", "dwg") and f.ingest_status == "OK"]
    if not files:
        return None
    ents = list(s.scalars(select(CadEntity).where(CadEntity.file_id.in_(files))))
    geoms = [(e.role, shapely_wkt.loads(e.wkt_m)) for e in ents]
    overlays = [shapely_wkt.loads(f["overlay_wkt"]) for f in findings
                if f.get("overlay_wkt") and f["status"] in ("FAIL", "UNCERTAIN")]
    allg = [g for _, g in geoms] + overlays
    minx = min(g.bounds[0] for g in allg); miny = min(g.bounds[1] for g in allg)
    maxx = max(g.bounds[2] for g in allg); maxy = max(g.bounds[3] for g in allg)
    sc = min((w - 20) / max(maxx - minx, 1e-6), (h - 20) / max(maxy - miny, 1e-6))
    tx = lambda x, y: (10 + (x - minx) * sc, 10 + (y - miny) * sc)  # noqa: E731
    colour = {"PLOT_BOUNDARY": colors.HexColor("#1f3b73"), "BUILDING_LINE": colors.HexColor("#2e7dd7"),
              "EXISTING": colors.HexColor("#7d8798"), "PROPOSED": colors.HexColor("#0a7f4f"),
              "BALCONY": colors.HexColor("#b36b00"), "ROOF_ROOM": colors.HexColor("#6a3fb5"),
              "ROOF_EDGE_FRONT": colors.HexColor("#c2185b"), "SUKKAH": colors.HexColor("#00838f")}
    d = Drawing(w, h)
    d.hAlign = "RIGHT"

    def add(g, stroke, fill=None, width=0.8, dash=None):
        if isinstance(g, (MultiPolygon,)):
            for p in g.geoms:
                add(p, stroke, fill, width, dash)
            return
        if isinstance(g, Polygon):
            pts = [c for xy in g.exterior.coords for c in tx(*xy)]
            d.add(RLPolygon(pts, strokeColor=stroke, fillColor=fill, strokeWidth=width, strokeDashArray=dash))
        elif isinstance(g, LineString):
            pts = [c for xy in g.coords for c in tx(*xy)]
            d.add(PolyLine(pts, strokeColor=stroke, strokeWidth=width, strokeDashArray=dash))
        elif hasattr(g, "geoms"):
            for p in g.geoms:
                add(p, stroke, fill, width, dash)
    for role, g in geoms:
        add(g, colour.get(role, colors.lightgrey), None, 0.9, [3, 2] if role == "BUILDING_LINE" else None)
    for g in overlays:
        add(g, colors.HexColor("#d32f2f"), colors.Color(0.83, 0.18, 0.18, alpha=0.35), 1.6)
    # scale bar 5 m
    x0, y0 = 10, 4
    d.add(Line(x0, y0, x0 + 5 * sc, y0, strokeColor=colors.black, strokeWidth=1))
    d.add(String(x0 + 5 * sc + 3, y0 - 2, "5 m", fontName="He", fontSize=6))
    return d


def render_pdf(s: Session, case: PermitCase, report: dict) -> bytes:
    _fonts()
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, rightMargin=12 * mm, leftMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=report["title_he"], author="BBP POC")
    W = page[0] - 24 * mm
    c = report["case"]
    story = [he(report["title_he"] + (" — הדגמה, נתונים פיקטיביים" if c["is_demo"] else ""), W, 16, True), Spacer(1, 4)]
    meta = (f"תיק: {c['case_number']} | {c['title']} | גוש {c['gush'] or '—'} חלקה {c['helka'] or '—'} | "
            f"סוג בקשה: {c['permit_type']} | מסלול: {c['track']} | תכניות: {', '.join(c['plans']) or '—'} | "
            f"גרסת בדיקה {report['run']['version']} | {report['run']['at'][:16].replace('T', ' ')} | "
            f"Ruleset {report['run']['ruleset_hash'][:12]}")
    story += [he(meta, W, 8.5), Spacer(1, 3), he(report["disclaimer_he"], W, 8.5, True), Spacer(1, 6)]

    if report["kind"] == "reviewer":
        dr = _plan_drawing(s, case, report["findings"], W * 0.6, 70 * mm)
        if dr:
            story += [he("תשריט מנותח עם סימון ממצאים (אדום = אי-התאמה/דורש בדיקה)", W, 9, True), dr, Spacer(1, 6)]
        if report["run"].get("ai_summary"):
            story += [he(report["run"]["ai_summary"], W, 8.5), Spacer(1, 6)]

    cols = [("#", 10), ("ממצא / כלל", 50), ("סטטוס", 20), ("חומרה", 17), ("נמדד", 22), ("סף", 22),
            ("הסבר", 70), ("מקור (מסמך/סעיף/עמוד)", 52), ("הנחיית תיקון", 42), ("ודאות", 16), ("החלטת בודק", 20)]
    widths = [w * mm for _, w in cols]
    scale = W / sum(widths)
    widths = [x * scale for x in widths]
    header = [he(t, wd, 8, True, in_cell=True) for (t, _), wd in zip(cols, widths)]
    rows = [header]
    styles = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c4d6")),
              ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7eef8")),
              ("VALIGN", (0, 0), (-1, -1), "TOP")]
    status_bg = {"FAIL": "#fde7e7", "UNCERTAIN": "#fff6dd", "PASS": "#e6f5ec", "NA": "#f2f4f7"}
    for i, f in enumerate(report["findings"], 1):
        meas = "—" if f["measured_value"] is None else (
            f"{f['measured_value']:.2f} {f['units'] or ''}" + (f" ±{f['measured_uncertainty']:.2f}" if f["measured_uncertainty"] else ""))
        thr = "—" if f["threshold"] is None else f"{ {'>=': '≥', '<=': '≤'}.get(f['operator'], f['operator'] or '')} {f['threshold']:.2f} {f['units'] or ''}"
        cites = "; ".join(f"{x.get('title_he')} {x.get('section') or ''} {('עמ׳ ' + str(x['page'])) if x.get('page') else ''} [{x.get('verification')}]"
                          for x in f["citations"]) or "—"
        flags = ", ".join(FLAG_HE.get(x, x) for x in f["flags"])
        decision = {"CONFIRMED": "אושר", "OVERRIDDEN": "נדחה/שונה"}.get(f["reviewer_decision"] or "", "ממתין")
        cells = [str(i), f"{f['title_he']}\n{f['rule_id']} v{f['rule_version']}", STATUS_HE[f["status"]] +
                 (f"\n(מחושב: {STATUS_HE[f['computed_result']]})" if f["computed_result"] != f["status"] else ""),
                 SEV_HE.get(f["severity"], f["severity"]), meas, thr,
                 f["explanation_he"] + (f"\n[{flags}]" if flags else ""), cites, f["fix_hint_he"] or "—",
                 f"{f['confidence']:.0%}", decision]
        rows.append([he(t, wd, 7.5, in_cell=True) for t, wd in zip(cells, widths)])
        styles.append(("BACKGROUND", (2, i), (2, i), colors.HexColor(status_bg[f["status"]])))
    # RTL: reverse column order so column 0 ("#") is rightmost
    rows = [list(reversed(r)) for r in rows]
    n = len(widths)
    styles = [(k, (n - 1 - a[0], a[1]), (n - 1 - b[0], b[1]), *rest) if k == "BACKGROUND" and a[0] == b[0]
              else (k, a, b, *rest) for (k, a, b, *rest) in styles]
    t = Table(rows, colWidths=list(reversed(widths)), repeatRows=1)
    t.setStyle(TableStyle(styles))
    story.append(t)
    story += [Spacer(1, 6), he("קבצי קלט (SHA-256): " + "; ".join(
        f"{x['file']} v{x['version']} {x['sha256'][:12]}" for x in report["run"]["inputs"]), W, 7.5)]
    story += [he(f"הופק: {dt.datetime.now().strftime('%d/%m/%Y %H:%M')} | מערכת POC — אין להסתמך ללא אישור בודק מוסמך",
                 W, 7.5)]
    doc.build(story)
    return buf.getvalue()
