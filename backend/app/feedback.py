"""Controlled professional feedback (Permit360 §15): corrections become classified records, then — only after an
administrator accepts them — regression cases that every rule change is measured against. No self-modification:
nothing here edits a rule, a prompt or an algorithm.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .models import CheckRun, FeedbackRecord, Finding, PdgNode, RegressionCase

CATEGORIES = {
    "application_exception": "חריג ספציפי לבקשה",
    "algorithm_defect": "פגם באלגוריתם / מדידה",
    "interpretation_error": "שגיאת פרשנות רגולטורית",
    "missing_knowledge": "ידע חסר (מקור / תכנית)",
    "extraction_error": "שגיאת חילוץ משרטוט או מסמך",
    "prompt_deficiency": "ליקוי בהנחיה למודל",
    "unclassified": "לא סווג",
}
OUTCOMES = ("PASS", "FAIL", "UNCERTAIN", "NA")


def record_override(s: Session, f: Finding, user: str, reason: str, category: str | None,
                    corrected_status: str | None, corrected_value: float | None) -> FeedbackRecord:
    """Called when a reviewer overrides a finding."""
    category = category if category in CATEGORIES else "unclassified"
    if corrected_status is not None and corrected_status not in OUTCOMES:
        raise ValueError("תוצאה מתוקנת לא מוכרת")
    run = s.get(CheckRun, f.run_id)
    node = s.scalars(select(PdgNode).where(PdgNode.run_id == f.run_id, PdgNode.key == f.rule_id)).first()
    candidate = {}
    if node is not None and corrected_status and category != "application_exception":
        facts = dict((node.inputs or {}).get("facts") or {})
        candidate = {"facts": facts, "expect": corrected_status}
    similar = []
    for other in s.scalars(select(Finding).where(Finding.tenant_id == f.tenant_id, Finding.rule_id == f.rule_id,
                                                 Finding.status == f.status, Finding.id != f.id,
                                                 Finding.reviewer_decision.is_(None)).limit(200)):
        r = s.get(CheckRun, other.run_id)
        latest = s.scalars(select(CheckRun.id).where(CheckRun.case_id == r.case_id).order_by(CheckRun.version.desc())).first()
        if r.case_id != run.case_id and latest == r.id:
            similar.append({"finding_id": other.id, "case_id": r.case_id, "run_version": r.version})
    rec = FeedbackRecord(tenant_id=f.tenant_id, finding_id=f.id, run_id=f.run_id, case_id=run.case_id, rule_id=f.rule_id,
                         rule_version=f.rule_version, category=category, reason=reason,
                         original={"status": f.status, "measured": f.measured_value, "threshold": f.threshold,
                                   "explanation": f.explanation_he},
                         corrected={"status": corrected_status, "value": corrected_value}, candidate=candidate,
                         similar=similar[:50], status="open", created_by=user)
    s.add(rec)
    s.flush()
    return rec


def decide(s: Session, rec: FeedbackRecord, user: str, action: str, note: str) -> RegressionCase | None:
    """accept: becomes a regression case (needs a candidate); dismiss: closed with a note. Shared rules unchanged."""
    if rec.status != "open":
        raise ValueError("הרשומה כבר טופלה")
    if action not in ("accept", "dismiss"):
        raise ValueError("פעולה לא מוכרת")
    rc = None
    if action == "accept":
        if not rec.candidate:
            raise ValueError("אין מקרה בדיקה (חסרה תוצאה מתוקנת או שהחריג ספציפי לבקשה)")
        rc = RegressionCase(tenant_id=rec.tenant_id, rule_id=rec.rule_id, facts=rec.candidate["facts"],
                            expect=rec.candidate["expect"], feedback_id=rec.id)
        s.add(rc)
    rec.status, rec.decided_by, rec.decision_note = ("accepted" if action == "accept" else "dismissed"), user, note
    audit.record(s, rec.tenant_id, user, f"feedback.{action}", "feedback", rec.id, {"rule_id": rec.rule_id, "note": note})
    s.flush()
    return rc


def run_regression(s: Session, tenant: str, rules: list) -> dict:
    """Evaluate the current rules on every accepted regression case of the authority."""
    from .rules.engine import _nest, evaluate_rule
    by_id = {r.id: r for r in rules}
    out = {"cases": 0, "passed": 0, "failed": [], "missing_rule": [], "at": dt.datetime.now(dt.timezone.utc).isoformat()}
    for rc in s.scalars(select(RegressionCase).where(RegressionCase.tenant_id == tenant)):
        out["cases"] += 1
        rule = by_id.get(rc.rule_id)
        if rule is None:
            out["missing_rule"].append(rc.rule_id)
            continue
        res = evaluate_rule(rule, _nest(rc.facts), {}, False)
        if res.status == rc.expect:
            out["passed"] += 1
        else:
            out["failed"].append({"case": rc.id, "rule_id": rc.rule_id, "expect": rc.expect, "got": res.status})
    return out
