"""Report assembly (JSON for the screen) and the Hebrew text helpers of the defects PDF.

Hebrew text is wrapped in *logical* order first and only then converted to visual order line by line
(python-bidi), so multi-line text keeps the correct line order.
"""
from __future__ import annotations

import re

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from sqlalchemy.orm import Session

from .config import settings
from .models import CheckRun, PermitCase

REPORT_TITLES = {
    "completeness": "דוח שלמות ותנאי סף",
    "rights": "דוח זכויות ותנאים",
    "reviewer": "דוח בודק",
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
        "run": {"id": run.id, "version": run.version, "at": run.started_at.isoformat(), "ruleset_hash": run.ruleset_hash,
                "inputs": run.input_hashes, "duration_ms": run.duration_ms, "locked": run.locked,
                "ai_summary": run.summary.get("ai_summary"), "kb_passages": run.summary.get("kb_passages") or [],
                "review": run.summary.get("review")},
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


# ------------------------------------------------------------------ PDF text helpers (used by the defects PDF)

def _split_long(word: str, font: str, size: float, width: float) -> list[str]:
    """Break a token wider than the cell (e.g. DEMO-ADDITION-MAX-AREA) after '-', '_' or '/',
    falling back to a character split; otherwise reportlab would re-wrap a visual line."""
    if stringWidth(word, font, size) <= width:
        return [word]
    parts, cur = [], ""
    for piece in re.split(r"(?<=[-_/])", word):
        if cur and stringWidth(cur + piece, font, size) > width:
            parts.append(cur)
            cur = ""
        cur += piece
    parts.append(cur)
    out = []
    for p in parts:
        while stringWidth(p, font, size) > width and len(p) > 1:
            k = len(p)
            while k > 1 and stringWidth(p[:k], font, size) > width:
                k -= 1
            out.append(p[:k])
            p = p[k:]
        out.append(p)
    return out


def _wrap_logical(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for para in (text or "").split("\n"):
        cur = ""
        words = [w for word in para.split(" ") for w in _split_long(word, font, size, width)]
        for word in words:
            cand = (cur + " " + word).strip()
            if stringWidth(cand, font, size) <= width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines
