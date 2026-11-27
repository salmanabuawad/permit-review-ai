"""A local committee's public meeting record: meetings, their items, and the decision on each item.

STUDY AND VALIDATION MATERIAL ONLY. Committee decisions are ground truth: they are never an input of the review engine,
never a rule, never a retrieval passage for a case. They are read to learn how the committee decides (what it approves,
rejects, defers, with which conditions) and, later, to measure the engine against outcomes.

Source: the committee's BarTech site. The meeting list comes from its search (behind a reCAPTCHA a person completes —
the list is then imported); each meeting's item list (MeetingItems) and each item's page (MeetingItemDetails) are public
pages the crawler reads, one request per delay. Applicant names on those pages are NOT stored; parcel, plan, request,
reliefs and decision are.
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import re
from html.parser import HTMLParser

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import CommitteeMeeting, CommitteeMeetingItem, PlanningCommittee

TYPES_HE = {"1": "רשות רישוי מקומית", "2": "מליאת הועדה", "3": "ועדת משנה", "4": "ועדת פיקוח"}
BATCH = 120                 # requests per crawler pass; other jobs run between passes

OUTCOMES_HE = {"APPROVED": "אושר", "APPROVED_CONDITIONS": "אושר בתנאים", "REJECTED": "נדחה", "DEFERRED": "נדחה הדיון / הוחזר",
               "RECOMMENDED": "הומלץ (תכנית)", "DEPOSIT": "הופקד / הוחלט להפקיד", "PLAN_APPROVED": "מתן תוקף לתכנית", "NOTED": "לידיעה", "OPEN": "טרם הוחלט",
               "OTHER": "אחר"}

# order matters: postponements and negations before plain approval / rejection words
_RULES = [
    ("DEFERRED", r"לדחות\s+את\s+(?:ה)?דיון|הדיון\s+נדחה|לשוב\s+ולדון|לחזור\s+ולדון|ירד\s+מסדר\s+היום|להוריד\s+מסדר\s+היום|לא\s+נדון|"
                 r"להחזיר\s+(?:את\s+הבקשה\s+)?ל|להשלמת|לשוב\s+לדיון|לדיון\s+נוסף|יידון\s+בישיבה|יובא\s+לדיון|מבוטל|בוטל"),
    ("REJECTED", r"לא\s+לאשר|לדחות\s+את\s+(?:ה)?בקש|לדחות\s+את\s+(?:ה)?תכנית|לדחות\s+את\s+(?:ה)?תוכנית|לדחות\s+את\s+(?:ה)?הקל|"
                 r"הבקשה\s+נדחית|נדחית|נדחתה|לסרב|^\s*לדחות\b"),
    ("PLAN_APPROVED", r"מתן\s+תוקף"),
    ("DEPOSIT", r"להפקיד|הפקדת\s+(?:ה)?(?:תכנית|תוכנית)|על\s+הפקדת|הפקדה\s+בתנאים|תופקד"),
    ("RECOMMENDED", r"להמליץ|ממליצ"),
    ("APPROVED_CONDITIONS", r"(?:לאשר|מאשר|אושר|אישור)[^.]{0,120}(?:בתנאים|בכפוף|בתנאי|ובלבד)"),
    ("APPROVED", r"לאשר|מאשרים|מאשרת|אושר|אושרה|ניתן\s+היתר|לתת\s+היתר|^\s*אישור\s+(?:תכנית|תוכנית|תשריט)|ס\.137|אישור\s+תשריט"),
    ("NOTED", r"לידיעה|הוועדה\s+רושמת|רשמה\s+לפניה"),
]


def classify(decision: str | None) -> str:
    t = re.sub(r"\s+", " ", decision or "").strip()
    t = re.sub(r"(?:לדחות|נדחו|נדחית|דוחה)\s+(?:את\s+)?ה?התנגדו\S*", " ", t)      # rejecting objections is not rejecting the request
    if not t:
        return "OPEN"
    for outcome, rx in _RULES:
        if re.search(rx, t):
            return outcome
    return "OTHER"


def _text(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", t))
    t = t.replace("‏", "").replace("‎", "")
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", x).strip() for x in t.splitlines() if x.strip())


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._href = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = {"cells": [], "hrefs": []}
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "a" and self._row is not None:
            self._row["hrefs"].append(dict(attrs).get("href") or "")
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row["cells"].append(_text("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_parcels(s: str | None) -> dict:
    s = s or ""
    g = re.search(r"גוש:\s*(\d+)", s)
    h = re.search(r"חלקה:\s*(\d+)", s)
    m = re.search(r"מגרש:\s*([\w/.-]+)", s)
    p = re.search(r"תוכנית:\s*([\w/.\-]+)", s)
    return {"gush": g and g.group(1), "helka": h and h.group(1), "migrash": m and m.group(1), "plan": p and p.group(1)}


def parse_items(page: str) -> list[dict]:
    """The item rows of a MeetingItems page (applicant name column dropped)."""
    p = _Rows()
    p.feed(page)
    out = []
    for r in p.rows:
        if not any("MeetingItemDetails" in h for h in r["hrefs"]) or len(r["cells"]) < 7:
            continue
        number = re.match(r"\s*(\d+)", r["cells"][0])
        if not number:
            continue
        num, typ, subject, desc, _name, address, parcels = r["cells"][:7]
        pp = parse_parcels(parcels)
        ref = re.search(r"(\d{6,9})\s*$", subject.replace("\\", " "))
        plan = re.search(r"תוכנית\s+([\w/.\-]+)", subject)
        out.append({"item_number": number.group(1), "item_type": typ[:80] or None, "subject": (subject + (" — " + desc if desc else ""))[:300],
                    "request_ref": ref and ref.group(1), "plan": (plan and plan.group(1)) or pp["plan"],
                    "locality": (address.split(",")[0].strip() or None) if address else None,
                    "gush": pp["gush"], "helka": pp["helka"], "migrash": pp["migrash"], "parcels": parcels or None})
    return out


def parse_header(page: str) -> dict:
    """Date and published number from a MeetingItems page header."""
    t = _text(page)
    d = re.search(r"מתאריך:\s*(\d\d/\d\d/\d{4})", t)
    n = re.search(r"מס['׳]:\s*(\d{4,9})", t)
    try:
        date = dt.datetime.strptime(d.group(1), "%d/%m/%Y").date() if d else None
    except ValueError:
        date = None
    return {"meeting_date": date, "real_number": n and n.group(1)}


def parse_detail(page: str) -> dict:
    """Essence, reliefs and decision from a MeetingItemDetails page (name and address fields are not kept)."""
    p = _Rows()
    p.feed(page)
    fields = {}
    for r in p.rows:
        if len(r["cells"]) >= 2:
            fields[r["cells"][0].rstrip(":").strip()] = r["cells"][1]
    essence = fields.get("מהות / מטרת דיון") or ""
    reliefs = None
    m = re.search(r"הקלות\s+מבוקשות\s*:?\s*(.*)$", essence, re.S)
    if m:
        reliefs, essence = m.group(1).strip() or None, essence[:m.start()].strip()
    decision = fields.get("החלטה") or None
    return {"essence": essence or None, "reliefs": reliefs, "decision": decision, "outcome": classify(decision),
            "parcels": fields.get("נתוני מקרקעין")}


# ---------------------------------------------------------------- import and crawler job

def import_meetings(s: Session, committee_id: str, rows: list) -> dict:
    """rows: [type_code, meeting_number, 'dd/mm/yyyy', protocol_ref, label] as read from the search results."""
    new = 0
    for r in rows:
        code, number, date, proto = str(r[0]), str(r[1]), r[2], (r[3] or None)
        if not code.isdigit() or not number.isdigit():
            continue
        m = s.scalars(select(CommitteeMeeting).where(CommitteeMeeting.committee_id == committee_id, CommitteeMeeting.type_code == code,
                                                     CommitteeMeeting.meeting_number == number)).first()
        if m is None:
            try:
                d = dt.datetime.strptime(date, "%d/%m/%Y").date() if date else None
            except ValueError:
                d = None
            real = re.search(r"(\d{5,9})", r[4] or "") if len(r) > 4 else None
            s.add(CommitteeMeeting(committee_id=committee_id, type_code=code, type_he=TYPES_HE.get(code), meeting_number=number,
                                   real_number=real and real.group(1), meeting_date=d, protocol_ref=proto, state="pending"))
            new += 1
    s.commit()
    return {"new": new, "total": s.scalar(select(func.count()).select_from(CommitteeMeeting).where(CommitteeMeeting.committee_id == committee_id))}


def _base(c: PlanningCommittee) -> str:
    from urllib.parse import urlsplit
    u = urlsplit(c.request_search_url or c.website_url or "")
    return f"https://{u.hostname}"


def run_batch(s: Session, c: PlanningCommittee, fetcher=None, sleep=None, limit: int = BATCH) -> dict:
    """Read pending meeting pages, then pending item pages, up to `limit` requests. Returns counts and what is left."""
    import time

    from .committee_docs import _allowed
    from .source_monitor import fetch as F
    from .source_monitor.service import load_config
    fetcher, sleep = fetcher or F.fetch, sleep or time.sleep
    cfg, allowed, base = load_config(), _allowed(c), _base(c)
    out = {"meetings": 0, "items": 0, "failed": 0}
    n = 0
    now = lambda: dt.datetime.now(dt.timezone.utc)  # noqa: E731
    for m in s.scalars(select(CommitteeMeeting).where(CommitteeMeeting.committee_id == c.id, CommitteeMeeting.state == "pending")
                       .order_by(CommitteeMeeting.meeting_number.desc()).limit(limit)):
        if n:
            sleep(cfg["delay_between_requests_s"])
        n += 1
        r = fetcher(f"{base}/MeetingItems?Committee_Type_Code={m.type_code}&Meeting_Number={m.meeting_number}", cfg, allowed)
        if r.status != "ok":
            m.state, m.error = "failed", (r.message or r.status)[:300]
            out["failed"] += 1
        else:
            page = F.decode_html(r.body)
            rows = parse_items(page)
            head = parse_header(page)
            m.meeting_date = m.meeting_date or head["meeting_date"]
            m.real_number = m.real_number or head["real_number"]
            for it in rows:
                if not s.scalars(select(CommitteeMeetingItem).where(CommitteeMeetingItem.meeting_id == m.id,
                                                                    CommitteeMeetingItem.item_number == it["item_number"])).first():
                    s.add(CommitteeMeetingItem(meeting_id=m.id, state="pending", **it))
            m.state, m.items, m.fetched_at, m.error = "items", len(rows), now(), None
            out["meetings"] += 1
        s.commit()
        if n >= limit:
            return {**out, "left": True}
    q = (select(CommitteeMeetingItem, CommitteeMeeting).join(CommitteeMeeting, CommitteeMeetingItem.meeting_id == CommitteeMeeting.id)
         .where(CommitteeMeeting.committee_id == c.id, CommitteeMeetingItem.state == "pending")
         .order_by(CommitteeMeeting.meeting_date.desc(), CommitteeMeetingItem.id).limit(limit - n))
    for it, m in s.execute(q).all():
        if n:
            sleep(cfg["delay_between_requests_s"])
        n += 1
        r = fetcher(f"{base}/MeetingItemDetails?Committee_Type_Code={m.type_code}&Meeting_Number={m.meeting_number}"
                    f"&Item_Number={it.item_number}", cfg, allowed)
        if r.status != "ok":
            it.state = "failed"
            out["failed"] += 1
        else:
            d = parse_detail(F.decode_html(r.body))
            it.essence, it.reliefs, it.decision, it.outcome = d["essence"], d["reliefs"], d["decision"], d["outcome"]
            it.state, it.fetched_at = "done", now()
            out["items"] += 1
        s.commit()
    left = s.scalar(select(func.count()).select_from(CommitteeMeetingItem).join(CommitteeMeeting)
                    .where(CommitteeMeeting.committee_id == c.id, CommitteeMeetingItem.state == "pending")) or 0
    left += s.scalar(select(func.count()).select_from(CommitteeMeeting)
                     .where(CommitteeMeeting.committee_id == c.id, CommitteeMeeting.state == "pending")) or 0
    for m in s.scalars(select(CommitteeMeeting).where(CommitteeMeeting.committee_id == c.id, CommitteeMeeting.state == "items")):
        if not s.scalar(select(func.count()).select_from(CommitteeMeetingItem).where(CommitteeMeetingItem.meeting_id == m.id,
                                                                                     CommitteeMeetingItem.state == "pending")):
            m.state = "done"
    s.commit()
    return {**out, "left": bool(left), "pending": left}


def run_job(session_factory, cid: str, fetcher=None, sleep=None) -> None:
    """One pass of the 'meetings' job; it stays queued while work is left, so other crawler jobs interleave."""
    with session_factory() as s:
        c = s.get(PlanningCommittee, cid)
        try:
            out = run_batch(s, c, fetcher, sleep)
            if not out["left"]:
                out["reclassified"] = reclassify(s, cid)
            c = s.get(PlanningCommittee, cid)
            prev = (c.kb_detail or {}).get("meetings") or {}
            c.kb_detail = {**(c.kb_detail or {}), "meetings": {**prev, "state": "queued" if out["left"] else "done",
                                                                "at": dt.datetime.now(dt.timezone.utc).isoformat(), "last_pass": out,
                                                                **counts(s, cid)}}
            s.commit()
        except Exception as e:  # noqa: BLE001 — recorded; the worker goes on
            s.rollback()
            c = s.get(PlanningCommittee, cid)
            c.kb_detail = {**(c.kb_detail or {}), "meetings": {"state": "failed", "error": f"{type(e).__name__}: {e}"[:300]}}
            s.commit()


def reclassify(s: Session, cid: str) -> int:
    """Re-apply the classifier to stored decision text (after the rules improve). Returns rows changed."""
    n = 0
    for it in s.scalars(select(CommitteeMeetingItem).join(CommitteeMeeting)
                        .where(CommitteeMeeting.committee_id == cid, CommitteeMeetingItem.state == "done")):
        o = classify(it.decision)
        if o != it.outcome:
            it.outcome, n = o, n + 1
    s.commit()
    return n


def counts(s: Session, cid: str) -> dict:
    meetings = dict(s.execute(select(CommitteeMeeting.state, func.count()).where(CommitteeMeeting.committee_id == cid)
                              .group_by(CommitteeMeeting.state)).all())
    outcomes = dict(s.execute(select(CommitteeMeetingItem.outcome, func.count()).join(CommitteeMeeting)
                              .where(CommitteeMeeting.committee_id == cid, CommitteeMeetingItem.state == "done")
                              .group_by(CommitteeMeetingItem.outcome)).all())
    return {"meetings_by_state": meetings, "outcomes": {k or "—": v for k, v in outcomes.items()}}
