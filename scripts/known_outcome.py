"""Reprocess a known-outcome regression case and compare the engine with the committee's decisions.

    python scripts/known_outcome.py validation/known_outcome/20221189 [--out exports/reports]

Known-outcome cases are NOT blind tests: the expected outcome is in the case file. The engine is run first on the
application facts only (application block); committee-reported values are added afterwards as a second, labelled pass
(they are never presented as independently calculated geometry). Output: <out>/<id>_comparison.json and a Hebrew RTL
report <out>/<id>_comparison.html with an external part (evidence-backed defects only) and the internal record.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.lifecycle import ApplicationVersion, ApplicationVersionComparator, Decision, build_lifecycle  # noqa: E402
from app.rules import route as R  # noqa: E402
from app.rules.applicability import AppContext, ApplicableRegulationResolver  # noqa: E402
from app.rules.components import Component, Measure, validate_component  # noqa: E402
from app.rules.relief import ReliefRequest, ReliefValidationEngine  # noqa: E402


def run(case_dir: Path, process_history: list | None = None, decision_texts: list | None = None) -> dict:
    t0 = time.perf_counter()
    c = yaml.safe_load((case_dir / "case.yaml").read_text(encoding="utf-8"))
    a = c["application"]
    sub = dt.date.fromisoformat(a["submission_date"])
    ctx = AppContext(c["application_id"], sub, a["plans"], a.get("block"), a.get("parcel"), a.get("lot"),
                     a.get("main_use"), activity=a.get("request_text", ""))
    res = ApplicableRegulationResolver().resolve(ctx)
    law = yaml.safe_load((ROOT / "knowledge/law/deviation_regulations_2002.yaml").read_text(encoding="utf-8"))
    eng = ReliefValidationEngine(law)
    reliefs = [eng.assess(ReliefRequest(r["component"], r["attribute"], r.get("requested"), r.get("source", "declared"),
                                        r.get("text", ""), r.get("justification")), res.limits) for r in a.get("reliefs", [])]
    # pass 1 — application facts only
    base = dict(application_id=c["application_id"], submission_date=sub, plans=a["plans"], lot=a.get("lot"),
                main_use=a.get("main_use"), selected_route=a.get("route_filed"), request_text=a.get("request_text", ""),
                total_main_m2=a["declared"].get("main_m2"), total_service_m2=a["declared"].get("service_m2"))
    route1 = R.validate(R.Proposal(**base))
    # pass 2 — with the committee-reported split by floor (labelled)
    cr = c.get("committee_reported") or {}
    route2 = R.validate(R.Proposal(**base, main_above_m2=cr.get("main_above_m2"), main_below_m2=0.0,
                                   service_above_m2=cr.get("service_above_m2"), service_below_m2=cr.get("service_below_m2"),
                                   split_source="committee_reported")) if cr else None
    comps = []
    for r in a.get("reliefs", []):
        comp = Component(r["component"], {r["attribute"]: Measure(r["requested"], r.get("source", "declared"))},
                         reliefs=[r["attribute"]])
        comps += [f.as_dict() for f in validate_component(comp, res.limits)]
    if process_history is not None:
        life = build_lifecycle(c["application_id"], process_history, decision_texts or [])
    else:                                         # fixture only: the expected decisions as register steps
        steps = {"RETURNED_FOR_CORRECTIONS": "בקרה מרחבית-הוחזר לעורך הבקשה להמשך טיפול", "APPLICATION_APPROVED": "הפקת היתר"}
        ph = [{"description": steps[d["type"]], "date": d["date"]} for d in c["expected"]["decisions"] if d["type"] in steps]
        life = build_lifecycle(c["application_id"], ph, [{"date": d["date"], "meeting": d.get("meeting"),
                               "text": d.get("reason", "") + (" החלטה לסרב להקלה" if d["type"] == "RELIEF_REJECTED" else ""),
                               "reference": d.get("regulatory_reference")} for d in c["expected"]["decisions"]
                               if d["type"] in ("RELIEF_REJECTED", "APPLICATION_REJECTED")])
    orig = ApplicationVersion("original", "application (register)", areas={"main_m2": a["declared"]["main_m2"],
                              "service_m2": a["declared"]["service_m2"]},
                              components={f"{r['component']}.{r['attribute']}": r["requested"] for r in a.get("reliefs", [])},
                              reliefs=[f"{r['component']}.{r['attribute']}" for r in a.get("reliefs", [])])
    av = c.get("approved_version") or {}
    appr = ApplicationVersion("approved", "permit (validation evidence)", areas=av.get("areas", {}),
                              geometry_available=bool(av.get("geometry_available")))
    changes = [asdict(x) for x in ApplicationVersionComparator().compare(orig, appr, life.decisions)]
    comparison = compare(c["expected"], reliefs, life, res)
    return {"application_id": c["application_id"], "blind_classification": c.get("blind_classification"),
            "regulation": res.as_dict(), "components": comps, "reliefs": [x.as_dict() for x in reliefs],
            "route_application_only": route1.as_dict() | {"summary_he": R.summary_he(route1)},
            "route_with_committee_split": route2.as_dict() if route2 else None,
            "lifecycle": life.as_dict(), "version_changes": changes, "comparison": comparison,
            "metrics": {"wall_ms": round(1000 * (time.perf_counter() - t0)), "llm_tokens": 0, "llm_cost": 0.0,
                        "note": "deterministic run — no model call needed for this case"}}


def compare(exp: dict, reliefs, life, res) -> list[dict]:
    out = []
    r = reliefs[0] if reliefs else None
    e = exp.get("relief", {})
    if r:
        out.append({"item": "permitted inner parking height", "committee": e.get("permitted"), "engine": r.permitted,
                    "match": r.permitted == e.get("permitted")})
        out.append({"item": "absolute deviation", "committee": e.get("deviation_abs"), "engine": r.deviation_abs,
                    "match": r.deviation_abs == e.get("deviation_abs")})
        out.append({"item": "percentage deviation", "committee": e.get("deviation_pct"), "engine": r.deviation_pct,
                    "match": r.deviation_pct == e.get("deviation_pct")})
        out.append({"item": "relief not a violation / not legally barred", "committee": "relief refused on merits",
                    "engine": r.outcome, "match": r.outcome not in e.get("outcome_not", [])})
        g = exp.get("governing_parking_inner_height", {})
        out.append({"item": "governing source", "committee": g.get("plan"), "engine": r.binding_regulation.get("plan"),
                    "match": r.binding_regulation.get("plan") == g.get("plan")})
    types = [d.type for d in life.decisions]
    out.append({"item": "relief refusal classified as RELIEF_REJECTED (not application rejection)",
                "committee": "RELIEF_REJECTED", "engine": types, "match": "RELIEF_REJECTED" in types
                and "APPLICATION_REJECTED" not in types})
    out.append({"item": "final status", "committee": exp.get("final_status"), "engine": life.final_status,
                "match": life.final_status == exp.get("final_status")})
    return out


# ------------------------------------------------------------------ Hebrew RTL report

HE_OUT = {"MISSING_PLANNING_JUSTIFICATION": "הקלה מבוקשת ללא נימוק תכנוני — בשיקול דעת הוועדה",
          "DISCRETIONARY_DECISION_REQUIRED": "הקלה מבוקשת — בשיקול דעת הוועדה",
          "LEGALLY_UNAVAILABLE_RELIEF": "הקלה שאינה ניתנת לאישור (סטייה ניכרת)", "CONFIRMED_VIOLATION": "חריגה מאומתת",
          "UNRESOLVED_APPLICABILITY": "תחולת ההוראה לא הוכרעה", "INSUFFICIENT_EVIDENCE": "אין ראיה לערך המבוקש",
          "WITHIN_LIMIT": "בתחום המותר"}
HE_DEC = {"RELIEF_REJECTED": "סירוב להקלה", "APPLICATION_REJECTED": "סירוב לבקשה", "APPLICATION_APPROVED": "אישור הבקשה / הפקת היתר",
          "APPLICATION_APPROVED_WITH_CONDITIONS": "אישור בתנאים", "RETURNED_FOR_CORRECTIONS": "הוחזר לתיקונים",
          "APPLICATION_WITHDRAWN": "משיכת הבקשה", "APPLICATION_CANCELLED": "ביטול", "APPLICATION_PENDING": "בטיפול"}


def html_report(r: dict) -> str:
    esc = html.escape
    ext = [x for x in r["reliefs"] if x["external"]]
    internal = [x for x in r["reliefs"] if not x["external"]]
    rows = lambda items, cols: "".join("<tr>" + "".join(f"<td>{esc(str(i.get(c, '')))}</td>" for c in cols) + "</tr>" for i in items)
    src = [s for s in r["regulation"]["sources"]]
    parts = [f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>בקשה {esc(r['application_id'])} — השוואה להחלטת הוועדה</title>
<style>body{{font-family:Arial,'Noto Sans Hebrew',sans-serif;direction:rtl;text-align:right;margin:24px;max-width:1000px}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}td,th{{border:1px solid #bbb;padding:4px 6px;vertical-align:top}}
th{{background:#eef}}h1,h2{{color:#234}}.ok{{color:#060}}.bad{{color:#a00}}.note{{color:#555;font-size:90%}}</style></head><body>
<h1>בקשה {esc(r['application_id'])} — השוואת תוצאת המנוע להחלטות הוועדה</h1>
<p class="note">מקרה בדיקה עם תוצאה ידועה — <b>אינו מבחן עיוור</b> ({esc(str(r['blind_classification']))}): בקובץ ה־DWF שבארכיון הישיבה נמצאו
הערות בודק, ומסמכי הוועדה נקראו במהלך הבדיקה.</p>
<h2>א. דוח חיצוני — ליקויים מבוססי ראיות בלבד</h2>"""]
    parts.append("<table><tr><th>רכיב</th><th>ממצא</th></tr>" + rows(ext, ["component", "explanation_he"]) + "</table>" if ext
                 else "<p>לא נמצאו ליקויים מבוססי ראיות. הקלה מבוקשת שלא אושרה אינה מדווחת כבנייה בלתי חוקית; "
                      "פריטים בשיקול דעת ופריטים פתוחים נמצאים ברשומה הפנימית.</p>")
    parts.append("<h2>ב. רשומה פנימית — הקלות</h2><table><tr><th>רכיב / תכונה</th><th>מותר</th><th>מבוקש</th><th>חריגה</th>"
                 "<th>%</th><th>מקור מחייב</th><th>זמינות משפטית</th><th>נימוק</th><th>סיווג</th></tr>")
    for x in internal:
        reg = x["binding_regulation"]
        parts.append(f"<tr><td>{esc(x['component'])}.{esc(x['attribute'])}</td><td>{x['permitted']}</td><td>{x['requested']}</td>"
                     f"<td>{x['deviation_abs']}</td><td>{x['deviation_pct']}</td><td>{esc(str(reg.get('plan')))} סעיף "
                     f"{esc(str(reg.get('clause')))} עמ' {esc(str(reg.get('page')))}</td><td>{esc(x['legally_available'])}</td>"
                     f"<td>{esc(x['justification'])}</td><td>{esc(HE_OUT.get(x['outcome'], x['outcome']))}</td></tr>")
    parts.append("</table>" + "".join(f"<p class='note'>{esc(x['explanation_he'])}</p>" for x in internal))
    rc = r["route_with_committee_split"] or r["route_application_only"]
    parts.append("<h2>ג. זכויות בנייה לפי קטגוריה וקומה</h2><table><tr><th>בדיקה</th><th>סטטוס</th><th>הסבר</th></tr>")
    for ch in r["route_application_only"]["checks"]:
        parts.append(f"<tr><td>{esc(ch['topic_he'])}</td><td>{esc(ch['status'])}</td><td>{esc(ch['explanation_he'])}</td></tr>")
    parts.append("</table><p class='note'>מעבר שני — עם חלוקת השטחים שבפרוטוקול הוועדה (נתוני ועדה, לא חישוב עצמאי):</p><table>")
    for ch in rc["checks"]:
        parts.append(f"<tr><td>{esc(ch['topic_he'])}</td><td>{esc(ch['status'])}</td><td>{esc(ch['explanation_he'])}</td></tr>")
    parts.append("</table><h2>ד. מקורות רגולטוריים שהוכרעו</h2><table><tr><th>מקור</th><th>סוג</th><th>תחולה</th><th>נימוק</th></tr>"
                 + rows(src, ["plan", "kind", "status", "reason"]) + "</table>")
    sup = r["regulation"]["superseded"]
    if sup:
        parts.append("<p class='note'>הוראות שהוחלפו: " + "; ".join(
            esc(f"{s['component']}.{s['attribute']} = {s['value']} לפי {s['plan']} — {s['note']}") for s in sup) + "</p>")
    parts.append("<h2>ה. השוואה להחלטות הוועדה</h2><table><tr><th>פריט</th><th>ועדה</th><th>מנוע</th><th>התאמה</th></tr>")
    for x in r["comparison"]:
        parts.append(f"<tr><td>{esc(x['item'])}</td><td>{esc(str(x['committee']))}</td><td>{esc(str(x['engine']))}</td>"
                     f"<td class='{'ok' if x['match'] else 'bad'}'>{'כן' if x['match'] else 'לא'}</td></tr>")
    parts.append("</table><h2>ו. מחזור חיי הבקשה</h2><table><tr><th>תאריך</th><th>החלטה</th><th>רכיב</th><th>הפניה</th></tr>")
    for d in r["lifecycle"]["decisions"]:
        parts.append(f"<tr><td>{esc(str(d['date']))}</td><td>{esc(HE_DEC.get(d['type'], d['type']))}</td>"
                     f"<td>{esc(str(d['rejected_component'] or ''))}</td><td>{esc(str(d['regulatory_reference'] or ''))}</td></tr>")
    parts.append(f"</table><p>סטטוס סופי: <b>{esc(r['lifecycle']['final_status'])}</b></p>"
                 "<h2>ז. השוואת גרסאות (מקורית מול מאושרת)</h2><table><tr><th>תכונה</th><th>לפני</th><th>אחרי</th><th>סטטוס</th><th>ראיה</th></tr>"
                 + rows(r["version_changes"], ["attribute", "before", "after", "status", "evidence"]) + "</table>")
    m = r["metrics"]
    parts.append(f"<p class='note'>זמן ריצה {m['wall_ms']} מ״ש; טוקנים {m['llm_tokens']}; עלות {m['llm_cost']}.</p></body></html>")
    return "\n".join(parts)


def main():
    case = Path(sys.argv[1])
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "exports" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    ph = texts = None
    store = os.environ.get("BBP_KNOWN_OUTCOME_HISTORY")       # optional: real register process history (eval store)
    if store and Path(store).exists():
        d = json.loads(Path(store).read_text(encoding="utf-8"))
        ph, texts = d["process_history"], d["decisions"]
    r = run(case, ph, texts)
    (out / f"{r['application_id']}_comparison.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / f"{r['application_id']}_comparison.html").write_text(html_report(r), encoding="utf-8")
    print(json.dumps({"comparison": r["comparison"], "reliefs": [x["outcome"] for x in r["reliefs"]],
                      "final_status": r["lifecycle"]["final_status"], "unresolved": r["regulation"]["unresolved"],
                      "out": str(out)}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
