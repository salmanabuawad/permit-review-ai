"""Permit360 Pro projects: two ways to start, one preparation workflow.

Path A — the engineer picks the committee from the national directory, then the parcel; the parcel's registered boundary
         is checked against the committee's planning area(s).
Path B — the engineer enters block / parcel; the committee is found by the spatial intersection of the registered parcel
         with the official planning areas, shown for confirmation.
Either way the committee is never inferred from a municipality name or a plan number. When the boundaries cannot answer
(parcel not in the cadastre, no linked area) the engineer may choose the committee manually; the project then carries
jurisdiction status MANUAL_UNRESOLVED and every view says so. Several intersecting areas → the engineer must choose
among the candidates (status CANDIDATE_SELECTED, still marked unverified).

A project is a case of kind "design" (private to its owner, as Architect360 designs), with `committee_id`, the
jurisdiction evidence and the workflow state. Creating it starts knowledge initialization: XPLAN discovery for the
parcel, and — for a committee whose knowledge base is empty or stale — a site probe / document fetch by the crawler.
"""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import jurisdiction as J
from .models import CheckRun, CommitteeDocument, PermitCase, PlanningCommittee

STAGES = [("property", "זיהוי הנכס"), ("jurisdiction", "אימות התחום והוועדה"), ("knowledge", "ידע רגולטורי"),
          ("rights", "זכויות בנייה ומגבלות"), ("purpose", "מטרת הבקשה"), ("assistance", "סיוע תכנוני"),
          ("preparation", "הכנת הבקשה"), ("validation", "בדיקה רציפה"), ("readiness", "מוכנות להגשה")]
KB_STALE_DAYS = 180
REQUEUE_DAYS = 7
OK_STATUSES = ("VERIFIED", "RESOLVED")


class ProjectError(ValueError):
    def __init__(self, msg: str, detail: dict | None = None, code: int = 422):
        super().__init__(msg)
        self.detail, self.code = detail or {}, code


def directory(s: Session, q: str = "", limit: int = 40) -> list[dict]:
    """Searchable national committee directory (name, district, kind, planning-area codes, settlements)."""
    from .models import CommitteeSettlement
    qn = J.norm(q)
    rows = []
    for c in s.scalars(select(PlanningCommittee).order_by(PlanningCommittee.name_he)):
        sett = [x.name_he for x in s.scalars(select(CommitteeSettlement).where(CommitteeSettlement.committee_id == c.id))]
        hay = [J.norm(c.name_he), *(J.norm(x) for x in sett), *(c.planning_area_codes or [])]
        if qn and not any(qn in h for h in hay):
            continue
        rows.append({"id": c.id, "name_he": c.name_he, "district": c.district, "kind": c.kind, "codes": c.planning_area_codes or [],
                     "settlements": sett[:12], "settlements_total": len(sett), "kb_status": c.kb_status})
        if len(rows) >= limit:
            break
    return rows


def _check_ids(gush, helka, lot=None):
    g, h = str(gush or "").strip(), str(helka or "").strip()
    if not re.fullmatch(r"\d{1,6}", g) or not re.fullmatch(r"\d{1,5}", h) or int(g) == 0 or int(h) == 0:
        raise ProjectError("מספר גוש / חלקה לא תקין (ספרות בלבד)")
    if lot is not None and str(lot).strip() and not re.fullmatch(r"[\w/.\-]{1,20}", str(lot).strip()):
        raise ProjectError("מספר מגרש לא תקין")
    return g, h, (str(lot).strip() or None) if lot is not None else None


def decide(s: Session, path: str, gush, helka, committee_id: str | None, manual: bool = False) -> dict:
    """The jurisdiction record a project would get — or a ProjectError saying what the engineer must resolve."""
    g, h, _ = _check_ids(gush, helka)
    if path == "A":
        if not committee_id:
            raise ProjectError("במסלול א יש לבחור ועדה")
        r = J.verify(s, committee_id, g, h)
        if r["status"] == "VERIFIED":
            return {**r, "decision": "VERIFIED"}
        if r["status"] == "MISMATCH":
            raise ProjectError("החלקה אינה במרחב התכנון של הוועדה שנבחרה", r, 409)
        if r["status"] == "AMBIGUOUS":
            return {**r, "decision": "CANDIDATE_SELECTED", "status_he": "החלקה חוצה כמה מרחבי תכנון; הוועדה שנבחרה היא אחת מהן — לא אומת"}
        if not manual:
            raise ProjectError("לא ניתן לאמת את התחום מנתונים רשמיים — ניתן לבחור ידנית (יסומן כלא מאומת)", r, 409)
        return {**r, "decision": "MANUAL_UNRESOLVED", "status_he": J.STATUS_HE["MANUAL_UNRESOLVED"], "committee_id": committee_id}
    if path != "B":
        raise ProjectError("מסלול לא מוכר")
    r = J.discover(s, g, h)
    if r["status"] == "RESOLVED":
        if committee_id and committee_id != r["committee_id"]:
            raise ProjectError("הוועדה שנבחרה שונה מהוועדה שזוהתה לפי הגבולות", r, 409)
        return {**r, "decision": "RESOLVED"}
    if r["status"] == "AMBIGUOUS":
        ids = {x["committee_id"] for x in r["candidates"] if x["committee_id"]}
        if committee_id in ids:
            return {**r, "decision": "CANDIDATE_SELECTED", "committee_id": committee_id,
                    "status_he": "נבחרה ועדה מבין מרחבי התכנון החותכים את החלקה — לא אומת"}
        raise ProjectError("החלקה חוצה כמה מרחבי תכנון — יש לבחור ועדה מבין המועמדות", r, 409)
    if manual and committee_id and s.get(PlanningCommittee, committee_id):
        return {**r, "decision": "MANUAL_UNRESOLVED", "status_he": J.STATUS_HE["MANUAL_UNRESOLVED"], "committee_id": committee_id}
    raise ProjectError(r.get("status_he") or "לא ניתן לזהות את הוועדה", r, 409)


def create(s: Session, tenant: str, user: str, path: str, gush, helka, lot=None, committee_id: str | None = None,
           title: str = "", permit_type: str = "new_building", manual: bool = False) -> PermitCase:
    g, h, lot = _check_ids(gush, helka, lot)
    d = decide(s, path, g, h, committee_id, manual)
    c = s.get(PlanningCommittee, d["committee_id"])
    n = s.scalar(select(func.count()).select_from(PermitCase).where(PermitCase.tenant_id == tenant, PermitCase.kind == "design")) or 0
    loc = (d.get("localities") or [{}])[0].get("name_he") if d.get("localities") else None
    case = PermitCase(tenant_id=tenant, case_number=f"DES-{n + 1:04d}", title=(title or "").strip() or f"גוש {g} חלקה {h} — {c.name_he}",
                      permit_type=permit_type, track="regular_permit", gush=g, helka=h, applicable_plans=[],
                      declared={"lot": lot} if lot else {}, kind="design", owner_id=user, is_demo=False, status="INTAKE",
                      committee_id=c.id, address=loc,
                      jurisdiction={"path": path, "status": d["decision"], "status_he": d["status_he"], "committee_id": c.id,
                                    "committee_name": c.name_he, "candidates": d.get("candidates", []),
                                    "municipalities": d.get("municipalities", []), "localities": d.get("localities", []),
                                    "parcel": d.get("parcel"), "datasets": d.get("datasets"), "decided_by": user,
                                    "decided_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                      workflow={"started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "knowledge": {}})
    s.add(case)
    s.flush()
    case.workflow = {**case.workflow, "knowledge": init_knowledge(s, case)}
    return case


def init_knowledge(s: Session, case: PermitCase) -> dict:
    """Queue what the project needs: XPLAN discovery for the parcel, and the committee's knowledge base when it is
    empty or stale (probe when it has no known sources, fetch otherwise; not again within REQUEUE_DAYS)."""
    from . import committees as CM
    from . import plan_discovery as PD
    out = {"queued": [], "reused": []}
    PD.queue(s, case, case.owner_id or "system")
    out["queued"].append("xplan_discovery")
    c = s.get(PlanningCommittee, case.committee_id)
    docs = s.scalar(select(func.count()).select_from(CommitteeDocument).where(CommitteeDocument.committee_id == c.id,
                                                                              CommitteeDocument.status.in_(("ok", "unchanged")))) or 0
    last = ((c.kb_detail or {}).get("fetch") or {}).get("at") or ((c.kb_detail or {}).get("deep") or {}).get("at")
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)).days if last else None
    recent = lambda job: (((c.kb_detail or {}).get(job) or {}).get("queued_at") or "") > (  # noqa: E731
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=REQUEUE_DAYS)).isoformat()
    if docs and age is not None and age <= KB_STALE_DAYS:
        out["reused"].append({"committee_documents": docs, "fetched_days_ago": age})
    elif not c.sources and not recent("probe"):
        CM.queue_jobs(s, "probe", [c.id], )
        out["queued"].append("committee_probe")
    elif c.sources and not recent("fetch"):
        CM.queue_jobs(s, "fetch", [c.id])
        out["queued"].append("committee_fetch")
    out["kb_documents"], out["kb_age_days"] = docs, age
    return out


# ---------------------------------------------------------------- the applicable regulatory package

def package(s: Session, case: PermitCase) -> dict:
    from . import plan_discovery as PD
    from .rules.route import load_rights
    jur = dict(case.jurisdiction or {})
    c = s.get(PlanningCommittee, case.committee_id) if case.committee_id else None
    missing, outdated, restrictions = [], [], []
    # jurisdiction re-check against the current datasets (a boundary change since the project started is reported)
    now = J.discover(s, case.gush, case.helka) if case.gush and case.helka else {"status": "UNRESOLVED"}
    if now.get("status") == "RESOLVED" and now.get("committee_id") != case.committee_id:
        restrictions.append({"kind": "jurisdiction_changed", "text_he": f"לפי נתוני הגבולות העדכניים החלקה במרחב של "
                             f"{(now['candidates'] or [{}])[0].get('committee_name')} — שונה מהוועדה בפרויקט"})
    if jur.get("status") not in OK_STATUSES:
        missing.append({"item": "jurisdiction", "text_he": jur.get("status_he") or "התחום לא אומת"})
    # committee knowledge base
    kb = {}
    if c:
        docs = dict(s.execute(select(CommitteeDocument.kind, func.count()).where(CommitteeDocument.committee_id == c.id,
                              CommitteeDocument.status.in_(("ok", "unchanged"))).group_by(CommitteeDocument.kind)).all())
        last = ((c.kb_detail or {}).get("fetch") or {}).get("at") or ((c.kb_detail or {}).get("deep") or {}).get("at")
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)).days if last else None
        kb = {"committee": c.name_he, "district": c.district, "codes": c.planning_area_codes or [], "documents_by_kind": docs,
              "documents": sum(docs.values()), "last_fetch": last, "age_days": age, "status": c.kb_status}
        if not docs:
            missing.append({"item": "committee_kb", "text_he": "אין עדיין מסמכים מאתר הוועדה (נשלח לסורק)"})
        elif age is not None and age > KB_STALE_DAYS:
            outdated.append({"item": "committee_kb", "text_he": f"מסמכי הוועדה נשלפו לפני {age} ימים"})
        if not docs.get("guideline"):
            missing.append({"item": "guidelines", "text_he": "לא נמצאו הנחיות מרחביות של הוועדה — ניתן להעלות"})
    # statutory plans (XPLAN, on the registered parcel)
    disc = PD.view(s, case)
    plans = disc.get("plans") or []
    if disc.get("status") in ("QUEUED", "RUNNING"):
        missing.append({"item": "plans", "text_he": "איתור התכניות ב־XPLAN בעבודה"})
    elif not plans:
        missing.append({"item": "plans", "text_he": disc.get("status_he") or "טרם אותרו תכניות"})
    for p in plans:
        st = (p.get("status") or "") + " " + (p.get("stage") or "")
        if "77" in (p.get("plan") or "") or "77" in (p.get("subtype") or ""):
            restrictions.append({"kind": "notice_77_78", "plan": p["plan"], "text_he": f"{p.get('name') or p['plan']} — הודעה לפי סעיפים 77–78: ייתכנו תנאים להיתר"})
        elif "הפקדה" in st:
            restrictions.append({"kind": "deposited_plan", "plan": p["plan"], "text_he": f"תכנית מופקדת {p['plan']} — היתר בכפוף לסעיפים 97–98"})
        if p.get("relation") == "PARTIAL":
            restrictions.append({"kind": "partial_plan", "plan": p["plan"], "text_he": f"תכנית {p['plan']} חלה על חלק מהחלקה — יש לבדוק את מיקום הבנייה"})
    land_use = sorted({u.get("designation") for u in disc.get("land_use") or [] if u.get("designation") and "אחרת" not in u["designation"]})
    if len(land_use) > 1:
        restrictions.append({"kind": "mixed_land_use", "text_he": "בחלקה כמה ייעודי קרקע: " + ", ".join(land_use)})
    # building rights (verified rights files of the covering plans)
    lot = (case.declared or {}).get("lot")
    rights, note = load_rights([p["plan"] for p in plans if p.get("relation") == "COVERS"] or [p["plan"] for p in plans],
                               land_use[0] if land_use else None, dt.date.today(), lot=lot)
    if rights is None:
        missing.append({"item": "rights", "text_he": f"זכויות בנייה: {note}; יש לקרוא את הוראות התכנית (קישור מבא\"ת)"})
    requirements = _requirements(s, case, plans, land_use, restrictions)
    return {"case_id": case.id, "property": {"gush": case.gush, "helka": case.helka, "lot": lot, "parcel": jur.get("parcel"),
                                             "municipalities": jur.get("municipalities"), "localities": jur.get("localities")},
            "jurisdiction": {**jur, "current": {k: now.get(k) for k in ("status", "status_he", "committee_id", "datasets")}},
            "committee_kb": kb, "plans": plans, "land_use": land_use, "xplan": {k: disc.get(k) for k in ("status", "status_he", "checked_at", "geometry_source")},
            "rights": rights, "rights_note": note, "restrictions": restrictions, "requirements": requirements,
            "missing": missing, "outdated": outdated,
            "disclaimer_he": "חבילת מידע תכנוני לסיוע בהכנת הבקשה — אינה קביעת תחולה משפטית ואינה מחליפה את בדיקת הוועדה."}


def _requirements(s: Session, case: PermitCase, plans: list, land_use: list, restrictions: list) -> list[dict]:
    """What the application will need, from the package (deterministic) and — as statistics only — the committee's
    recurring approval conditions."""
    req = [{"id": "plans_instructions", "text_he": "הוראות ותשריט התכניות החלות", "why_he": ", ".join(p["plan"] for p in plans[:6]) or "—",
            "links": [p["url"] for p in plans if p.get("url")][:6]},
           {"id": "survey", "text_he": "מפת מדידה עדכנית חתומה", "why_he": "בסיס לכל בקשה להיתר"},
           {"id": "rights_table", "text_he": "טבלת שטחים וזכויות מול התכנית", "why_he": "שטח עיקרי, שירות ותכסית מותרת"}]
    if any(r["kind"] == "notice_77_78" for r in restrictions):
        req.append({"id": "s78", "text_he": "בדיקת תנאי סעיף 78 של ההודעה", "why_he": "הודעה לפי סעיפים 77–78 חלה על החלקה"})
    if any(r["kind"] == "deposited_plan" for r in restrictions):
        req.append({"id": "s97", "text_he": "בחינת התאמה לתכנית המופקדת", "why_he": "תכנית מופקדת חלה על החלקה"})
    if any("חקלא" in u for u in land_use):
        req.append({"id": "agri", "text_he": "אישור משרד החקלאות / ות\"ל לפי הצורך", "why_he": "ייעוד חקלאי בחלקה"})
    req += [{"id": "home_front", "text_he": "אישור פיקוד העורף / פתרון מיגון", "why_he": "תנאי להיתר (חוק ההתגוננות האזרחית)"},
            {"id": "fire", "text_he": "התאמה לדרישות כבאות", "why_he": "לפי סוג המבנה ושימושו"}]
    return req


# ---------------------------------------------------------------- workflow and assistant

def workflow(s: Session, case: PermitCase, pkg: dict | None = None) -> dict:
    from .api.architect import readiness
    pkg = pkg or package(s, case)
    jur = case.jurisdiction or {}
    runs = s.scalar(select(func.count()).select_from(CheckRun).where(CheckRun.case_id == case.id)) or 0
    files = len(case.files or [])
    purpose = (case.declared or {}).get("purpose")
    st = {"property": "done" if (pkg["property"].get("parcel") or {}).get("area_m2") else "open",
          "jurisdiction": "done" if jur.get("status") in OK_STATUSES else "warning",
          "knowledge": "pending" if any(m["item"] in ("plans", "committee_kb") and ("בעבודה" in m["text_he"] or "נשלח" in m["text_he"])
                                        for m in pkg["missing"]) else ("done" if pkg["plans"] and pkg["committee_kb"].get("documents") else "warning"),
          "rights": "done" if pkg["rights"] else "warning",
          "purpose": "done" if purpose and case.permit_type else "open",
          "assistance": "available",
          "preparation": "done" if files else "open",
          "validation": "done" if runs else "open",
          "readiness": "open"}
    ready = readiness(s, case) if runs else None
    if ready:
        st["readiness"] = "done" if not ready.get("blockers") else "warning"
    stages = [{"key": k, "label_he": lab, "status": st[k]} for k, lab in STAGES]
    nxt = next((x for x in stages if x["status"] in ("open", "warning", "pending")), None)
    return {"stages": stages, "current": nxt and nxt["key"], "readiness": ready, "next_actions": next_actions(case, pkg, st)}


def next_actions(case: PermitCase, pkg: dict, st: dict) -> list[str]:
    """What the assistant proposes now — deterministic, from the project state (no question is asked twice)."""
    out = []
    jur = case.jurisdiction or {}
    if st["jurisdiction"] != "done":
        out.append(f"התחום לא אומת ({jur.get('status_he')}). מומלץ לאמת מול הוועדה לפני השקעה בתכנון.")
    for m in pkg["missing"]:
        if m["item"] in ("plans", "committee_kb") and st["knowledge"] == "pending":
            out.append(m["text_he"] + " — החבילה תתעדכן אוטומטית.")
    for r in pkg["restrictions"]:
        out.append("שים לב: " + r["text_he"])
    if st["rights"] != "done":
        out.append(pkg["rights_note"] + " — העלה את טבלת הזכויות או את הוראות התכנית, והמערכת תחשב את הזכויות למגרש.")
    if st["purpose"] != "done":
        out.append("הגדר את מטרת הבקשה (סוג הבנייה והשימוש) כדי שהבדיקות יותאמו לה.")
    elif st["preparation"] != "done":
        out.append("העלה את מסמכי הבקשה (תשריט, תכניות קומות, חתכים, טבלת שטחים) להפעלת הבדיקות.")
    elif st["validation"] != "done":
        out.append("הרץ בדיקה על הטיוטה כדי לראות חסמים לפני הגשה.")
    return out[:8]


def ask(s: Session, case: PermitCase, question: str, gateway=None) -> dict:
    """A question to the engineering assistant: answered by the local model from the project package and the
    committee's own texts only; numbers not in that material are rejected (the answer falls back to the sources)."""
    from . import committee_docs as CD
    from .services import gateway_for
    q = re.sub(r"\s+", " ", question or "").strip()[:500]
    if len(q) < 3:
        raise ProjectError("שאלה קצרה מדי")
    pkg = package(s, case)
    hits = []
    if case.committee_id:
        try:
            hits = [h for h in CD.hybrid_search(s, q, case.committee_id, mode="hybrid", k=8)][:5]
        except Exception:  # noqa: BLE001 — no model / no vectors
            hits = []
    passages = [{"id": f"cmt:{h['passage_id']}", "source_title_he": f"{h['committee']} — {h['document']}", "page": h["page"],
                 "text_he": h["excerpt"][:900], "url": h["url"]} for h in hits]
    facts = {"property": pkg["property"], "jurisdiction": {k: pkg["jurisdiction"].get(k) for k in ("status_he", "committee_name")},
             "plans": [{k: p.get(k) for k in ("plan", "name", "status", "relation", "published")} for p in pkg["plans"][:12]],
             "land_use": pkg["land_use"], "restrictions": [r["text_he"] for r in pkg["restrictions"]],
             "rights_note": pkg["rights_note"], "missing": [m["text_he"] for m in pkg["missing"]]}
    gw = gateway or gateway_for(s, case.tenant_id)
    res = gw.route("Assistant", "PROJECT", {"question": q, "facts": facts, "passages": passages})
    answer = (res.output or {}).get("text") if res.outcome in ("OK", "FALLBACK") else None
    return {"question": q, "answer": answer, "outcome": res.outcome, "provider": res.provider_id, "sources": passages,
            "note_he": "תשובת עוזר AI מקומי מתוך חבילת הפרויקט ומסמכי הוועדה בלבד — לא קביעה מקצועית." if answer else
            "העוזר אינו זמין כעת; אלה הקטעים הרלוונטיים ממסמכי הוועדה."}
