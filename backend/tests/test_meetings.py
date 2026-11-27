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
                       ("להפקיד את התכנית בתנאים", "DEPOSIT"), ("", "OPEN"), ("לשוב ולדון לאחר סיור", "DEFERRED")]:
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
