"""Committee meeting record: parsing, decision classification, crawler job — study material, never engine input."""
from sqlalchemy import select

from app import committees, meetings as MT
from app.db import SessionLocal
from app.models import CommitteeMeeting, CommitteeMeetingItem, PlanningCommittee
from app.seed import seed
from app.source_monitor import fetch as F

ITEMS = """<main><ul><li>סוג ישיבה: ועדת משנה</li><li>מס': <strong>202690</strong></li><li>מתאריך: <strong>04/11/2026</strong></li></ul>
<table><tr><th>מספר סעיף</th></tr>
<tr><td><span>11</span> <a href="MeetingItemDetails?Committee_Type_Code=3&amp;Meeting_Number=202521&amp;Item_Number=11">פרטי סעיף</a></td>
<td><span>אישור בקשה</span></td><td><span>בקשה מקוונת כולל הקלות ‏1‏\\‏20260040‏</span></td><td><span>מגורים, בנייה חדשה</span></td>
<td><span>ישראל ישראלי</span></td><td><span>הודיה, מס&#39; משק 113, הודיה, 85</span></td>
<td><span>גוש: 2683, חלקה: 66, מגרש: 85, תוכנית: 156/03/6</span></td></tr></table></main>"""
DETAIL = """<table class="footable"><tr><td> מבקש / יזם: </td><td>ישראל ישראלי</td></tr>
<tr><td> נתוני מקרקעין: </td><td>גוש: 2683, חלקה: 66</td></tr>
<tr><td> מהות / מטרת דיון: </td><td>הקמת מבנה מגורים<br /> הקלות מבוקשות :<br /> הקלה בקו בניין צידי 10%</td></tr>
<tr><td> החלטה: </td><td>לאשר את הבקשה בתנאים הבאים: תיקון תכנית</td></tr></table>"""


def test_parse_and_classify():
    rows = MT.parse_items(ITEMS)
    assert rows == [{"item_number": "11", "item_type": "אישור בקשה", "subject": rows[0]["subject"], "request_ref": "20260040",
                     "plan": "156/03/6", "locality": "הודיה", "gush": "2683", "helka": "66", "migrash": "85",
                     "parcels": "גוש: 2683, חלקה: 66, מגרש: 85, תוכנית: 156/03/6"}]
    assert "ישראלי" not in str(rows)                                    # applicant names are not kept
    assert MT.parse_header(ITEMS)["real_number"] == "202690" and str(MT.parse_header(ITEMS)["meeting_date"]) == "2026-11-04"
    d = MT.parse_detail(DETAIL)
    assert d["essence"] == "הקמת מבנה מגורים" and "קו בניין" in d["reliefs"] and d["outcome"] == "APPROVED_CONDITIONS"
    assert "ישראלי" not in str(d)
    for text, want in [("לאשר את הבקשה", "APPROVED"), ("לא לאשר את הבקשה", "REJECTED"), ("לדחות את הבקשה", "REJECTED"),
                       ("לדחות את הדיון לישיבה הבאה", "DEFERRED"), ("לדחות את ההתנגדויות ולאשר את הבקשה", "APPROVED"),
                       ("להפקיד את התכנית בתנאים", "DEPOSIT"), ("", "OPEN"), ("לשוב ולדון לאחר סיור", "DEFERRED"),
                       ("ס.85(ב)(1) - החלטת ועדה מקומית על הפקדת תכנית בכפוף לכתב שיפוי", "DEPOSIT"),
                       ("ס.108 - החלטת ועדה מקומית על מתן תוקף לתכנית", "PLAN_APPROVED"),
                       ("אישור תכנית בינוי בכפוף לתיקון תוואי כביש", "APPROVED_CONDITIONS"),
                       ("לחזור ולדון בנושא", "DEFERRED"), ("החלטה לאשר חלקית את הבקשה: 1. הקלה לבריכה -לאשר 2. חדר מכונות - לסרב", "APPROVED_PARTIAL"),
                       ("אישור תצ\"ר התצ\"ר תואם תכנית", "APPROVED"), ("הבקשה הורדה מסדר היום לבקשת המבקש", "DEFERRED"), ("החלטת הועדה- ס.137 - אישור תשריט חלוקת בית משותף", "APPROVED")]:
        assert MT.classify(text) == want, text


def test_job_reads_meetings_then_items():
    seed(reset=True, samples=False)
    calls = []

    def fetch(url, cfg, allowed, *a, **k):
        calls.append(url)
        body = ITEMS if "/MeetingItems?" in url else DETAIL
        return F.Fetched("ok", url, 200, "text/html", body.encode(), final_url=url)
    with SessionLocal() as s:
        committees.import_register(s)
        c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "חוף אשקלון")).one()
        c.website_url, c.request_search_url = "https://v.example/", "https://v.example/SearchPermitApplication"
        s.commit()
        assert MT.import_meetings(s, c.id, [["3", "202521", "", "", ""], ["x", "1", "", "", ""]])["new"] == 1
        out = MT.run_batch(s, c, fetch, sleep=lambda _: None)
        assert out["meetings"] == 1 and out["items"] == 1 and not out["left"]
        m = s.scalars(select(CommitteeMeeting)).one()
        it = s.scalars(select(CommitteeMeetingItem)).one()
        assert m.state == "done" and str(m.meeting_date) == "2026-11-04" and it.outcome == "APPROVED_CONDITIONS"
        assert all(u.startswith("https://v.example/Meeting") for u in calls)


def test_study_aggregates_without_personal_data():
    import datetime as dt
    import sys
    from pathlib import Path
    seed(reset=True, samples=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import study_meetings as SM
    with SessionLocal() as s:
        committees.import_register(s)
        c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "חוף אשקלון")).one()
        m = CommitteeMeeting(committee_id=c.id, type_code="1", type_he="רשות רישוי מקומית", meeting_number="1", state="done",
                             meeting_date=dt.date(2020, 5, 1))
        s.add(m)
        s.flush()
        for n, (rel, dec) in enumerate([("הקלה בקו בניין צידי", "לאשר בתנאים: אישור פיקוד העורף"), (None, "לאשר את הבקשה"),
                                         ("תוספת קומה", "לדחות את הבקשה — בניגוד לתכנית")], 1):
            s.add(CommitteeMeetingItem(meeting_id=m.id, item_number=str(n), item_type="אישור בקשה", locality="זיקים", gush="2832",
                                       reliefs=rel, decision=dec, outcome=MT.classify(dec), state="done", request_ref="2020000" + str(n)))
        s.commit()
        r = SM.study(c.id, dt.date(2016, 1, 1))
    assert r["requests_decided"] == 3 and r["approval_rate_with_reliefs"] == {"n": 2, "approved": 1}
    assert r["reliefs"]["קו בניין"] == {"n": 1, "approved": 1} and r["rejection_reasons"]["בניגוד לתכנית / אינו תואם"] == 1
    assert r["approval_conditions"]["פיקוד העורף / ממ\"ד"] == 1 and r["zikim_block_2832_plan_0723718"]["items"] == 3
    md = SM.markdown(r)
    assert "20200001" not in md and "אושרו 50%" in md
