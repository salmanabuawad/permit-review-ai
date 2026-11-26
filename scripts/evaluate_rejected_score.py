"""Scoring for evaluate_rejected.py — runs only after the engine result is frozen.

The official reasons are the committee's own decision text (details-page decision and protocol excerpts, text layer
without OCR, so partly broken RTL). Each case's reasons are tagged with topics by keyword; a tag is evidence that the
topic was raised, not a full reading. Per topic the engine is DETECTED (confirmed finding), FLAGGED (open check on that
topic), MISSED (the engine had the input for the topic but raised nothing) or NO_INPUT (the topic needs documents or
drawings the public package does not hold — not counted as missed). Output: <package>/../results/score.json and
score.md (case ids and topics only, no personal data).
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from evaluate_blind import eval_store

TOPICS = {
    "route": r"מסלול שגוי|תוגש במסלול|להגיש במסלול|במסלול הקלה|במסלול רגיל|במסלול ה?רישוי|הוגשה במסלול|"
             r"במסלול לא|יש לבקש בהקלה",
    "incomplete_or_preconditions": r"תנאים מוקדמים|בקרה מרחבית|לא הושלמ|השלמת מסמכים|חוסרים|אינה בשלה|לא עודכנ|לא תוקנ|לא הגיב|"
                                   r"לא השלים|חוסר מעש|לא הוגש|לא צורפ",
    "rights_area": r"חריגה ב?שטח|שטחים מותרים|חריגה מ?ה?זכויות|עודף שטח|זכויות ה?בני|אחוזי ה?בני|תכסית",
    "building_lines": r"קווי? ה?בני[י]?ן|לחרוג מ\s?\d+\s?מ'|מרחק",
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
RIGHTS_TOPICS = {"rights_area", "height_level", "building_lines"}


def official(store: Path, case: str) -> str:
    d = store / case
    parts = []
    for f in [d / "committee_decisions" / "decision_excerpts.txt", d / "rejection_reasons" / "rejection_evidence.json"]:
        if f.exists():
            t = f.read_text(encoding="utf-8", errors="replace")
            if f.suffix == ".json":
                t = "\n".join(x.get("text", "") for x in json.loads(t) if isinstance(x, dict))
            parts.append(t)
    return re.sub(r"\s+", " ", "\n".join(parts))


def engine_on(topic: str, e: dict) -> str:
    if topic == "route":
        if e["verdict"] in ("WRONG_ROUTE", "PROHIBITED_DEVIATION"):
            return "DETECTED" if e["confirmed"] else "FLAGGED"
        # same rule as evaluate_blind.score: an undecided route (open checks, needs named inputs) is FLAGGED
        if e["verdict"] == "INSUFFICIENT_EVIDENCE":
            return "FLAGGED"
        if e["route_filed"] is None:
            return "NO_INPUT"    # an old paper application: the register does not say which route was filed
        return "MISSED" if e["verdict"] != "NO_RIGHTS" else "NO_INPUT"
    if topic in ("height_level", "building_lines") and any(c["topic"] == "building_provisions" for c in e["checks"]):
        return "FLAGGED"         # the building-provisions limits apply and are open until the drawings are read
    if topic in RIGHTS_TOPICS:
        if e["verdict"] == "NO_RIGHTS":
            return "NO_INPUT"
        open_ = [c for c in e["checks"] if c["status"] in ("NOT_CHECKED", "POSSIBLE_DEVIATION")]
        dev = [c for c in e["checks"] if c["status"] in ("RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED")]
        return "DETECTED" if dev and all(c["confirmable"] for c in dev) else "FLAGGED" if dev or open_ else "MISSED"
    if topic == "relief_refused" and any(c["topic"] == "declared_relief" for c in e["checks"]):
        return "FLAGGED"         # the engine found the relief the request names, without classifying it
    return "NO_INPUT"            # documents, objections, publication, ownership ... need files the package lacks


def main(pkg: Path, engine: dict) -> None:
    store = eval_store() / pkg.name
    if not (store / "rejection_index.json").exists():
        raise SystemExit(f"labels not in the evaluation store: {store}")
    index = {x["case_id"]: x for x in json.loads((store / "rejection_index.json").read_text(encoding="utf-8"))}
    rows, tally = [], collections.Counter()
    by_topic = collections.defaultdict(collections.Counter)
    route_code = collections.Counter()
    for e in engine["cases"]:
        cid = e["case"]
        if "excluded" in e:
            rows.append({"case": cid, "excluded": e["excluded"]})
            tally["excluded"] += 1
            continue
        ix = index.get(cid, {})
        filed = {"81": "REGULAR", "82": "RELIEF", "83": "SHORT"}.get(str(ix.get("application_type_code")))
        route_code["match" if filed == e["route_filed"] else f"{filed}≠{e['route_filed']}"] += 1
        text = official(store, cid)
        topics = sorted(k for k, rx in TOPIC_RX.items() if rx.search(text))
        res = {t: engine_on(t, e) for t in topics}
        for t, r in res.items():
            by_topic[t][r] += 1
            tally[r] += 1
        unsupported = e["verdict"] in ("WRONG_ROUTE", "PROHIBITED_DEVIATION") and not {"route", "relief_refused"} & set(topics)
        rows.append({"case": cid, "confidence": ix.get("confidence"), "classification": ix.get("classification"),
                     "engine": e["verdict"] + (" (confirmed)" if e["confirmed"] else ""), "official_topics": topics,
                     "result": res, "engine_unsupported": unsupported, "reason_text_chars": len(text)})
    scored = [r for r in rows if "excluded" not in r]
    in_scope = tally["DETECTED"] + tally["FLAGGED"] + tally["MISSED"]
    summary = {
        "cases": len(rows), "excluded": tally["excluded"], "scored": len(scored),
        "cases_with_reason_text": sum(r["reason_text_chars"] > 0 for r in scored),
        "cases_without_topic": sum(not r["official_topics"] for r in scored),
        "topic_mentions": sum(len(r["official_topics"]) for r in scored),
        "in_engine_scope": in_scope, "DETECTED": tally["DETECTED"], "FLAGGED": tally["FLAGGED"],
        "MISSED": tally["MISSED"], "NO_INPUT": tally["NO_INPUT"],
        "engine_findings_unsupported_by_reasons": [r["case"] for r in scored if r["engine_unsupported"]],
        "route_filed_vs_register_code": dict(route_code),
        "by_topic": {t: dict(c) for t, c in sorted(by_topic.items(), key=lambda kv: -sum(kv[1].values()))},
    }
    out = pkg.parent / "results"
    (out / "score.json").write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
