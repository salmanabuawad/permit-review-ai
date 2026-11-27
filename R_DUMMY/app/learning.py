"""Learning from decided cases.

The administrator loads a whole case (the request package, through the normal import) and the committee's decision.
The engine reviews the case as usual — the decision is never an engine input — and the decision is then compared
with the engine's findings, topic by topic:

  * confirmed  — the committee raised a topic the engine also found (the rules behind it gain support);
  * missed     — a reason the engine did not find: becomes a rule draft (kind "committee_reason") in the existing
                 drafts workflow; it takes effect only after the administrator turns it into a rule and approves it;
  * not raised — the engine reported something the committee did not mention; in an approved decision this is a
                 possible false defect and counts against the rule.

The knowledge base is updated at once with what informs but cannot decide: the decision text (a source document of
the authority, with its snapshot and searchable unverified passages), the precedent (plans, parcel, outcome, topics)
shown on similar requests, and per-rule statistics shown in the rules screen.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .intake.protocol import classify_decision, split_numbered
from .intake.schemas import DECISION_OUTCOMES_HE
from .models import CommitteeDecision, LearningRecord, PermitCase, RuleDraft, SourceDocument, SourceSnapshot

# Topics of committee reasons (same keyword rules as the blind evaluation of rejected applications, docs/12).
TOPICS = {
    "route": r"מסלול שגוי|תוגש במסלול|להגיש במסלול|במסלול הקלה|במסלול רגיל|במסלול ה?רישוי|הוגשה במסלול|"
             r"במסלול לא|יש לבקש בהקלה",
    "incomplete_or_preconditions": r"תנאים מוקדמים|בקרה מרחבית|לא הושלמ|השלמת מסמכים|חוסרים|אינה בשלה|לא עודכנ|לא תוקנ|לא הגיב|"
                                   r"לא השלים|חוסר מעש|לא הוגש|לא צורפ",
    "rights_area": r"חריגה ב?שטח|שטחים מותרים|חריגה מ?ה?זכויות|עודף שטח|זכויות ה?בני|אחוזי ה?בני|תכסית",
    "building_lines": r"קו(?:וי)? ה?בני[י]?ן|לחרוג מ\s?\d+\s?מ'|מרחק",
    "height_level": r"גובה|מפלס",
    "relief_refused": r"לא לאשר את ה?הקל|דחיית ה?הקל|הקלה ניכרת|סטי?יה ניכרת|ההקלה אינה|לא נמצאה הצדקה",
    "housing_units": r"יחידת דיור|יחידות דיור|חלוקה נוספת|יח\"ד נוספת",
    "objections": r"התנגד",
    "use_zoning": r"שימוש חורג|ייעוד|יעוד הקרקע|שימוש שאינו",
    "unpermitted_existing": r"בנוי בפועל|ללא היתר|להריסה|הריסת|אינה משקפת",
    "publication": r"לא פורסמ|פרסום ה?הקל",
    "ownership_consent": r"הוכחת בעלות|הסכמת|חתימת ה?בעלים|רמ\"?י|מנהל מקרקעי",
    "plan_conflict": r"בניגוד ל|אינו תואם|אינה תואמת|לא תואם|סותר|בקשה למידע",
    "external_authority": r"מי אשקלון|תאגיד|כיבוי|פיקוד העורף|רשות העתיקות|חברת חשמל|ניקוז|משרד הבריאות",
}
TOPIC_RX = {k: re.compile(v) for k, v in TOPICS.items()}
TOPIC_HE = {
    "route": "מסלול רישוי", "incomplete_or_preconditions": "השלמות ותנאים מוקדמים", "rights_area": "שטחים וזכויות",
    "building_lines": "קווי בניין", "height_level": "גובה ומפלסים", "relief_refused": "הקלות",
    "housing_units": "יחידות דיור", "objections": "התנגדויות", "use_zoning": "שימוש וייעוד",
    "unpermitted_existing": "בנייה ללא היתר", "publication": "פרסום", "ownership_consent": "בעלות והסכמות",
    "plan_conflict": "התאמה לתכנית", "external_authority": "גורמי חוץ",
}
APPROVED = {"approved", "approved_with_conditions", "renewed", "objection_rejected", "objection_partially_accepted"}
OUTCOMES = set(DECISION_OUTCOMES_HE)


def topics_of(text: str) -> list[str]:
    return sorted(k for k, rx in TOPIC_RX.items() if rx.search(text or ""))


def parse_decision(text: str) -> dict:
    """Outcome and numbered reasons / conditions of a committee decision, each with its topics."""
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    parts = split_numbered(text.replace("\n", " "))
    numbered = any(no for no, _ in parts)
    reasons = [{"no": no, "text_he": t[:2000], "topics": topics_of(t)} for no, t in parts
               if len(t) > 3 and (no or not numbered)]          # the opening sentence of a numbered list is no reason
    if not reasons and text:
        reasons = [{"no": None, "text_he": text[:2000], "topics": topics_of(text)}]
    return {"outcome": classify_decision(text), "reasons": reasons}


def _finding_topics(f) -> list[str]:
    return topics_of(" ".join(x for x in (f.title_he, f.explanation_he, f.rule_id.replace("-", " ")) if x))


def record_decision(s: Session, case: PermitCase, user: str, filename: str, body: bytes,
                    outcome: str | None = None) -> LearningRecord:
    """Store the decision (as a source document of the authority + a committee decision) and queue the learning."""
    from .source_monitor import service as source_service
    if outcome and outcome not in OUTCOMES:
        raise ValueError("תוצאת החלטה לא מוכרת")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".txt"
    pages = source_service.extract_text(body, ext)             # validates the file too
    text = "\n".join(pages).strip()
    if len(text) < 10:
        raise ValueError("לא חולץ טקסט מההחלטה — יש להעלות קובץ עם שכבת טקסט או להדביק את נוסח ההחלטה")
    parsed = parse_decision(text)
    outcome = outcome or parsed["outcome"]
    doc = source_service.ingest_upload(s, case.tenant_id, user, filename, body, None)
    doc.title = f"החלטת ועדה — בקשה {case.case_number}"[:400]
    dec = CommitteeDecision(tenant_id=case.tenant_id, case_id=case.id, outcome=outcome, text=text[:20000],
                            conditions=[r["text_he"] for r in parsed["reasons"]])
    s.add(dec)
    s.flush()
    for old in s.scalars(select(LearningRecord).where(LearningRecord.case_id == case.id,
                                                      LearningRecord.status != "superseded")):
        old.status = "superseded"                               # a corrected decision replaces the earlier one
    rec = LearningRecord(tenant_id=case.tenant_id, case_id=case.id, decision_id=dec.id, source_document_id=doc.id,
                         status="pending", outcome=outcome, reasons=parsed["reasons"], result={}, created_by=user)
    s.add(rec)
    audit.record(s, case.tenant_id, user, "learning.decision", "permit_case", case.id,
                 {"outcome": outcome, "reasons": len(parsed["reasons"]), "document_id": doc.id})
    s.flush()
    return rec


def process(s: Session, rec: LearningRecord) -> bool:
    """Compare the decision with the case's latest review; False while the case is not reviewed yet."""
    from .services import processing_status
    case = s.get(PermitCase, rec.case_id)
    if case is None or not case.runs or not processing_status(case)["ready"]:
        return False
    run = case.runs[-1]
    external = [f for f in run.findings if "EXTERNAL" in (f.flags or [])]
    approved = rec.outcome in APPROVED
    reason_topics = {t for r in rec.reasons for t in r["topics"]}
    confirmed, not_raised = [], []
    for f in external:
        ft = set(_finding_topics(f))
        row = {"rule_id": f.rule_id, "title_he": f.title_he, "topics": sorted(ft)}
        (confirmed if ft & reason_topics else not_raised).append(row)
    found_topics = {t for r in confirmed for t in r["topics"]}
    missed = [r for r in rec.reasons if not r["topics"] or not set(r["topics"]) & found_topics]
    if approved:
        missed = []                                  # conditions of an approval are not missed defects
    doc = s.get(SourceDocument, rec.source_document_id) if rec.source_document_id else None
    snap = s.scalars(select(SourceSnapshot).where(SourceSnapshot.document_id == doc.id)
                     .order_by(SourceSnapshot.id.desc())).first() if doc else None
    drafts = 0
    if doc:
        have = {d.key for d in s.scalars(select(RuleDraft).where(RuleDraft.document_id == doc.id))}
        for r in missed:
            key = hashlib.sha1(("committee_reason|" + r["text_he"]).encode()).hexdigest()
            if key in have:
                continue
            s.add(RuleDraft(tenant_id=rec.tenant_id, document_id=doc.id, snapshot_id=snap.id if snap else None, key=key,
                            page=1, section=r["no"], kind="committee_reason", topics=r["topics"],
                            text_he=r["text_he"], values=[], status="open",
                            note=f"נימוק ועדה שהבדיקה לא זיהתה — בקשה {case.case_number}"))
            drafts += 1
    rec.result = {
        "run_version": run.version, "approved": approved, "decision_he": DECISION_OUTCOMES_HE.get(rec.outcome, rec.outcome),
        "confirmed": confirmed, "missed": missed, "not_raised": not_raised,
        "possible_false_defects": not_raised if approved else [], "drafts_created": drafts,
        "topics": sorted(reason_topics),
    }
    rec.status, rec.processed_at = "done", dt.datetime.now(dt.timezone.utc)
    audit.record(s, rec.tenant_id, "system:learning", "learning.processed", "permit_case", rec.case_id,
                 {"confirmed": len(confirmed), "missed": len(missed), "not_raised": len(not_raised), "drafts": drafts})
    return True


def process_pending(s: Session) -> int:
    """Run by the background worker: every queued record whose case is reviewed."""
    n = 0
    for rec in s.scalars(select(LearningRecord).where(LearningRecord.status == "pending")):
        try:
            if process(s, rec):
                s.commit()
                n += 1
        except Exception as e:                       # noqa: BLE001 — recorded on the record
            s.rollback()
            rec = s.get(LearningRecord, rec.id)
            rec.status, rec.result = "failed", {"error": f"{type(e).__name__}: {str(e)[:300]}"}
            s.commit()
    return n


def record_dict(rec: LearningRecord, case: PermitCase | None = None) -> dict:
    return {"id": rec.id, "case_id": rec.case_id, "case_number": case.case_number if case else None,
            "status": rec.status, "outcome": rec.outcome, "outcome_he": DECISION_OUTCOMES_HE.get(rec.outcome, rec.outcome),
            "reasons": [{**r, "topics_he": [TOPIC_HE.get(t, t) for t in r["topics"]]} for r in rec.reasons],
            "result": rec.result, "source_document_id": rec.source_document_id,
            "created_at": rec.created_at.isoformat(), "processed_at": rec.processed_at.isoformat() if rec.processed_at else None}


def precedents(s: Session, case: PermitCase, limit: int = 10) -> list[dict]:
    """Decided cases of the same authority sharing a plan or the parcel block — information only, never a finding."""
    plans = set(case.applicable_plans or [])
    out = []
    for rec in s.scalars(select(LearningRecord).where(LearningRecord.tenant_id == case.tenant_id,
                                                      LearningRecord.status == "done",
                                                      LearningRecord.case_id != case.id)
                         .order_by(LearningRecord.created_at.desc())):
        other = s.get(PermitCase, rec.case_id)
        if other is None:
            continue
        shared = sorted(plans & set(other.applicable_plans or []))
        same_block = bool(case.gush and case.gush == other.gush)
        if not shared and not same_block:
            continue
        out.append({"case_number": other.case_number, "outcome_he": DECISION_OUTCOMES_HE.get(rec.outcome, rec.outcome),
                    "approved": rec.outcome in APPROVED, "plans": shared, "same_block": same_block,
                    "topics_he": [TOPIC_HE.get(t, t) for t in (rec.result or {}).get("topics", [])]})
        if len(out) >= limit:
            break
    return out


def rule_stats(s: Session, tenant: str) -> dict:
    """Per rule: how often a committee decision confirmed it, and how often it was not raised in an approval."""
    stats: dict[str, dict] = {}
    for rec in s.scalars(select(LearningRecord).where(LearningRecord.tenant_id == tenant, LearningRecord.status == "done")):
        res = rec.result or {}
        for r in res.get("confirmed", []):
            stats.setdefault(r["rule_id"], {"confirmed": 0, "not_raised_in_approval": 0})["confirmed"] += 1
        for r in res.get("possible_false_defects", []):
            stats.setdefault(r["rule_id"], {"confirmed": 0, "not_raised_in_approval": 0})["not_raised_in_approval"] += 1
    return stats
