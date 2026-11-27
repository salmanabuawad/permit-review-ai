"""Deep search of one committee: whole own site breadth-first, linked documents, XPLAN plan catalogue, and the
committee's fetched text reaching a review's summary passages as unverified context."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from app import committee_docs, committees, plan_discovery as PD, services
from app.db import SessionLocal
from app.models import CommitteeDocument, CommitteePassage, PlanningCommittee
from app.seed import seed
from app.source_monitor import fetch as F

LONG = "<p>" + "הנחיות הוועדה לבנייה בתחום המועצה " * 20 + "</p>"


def site():
    pages = {
        "https://v.example/": "<title>בית</title>" + LONG + "<a href='/a'>רישוי</a><a href='/search?q=1'>חיפוש</a><a href='/x.jpg'>תמונה</a>"
                              "<a href='https://other.example/z'>אחר</a><a href='/privacy'>פרטיות</a>",
        "https://v.example/a": "<title>רישוי ובנייה</title>" + LONG + "<a href='/a/b'>טפסים</a><a href='/f/form.pdf'>טופס בקשה</a>",
        "https://v.example/a/b": "<title>טפסים</title>" + LONG + "<a href='/a/b/c'>עוד</a><a href='/f/guide.pdf'>הנחיות מרחביות</a>",
        "https://v.example/a/b/c": "<title>עמוד עמוק</title>" + LONG + "<a href='/a/b/c/d'>עמוק מדי</a>",
        "https://v.example/a/b/c/d": "<title>עמוק מדי</title>" + LONG,
    }
    files = {u: ("text/html", h.encode()) for u, h in pages.items()}
    files["https://v.example/f/form.pdf"] = ("application/pdf", b"%PDF-form")
    files["https://v.example/f/guide.pdf"] = ("application/pdf", b"%PDF-guide")
    calls = []

    def fetch(url, cfg, allowed, etag=None, lm=None, form=None):
        calls.append(url)
        if F.host(url) not in allowed:
            return F.Fetched("error", url, message="outside")
        if url not in files:
            return F.Fetched("error", url, 404)
        ct, body = files[url]
        return F.Fetched("ok", url, 200, ct, body, final_url=url)
    return fetch, calls


def _committee(s):
    committees.import_register(s)
    c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "חוף אשקלון")).one()
    c.website_url, c.sources = "https://v.example/", []
    s.commit()
    return c


def test_deep_crawl_breadth_first_own_site():
    seed(reset=True, samples=False)
    fetch, calls = site()
    fake = lambda body, ext: [body.decode("latin1") + " עמוד"]  # noqa: E731
    with SessionLocal() as s:
        c = _committee(s)
        out = committee_docs.deep_crawl(s, c, fetch, sleep=lambda _: None, extract=fake)
        docs = {d.url: d for d in s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id))}
        assert "https://v.example/a/b/c" in docs and "https://v.example/a/b/c/d" not in calls          # depth 3
        assert not any("search" in u or u.endswith(".jpg") or "other.example" in u or "privacy" in u for u in calls)
        assert docs["https://v.example/f/guide.pdf"].kind == "guideline" and docs["https://v.example/f/guide.pdf"].status == "ok"
        assert docs["https://v.example/f/form.pdf"].status == "ok"
        assert out["pages_stored"] == 4 and out["documents"]["new_versions"] == 2
        again = committee_docs.deep_crawl(s, c, fetch, sleep=lambda _: None, extract=fake)
        assert again["pages_unchanged"] == 4 and again["pages_stored"] == 0


def test_xplan_catalogue_exact_committee_and_searchable():
    seed(reset=True, samples=False)

    def fetch(url, cfg, hosts, form=None):
        u = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path.split("MapServer", 1)[1]
        if path == "":
            d = {"layers": [{"id": 1}]}
        elif path == "/1":
            d = {"geometryType": "esriGeometryPolygon", "fields": [{"name": n} for n in ("pl_number", "station_desc", "pl_url")]}
        else:
            assert "חוף אשקלון" in q["where"]
            d = {"features": [
                {"attributes": {"pl_number": "633-0723718", "pl_name": "זיקים", "station_desc": "אישור", "ja_concat": "חוף אשקלון",
                                "pl_objectives": "הגדלת מספר יחידות הדיור", "pl_date_8": 1620691200000}},
                {"attributes": {"pl_number": "633-0639674", "station_desc": "הפקדה", "ja_concat": "חוף אשקלון,שער הנגב"}},
                {"attributes": {"pl_number": "603-0001", "station_desc": "אישור", "ja_concat": "אשקלון"}}]}   # another committee
        return F.Fetched("ok", url, 200, "application/json", json.dumps(d).encode())
    with SessionLocal() as s:
        c = _committee(s)
        out = PD.committee_catalogue(s, c, fetch, extract=lambda *a: [])
        assert out["plans"] == 2 and out["own_only"] == 1 and out["changed"]
        texts = [p.text_he for p in s.scalars(select(CommitteePassage))]
        assert any("מטרות התכנית: הגדלת מספר יחידות הדיור" in t and "2021-05-11" in t for t in texts)
        assert not any("603-0001" in t for t in texts)
        assert not PD.committee_catalogue(s, c, fetch)["changed"]                     # same list: no new version


def test_committee_text_reaches_summary_passages_as_unverified(monkeypatch):
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        from app.models import Municipality
        _committee(s)
        committees.link_authorities(s)
        s.commit()
        assert s.get(Municipality, "hof-ashkelon").committee_id
        hits = [{"passage_id": 7, "similarity": 0.9, "committee": "חוף אשקלון", "document": "הנחיות", "page": 2,
                 "excerpt": "גובה גדר", "url": "https://v.example/g.pdf"},
                {"passage_id": 8, "similarity": 0.7, "committee": "חוף אשקלון", "document": "x", "page": 1, "excerpt": "y", "url": None}]
        monkeypatch.setattr(committee_docs, "hybrid_search", lambda *a, **k: hits)
        r = SimpleNamespace(status="FAIL", as_dict=lambda: {"status": "FAIL", "title_he": "גובה גדר", "explanation_he": "", "rule_id": "R1"})
        case = SimpleNamespace(tenant_id="hof-ashkelon")
        out = services.committee_passages(s, case, [r, r], set())
        assert [p["id"] for p in out] == ["cmt:7"] and out[0]["verification"] == "UNVERIFIED_COMMITTEE"   # below 0.84 left out
        from app.ai.gateway import _report_passages
        assert "לא מאומת" in _report_passages({"passages": out})[0]["מעמד"]
