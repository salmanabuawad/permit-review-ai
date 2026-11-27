"""Study of a committee's public decisions (committee_meetings / committee_meeting_items): aggregates only.

No names, no addresses, no request numbers leave the database: the report gives counts, rates and recurring phrases.
Decisions are ground truth — this study informs people (and later the validation of the engine); nothing here feeds
the review engine.

Usage (server, user permit):  python scripts/study_meetings.py <committee_id> [--from 2016-01-01] [--md out.md] [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.meetings import OUTCOMES_HE  # noqa: E402
from app.models import CommitteeMeeting, CommitteeMeetingItem, PlanningCommittee  # noqa: E402

DECIDED = ("APPROVED", "APPROVED_CONDITIONS", "APPROVED_PARTIAL", "REJECTED")
RELIEFS = {
    "קו בניין": r"קו(?:ו)?\s*בני[י]?ן|קווי\s*בני[י]?ן|מרווח",
    "גובה": r"גובה|הגבהת",
    "מספר קומות": r"מס(?:פר)?['׳]?\s*קומות|קומה\s+נוספת|תוספת\s+קומה",
    "תכסית": r"תכסית",
    "שטחי בנייה / ניוד": r"ניוד|העברת\s+שטח|תוספת\s+שטח|שטחי\s+(?:ה)?בני|אחוזי\s+בני",
    "יחידות דיור": r"יח(?:ידת|ידות)?['\"״]?\s*ד(?:יור)?|תוספת\s+יח",
    "שימוש חורג": r"שימוש\s+חורג",
    "חניה": r"חני[יה]",
    "בריכה": r"בריכ",
    "גדר / קיר": r"גדר|קיר\s+תומך",
    "מרתף": r"מרתף",
    "פרגולה / סככה": r"פרגול|סככ",
}
REJECT_REASONS = {
    "פרוצדורלי: איחור / תם המועד / לא תוקן": r"באיחור|איחור|תם\s+פרק\s+הזמן|חלף\s+המועד|לא\s+תוקנה|טרם\s+הסתיימה|תיסגר|להגישה\s+בשנית|יש\s+להגיש\s+בשנית|נוסח\s+ההחלטה\s+הנו\s+אחיד",
    "סטייה ניכרת": r"סטייה\s+ניכרת",
    "בניגוד לתכנית / אינו תואם": r"בניגוד\s+ל|אינ[וה]\s+תוא[םמ]|לא\s+תוא[םמ]|חורג\s+מ",
    "חריגה מקו בניין": r"קו(?:ו)?\s*בני[י]?ן",
    "חריגה בשטחים / זכויות": r"זכויות|שטחי\s+(?:ה)?בני|אחוזי",
    "חסרים מסמכים / לא הושלם": r"לא\s+הושלמ|חוסר|חסר|השלמת\s+מסמכים|לא\s+הוגש",
    "התנגדויות / פגיעה בשכנים": r"התנגד|פגיעה|מטרד|שכנ",
    "קרקע חקלאית / שימוש": r"חקלאי|קרקע\s+חקלאית|שימוש",
    "בעלות / הסכמות": r"בעלות|הסכמת|חתימ",
}
CONDITIONS = {
    "פיקוד העורף / ממ\"ד": r"פיקוד\s+העורף|הג[\"״]א|ממ[\"״]ד",
    "כיבוי אש": r"כיבוי\s+אש|כבאות|רשות\s+הכבאות",
    "היטל השבחה / אגרות / תשלומים": r"השבחה|אגר|תשלום|היטל",
    "תיקון / עדכון תכנית": r"תיקון|לתקן|עדכון\s+(?:ה)?תכנית|תכנית\s+מתוקנת",
    "חתימות / הסכמות שכנים": r"חתימ|הסכמת",
    "מי שמאי / רמ\"י": r"רמ[\"״]י|מנהל\s+מקרקעי|רשות\s+מקרקעי",
    "אישור משרד החקלאות / ות\"ל": r"משרד\s+החקלאות|ולקחש|ות[\"״]ל|קרקע\s+חקלאית",
    "פסולת / פינוי": r"פסולת",
    "אישור יועץ / אחראי ביקורת": r"יועץ|אחראי\s+לביקורת|קונסטרוקט",
}


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "—"


def tag(text: str | None, table: dict) -> list[str]:
    t = text or ""
    return [k for k, rx in table.items() if re.search(rx, t)]


def study(committee_id: str, since: dt.date) -> dict:
    with SessionLocal() as s:
        c = s.get(PlanningCommittee, committee_id)
        rows = s.execute(select(CommitteeMeetingItem, CommitteeMeeting).join(CommitteeMeeting)
                         .where(CommitteeMeeting.committee_id == committee_id, CommitteeMeeting.meeting_date >= since)).all()
    items = [(i, m) for i, m in rows]
    done = [(i, m) for i, m in items if i.state == "done"]
    out = {"committee": c.name_he, "since": since.isoformat(), "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
           "meetings": len({m.id for _, m in items}), "items": len(items), "items_read": len(done),
           "with_decision_text": sum(1 for i, _ in done if (i.decision or "").strip())}
    out["outcomes"] = dict(collections.Counter(i.outcome for i, _ in done).most_common())

    def table(key):
        t = collections.defaultdict(collections.Counter)
        for i, m in done:
            t[key(i, m)][i.outcome] += 1
        return {k: dict(v) for k, v in sorted(t.items(), key=lambda kv: str(kv[0]))}
    out["by_year"] = table(lambda i, m: m.meeting_date.year if m.meeting_date else "?")
    out["by_meeting_type"] = table(lambda i, m: m.type_he or m.type_code)
    out["by_item_type"] = table(lambda i, m: i.item_type or "—")

    req = [(i, m) for i, m in done if i.item_type and "בקש" in i.item_type and i.outcome in DECIDED]
    def has_relief(i):        # a reliefs field, a request type "כולל הקלות", or a relief named in the essence / decision
        return bool((i.reliefs or "").strip()) or "כולל הקלות" in (i.subject or "") or bool(re.search(r"הקל[הות]", (i.essence or "") + " " + (i.decision or "")))
    with_r = [(i, m) for i, m in req if has_relief(i)]
    without = [(i, m) for i, m in req if not has_relief(i)]
    approved = lambda lst: sum(1 for i, _ in lst if i.outcome in ("APPROVED", "APPROVED_CONDITIONS", "APPROVED_PARTIAL"))  # noqa: E731
    out["requests_decided"] = len(req)
    out["approval_rate_with_reliefs"] = {"n": len(with_r), "approved": approved(with_r)}
    out["approval_rate_without_reliefs"] = {"n": len(without), "approved": approved(without)}
    rel = collections.defaultdict(lambda: [0, 0])
    for i, _ in with_r:
        for k in tag(" ".join(x for x in (i.reliefs, i.essence) if x), RELIEFS) or ["אחר"]:
            rel[k][0] += 1
            rel[k][1] += i.outcome != "REJECTED"
    out["reliefs"] = {k: {"n": n, "approved": a} for k, (n, a) in sorted(rel.items(), key=lambda kv: -kv[1][0])}
    rejected = [i for i, _ in done if i.outcome == "REJECTED"]
    out["rejection_reasons"] = dict(collections.Counter(k for i in rejected for k in tag(i.decision, REJECT_REASONS) or ["לא זוהה"]).most_common())
    cond = [i for i, _ in done if i.outcome == "APPROVED_CONDITIONS"]
    out["approval_conditions"] = dict(collections.Counter(k for i in cond for k in tag(i.decision, CONDITIONS)).most_common())
    loc = collections.defaultdict(collections.Counter)
    for i, _ in done:
        if i.outcome in DECIDED:
            loc[i.locality or "לא צוין"][i.outcome] += 1
    out["top_localities"] = {k: dict(v) for k, v in sorted(loc.items(), key=lambda kv: -sum(kv[1].values()))[:15]}
    out["decision_source"] = dict(collections.Counter(i.decision_source or ("page" if (i.decision or "").strip() else "none")
                                                     for i, _ in done))
    prot = [(i, m) for i, m in done if i.protocol]
    out["with_protocol"] = len(prot)
    rec = collections.Counter()
    for i, _ in prot:
        r = (i.protocol.get("recommendation") or "").strip()
        if not r or i.outcome not in DECIDED:
            continue
        rec_ok = not re.search(r"לא\s+לאשר|לסרב|לדחות", r) and bool(re.search(r"לאשר|ממליצ", r))
        rec[("ממליץ לאשר" if rec_ok else "ממליץ לסרב / אחר", "אושר" if i.outcome != "REJECTED" else "נדחה")] += 1
    out["recommendation_vs_decision"] = {f"{a} → {b}": v for (a, b), v in sorted(rec.items())}
    opin = collections.Counter()
    for i, _ in prot:
        if i.outcome == "REJECTED":
            for k in tag(i.protocol.get("opinion"), REJECT_REASONS) or ["לא זוהה"]:
                opin[k] += 1
    out["rejected_opinion_reasons"] = dict(opin.most_common())
    des = collections.defaultdict(collections.Counter)
    for i, _ in prot:
        if i.outcome in DECIDED and i.protocol.get("designation"):
            d = re.sub(r"\s*-\s*מבא.*$", "", i.protocol["designation"]).strip()[:40]
            des[d][i.outcome] += 1
    out["by_designation"] = {k: dict(v) for k, v in sorted(des.items(), key=lambda kv: -sum(kv[1].values()))[:15]}
    cov = collections.defaultdict(lambda: [0, 0])
    for i, m in done:
        cov[m.type_he or m.type_code][1] += 1
        cov[m.type_he or m.type_code][0] += bool((i.decision or "").strip())
    out["coverage_by_meeting_type"] = dict(cov)
    near = [(i, m) for i, m in done if (i.gush == "2832") or (i.plan and "0723718" in i.plan) or (i.locality or "").startswith("זיקים")]
    out["zikim_block_2832_plan_0723718"] = {"items": len(near), "outcomes": dict(collections.Counter(i.outcome for i, _ in near)),
                                            "reliefs": dict(collections.Counter(k for i, _ in near for k in tag(i.reliefs, RELIEFS)))}
    return out


def markdown(r: dict) -> str:
    L = [f"# החלטות הוועדה המקומית {r['committee']} — ניתוח ({r['since'][:4]}–היום)", "",
         f"נוצר {r['generated']} מתוך הרשומות הפומביות באתר הוועדה. נתונים מצטברים בלבד — ללא שמות, כתובות או מספרי בקשות.",
         "ההחלטות הן אמת־מידה: הן אינן קלט של מנוע הבדיקה.", "",
         f"- ישיבות: {r['meetings']} · סעיפים: {r['items']} · נקראו: {r['items_read']} · עם נוסח החלטה: {r['with_decision_text']}", "",
         "## תוצאות", "", "| תוצאה | סעיפים |", "|---|---|"]
    L += [f"| {OUTCOMES_HE.get(k, k)} | {v} |" for k, v in r["outcomes"].items()]
    outs = [k for k in ("APPROVED", "APPROVED_CONDITIONS", "APPROVED_PARTIAL", "REJECTED", "DEFERRED", "DEPOSIT", "PLAN_APPROVED", "RECOMMENDED", "OPEN", "OTHER")]
    for title, key in (("לפי שנה", "by_year"), ("לפי סוג ישיבה", "by_meeting_type"), ("לפי סוג סעיף", "by_item_type")):
        L += ["", f"## {title}", "", "| | " + " | ".join(OUTCOMES_HE[o] for o in outs) + " | סה\"כ |", "|---" * (len(outs) + 2) + "|"]
        for k, v in r[key].items():
            L.append(f"| {k} | " + " | ".join(str(v.get(o, 0)) for o in outs) + f" | {sum(v.values())} |")
    w, wo = r["approval_rate_with_reliefs"], r["approval_rate_without_reliefs"]
    L += ["", "## בקשות להיתר שהוכרעו", "", f"- הוכרעו: {r['requests_decided']}",
          f"- עם הקלות: {w['n']}, אושרו {pct(w['approved'], w['n'])}", f"- ללא הקלות: {wo['n']}, אושרו {pct(wo['approved'], wo['n'])}",
          "", "### הקלות מבוקשות", "", "| הקלה | בקשות | אושרו |", "|---|---|---|"]
    L += [f"| {k} | {v['n']} | {pct(v['approved'], v['n'])} |" for k, v in r["reliefs"].items()]
    L += ["", "## נימוקי דחייה חוזרים (זיהוי לפי ניסוח)", "", "| נימוק | סעיפים |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in r["rejection_reasons"].items()]
    L += ["", "## תנאים חוזרים באישור בתנאים", "", "| תנאי | סעיפים |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in r["approval_conditions"].items()]
    L += ["", "## יישובים (סעיפים שהוכרעו)", "", "| יישוב | אושר | אושר בתנאים | נדחה |", "|---|---|---|---|"]
    L += [f"| {k} | {v.get('APPROVED', 0)} | {v.get('APPROVED_CONDITIONS', 0)} | {v.get('REJECTED', 0)} |" for k, v in r["top_localities"].items()]
    L += ["", "## מקור נוסח ההחלטה", "", "| מקור | סעיפים |", "|---|---|"]
    src_he = {"page": "דף הסעיף", "protocol": "קובץ ההחלטות", "none": "אין נוסח"}
    L += [f"| {src_he.get(k, k)} | {v} |" for k, v in r["decision_source"].items()]
    L += ["", f"## המלצת הצוות מול ההחלטה ({r['with_protocol']} סעיפים עם קובץ החלטות)", "", "| המלצה → החלטה | סעיפים |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in r["recommendation_vs_decision"].items()]
    L += ["", "## מה כתוב בחוות הדעת של בקשות שנדחו", "", "| נושא | סעיפים |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in r["rejected_opinion_reasons"].items()]
    L += ["", "## לפי ייעוד (מקובץ ההחלטות)", "", "| ייעוד | אושר | אושר בתנאים | נדחה |", "|---|---|---|---|"]
    L += [f"| {k} | {v.get('APPROVED', 0)} | {v.get('APPROVED_CONDITIONS', 0)} | {v.get('REJECTED', 0)} |" for k, v in r["by_designation"].items()]
    cov = r["coverage_by_meeting_type"]
    L += ["", "## כיסוי: סעיפים עם נוסח החלטה (דף הסעיף או קובץ ההחלטות)", "", "| סוג ישיבה | עם החלטה | סעיפים |", "|---|---|---|"]
    L += [f"| {k} | {v[0]} | {v[1]} |" for k, v in cov.items()]
    z = r["zikim_block_2832_plan_0723718"]
    L += ["", "## זיקים — גוש 2832 / תכנית 633-0723718", "", f"- סעיפים: {z['items']}",
          "- תוצאות: " + ", ".join(f"{OUTCOMES_HE.get(k, k)} {v}" for k, v in z["outcomes"].items()),
          "- הקלות: " + (", ".join(f"{k} {v}" for k, v in z["reliefs"].items()) or "—"), "",
          "## מגבלות", "", "- הסיווג לפי ניסוח ההחלטה (מילות מפתח); החלטות מורכבות עשויות להיות מסווגות 'אחר'.",
          "- סעיפים בלי נוסח החלטה (לא בדף הסעיף ולא בקובץ ההחלטות המונגש) נספרים 'טרם הוחלט'. קבצי החלטות מונגשים קיימים מאמצע 2023; לישיבות קודמות יש רק PDF שהטקסט העברי בו הפוך — טרם נקרא.",
          "- נימוקים ותנאים מזוהים לפי ניסוח; סעיף יכול להופיע בכמה קטגוריות."]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("committee_id")
    ap.add_argument("--from", dest="since", default="2016-01-01")
    ap.add_argument("--md")
    ap.add_argument("--json")
    a = ap.parse_args()
    r = study(a.committee_id, dt.date.fromisoformat(a.since))
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    md = markdown(r)
    if a.md:
        Path(a.md).write_text(md)
    print(md)


if __name__ == "__main__":
    main()
