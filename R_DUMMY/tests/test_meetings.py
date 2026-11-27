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
                       ("לחזור ולדון בנושא", "DEFERRED"),
                       ("החלטה לאשר הבקשה תואמת תכנית. בקרה מרחבית תקינה. בכפוף להשלמת יתר דרישות התכן", "APPROVED"),
                       ("החלטה לאשר\nהבקשה תואמת תכנית 278/03/35", "APPROVED"), ("להחזיר את הבקשה לעורך לתיקונים", "DEFERRED"), ("לאשר את הבקשה להקלות באופן חלקי", "APPROVED_PARTIAL"), ("החלטה לאשר חלקית את הבקשה: 1. הקלה לבריכה -לאשר 2. חדר מכונות - לסרב", "APPROVED_PARTIAL"),
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


ARCHIVE = """<table><tr><td>סדר יום לישיבה</td><td>סדר יום</td><td><a href="DocumentViewer?pageId=6720&amp;Name_File=11">x</a></td></tr>
<tr><td>קובץ החלטות</td><td>פרוטוקול החלטות</td><td><a href="DocumentViewer?pageId=6720&amp;Name_File=12">x</a></td></tr>
<tr><td>קובץ החלטות</td><td>קובץ החלטות מונגש</td><td><a href="DocumentViewer?pageId=6720&amp;Name_File=13">x</a></td></tr></table>"""
PROTOCOL = """<div>סעיף:11</div><div>תוכניות:</div><div>156/03/6</div><div>יעוד:</div><div>מגורים</div>
<div>בעלי עניין:</div><div>מבקש:</div><div>ישראל ישראלי</div><div>עורך:</div><div>פלוני אלמוני</div>
<div>מהות בקשה</div><div>הקמת בית מגורים</div><div>חוות דעת</div><div>הבקשה עומדת בזכויות הבניה</div>
<div>המלצות</div><div>לאשר.</div><div>החלטות</div><div>החלטה לסרב לבקשה - סטייה ניכרת</div><div>_____</div>"""


PDF_TEXT = """\u202bעמוד 6\u202c            \u202bקובץ החלטות רשות רישוי מקומית מס' 2022101 מתאריך01/12/2022:\u202c
        \u202bתיק ב\u202a\uf8ff\u202cיין:21000060\u202c        \u202bבקשה מקוו\u202a\uf8ff\u202cת ללא הקלות\u202c        \u202bסעיף 1\u202c
                                       \u202bבעלי ע\u202a\uf8ff\u202cיין\u202c
                                       \u202bמבקש\u202c
                     \u202bישראל ישראלי, רחוב 1, טלפון 050-0000000\u202c
                                       \u202bגושים חלקות\u202c
              \u202b633-0928358, 278/03/35\u202c           \u202bתוכ\u202a\uf8ff\u202cיות:\u202c
                                       \u202bמהות בקשה\u202c
                                \u202bמתקן כושר בחוף.\u202c
                                       \u202bהמלצות\u202c
                                       \u202bלאשר.\u202c
                                       \u202bהחלטות\u202c
                                \u202bהחלטה לסרב - סטייה ניכרת\u202c
"""


def test_pdf_protocol_letters_layout_and_no_names():
    sec = MT.parse_protocol_pdf(PDF_TEXT)["1"]
    assert sec["plans"] == "633-0928358, 278/03/35" and sec["essence"] == "מתקן כושר בחוף." and sec["recommendation"] == "לאשר."
    assert MT.classify(sec["decision"]) == "REJECTED" and "ישראלי" not in str(sec) and "050" not in str(sec)


def test_protocol_fills_missing_decision_without_names():
    seed(reset=True, samples=False)
    assert MT.pick_protocol(MT.archive_docs(ARCHIVE))["file"] == "13"
    sec = MT.parse_protocol(PROTOCOL)["11"]
    assert sec["plans"] == "156/03/6" and sec["recommendation"] == "לאשר." and "סטייה ניכרת" in sec["decision"]
    assert "ישראלי" not in str(sec) and "אלמוני" not in str(sec)

    def fetch(url, cfg, allowed, *a, **k):
        body, ct = (ARCHIVE, "text/html") if "MeetingsArchive" in url else ("\ufeff<!DOCTYPE html><html>" + PROTOCOL, "application/octet-stream")
        return F.Fetched("ok", url, 200, ct, body.encode(), final_url=url)
    with SessionLocal() as s:
        committees.import_register(s)
        c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "חוף אשקלון")).one()
        c.website_url, c.request_search_url = "https://v.example/", "https://v.example/SearchPermitApplication"
        m = CommitteeMeeting(committee_id=c.id, type_code="1", type_he="רשות רישוי מקומית", meeting_number="9", real_number="20269",
                             state="done")
        s.add(m)
        s.flush()
        s.add(CommitteeMeetingItem(meeting_id=m.id, item_number="11", state="done", outcome="OPEN"))
        s.commit()
        out = MT.run_protocols(s, c, fetch, sleep=lambda _: None)
        it = s.scalars(select(CommitteeMeetingItem)).one()
        assert out["items_filled"] == 1 and it.outcome == "REJECTED" and it.decision_source == "protocol"
        assert it.protocol["file"] == "13" and s.get(CommitteeMeeting, m.id).protocol_state == "done"
