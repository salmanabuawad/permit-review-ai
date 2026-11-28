"""National committee register: import from the published list, idempotence, authority links, access."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import committees
from app.db import SessionLocal
from app.main import app
from app.models import CommitteeSettlement, Municipality, PlanningCommittee
from app.seed import seed


def test_import_is_complete_idempotent_and_links_authorities(monkeypatch):
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        s.add(Municipality(id="authority-haifa", name_he="חיפה", is_demo=False, settings={}))
        s.commit()
        first = committees.import_register(s)
        s.commit()
        assert first["committees"] == 131 and first["added"] == 131
        again = committees.import_register(s)
        assert again == {"committees": 131, "added": 0, "updated": 0, "linked": []}
        hof = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "חוף אשקלון")).one()
        assert hof.district == "דרום" and hof.vendor == "BarTech" and hof.kind == "local"
        shomron = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "שומרון")).one()
        assert shomron.kind == "regional"
        assert {t.name_he for t in s.scalars(select(CommitteeSettlement).where(CommitteeSettlement.committee_id == shomron.id))} \
            == {"אור עקיבא", "בנימינה-גבעת עדה", "זכרון יעקב", "פוריידיס", "ג'סר א-זרקא"}
        assert s.scalar(select(func.count()).select_from(PlanningCommittee).where(PlanningCommittee.kind == "regional")) == 32
        assert s.get(Municipality, "hof-ashkelon").committee_id == hof.id          # "הוועדה המקומית לתכנון ובנייה חוף אשקלון"
        assert s.get(Municipality, "authority-haifa").committee_id is not None
        hof.vendor, hof.committee_code = "other", "X1"                              # curated values survive a re-import
        s.commit()
        committees.import_register(s)
        assert (hof.vendor, hof.committee_code) == ("other", "X1")
        s.commit()


def test_api_access_and_update(monkeypatch):
    monkeypatch.setenv("BBP_AUTHORITY_CREATORS", '["u-ha-admin"]')
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        committees.import_register(s)
        s.commit()
    c = TestClient(app)
    r = c.get("/api/committees", headers={"X-User": "u-ha-admin"})
    assert r.status_code == 200 and r.json()["totals"]["committees"] == 131 and r.json()["can_edit"]
    row = next(x for x in r.json()["committees"] if x["name_he"] == "חוף אשקלון")
    assert row["kb_status"] == "IN_SYSTEM" and row["authorities"][0]["id"] == "hof-ashkelon"
    assert c.get("/api/committees", headers={"X-User": "u-planner"}).status_code == 403
    assert c.patch(f"/api/committees/{row['id']}", headers={"X-User": "u-ha-engineer"}, json={"vendor": "Complot"}).status_code == 403
    assert c.patch(f"/api/committees/{row['id']}", headers={"X-User": "u-ha-admin"}, json={"vendor": "nope"}).status_code == 422
    r = c.patch(f"/api/committees/{row['id']}", headers={"X-User": "u-ha-admin"},
                json={"request_search_url": "https://hoa.bartech-net.co.il/search", "committee_code": "614"})
    assert r.status_code == 200 and r.json()["committee_code"] == "614"


def _site(pages, redirect_to=None):
    from app.source_monitor import fetch as F
    calls = []

    def fetch(url, cfg, allowed, *a):
        calls.append(url)
        host = F.host(url)
        if redirect_to and host in redirect_to[1] and redirect_to[0] not in allowed:
            return F.Fetched("error", url, message=f"הפניה לאתר שאינו ברשם המקורות — לא נשלפה ({redirect_to[0]})")
        if host not in allowed:
            return F.Fetched("error", url, message="כתובת מחוץ לרשם המקורות")
        body = pages.get(url)
        if body is None:
            return F.Fetched("error", url, 404, message="not found")
        return F.Fetched("ok", url, 200, "text/html", body.encode(), final_url=url)
    return fetch, calls


def test_probe_finds_vendor_search_and_sources():
    seed(reset=True, samples=False)
    home = """<html><body><a href="/handasa">אגף הנדסה</a><a href="/search">איתור בקשות להיתר</a>
      <a href="https://other.example/x">הנחיות מרחביות באתר אחר</a><script src="//cdn.complot.co.il/x.js"></script></body></html>"""
    handasa = """<a href="/docs/guide.pdf">הנחיות מרחביות 2024</a><a href="/docs/taba.pdf">תב"ע 101-0012345</a>
      <a href="/forms">טפסים</a><a href="javascript:void(0)">הנחיות</a><a href="/privacy">מדיניות פרטיות</a>
      <a href="https://pay.example/eng">מחלקת הנדסה</a>"""
    fetch, calls = _site({"https://c.example/": home, "https://c.example/handasa": handasa})
    with SessionLocal() as s:
        committees.import_register(s)
        c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.vendor == "unknown")).first()
        c.website_url, c.request_search_url = "https://c.example/", None
        s.commit()
        out = committees.probe(s, c, fetch, sleep=lambda _: None)
        assert out["vendor"] == "Complot" and c.vendor == "Complot" and c.vendor_evidence == "זוהה בדף האתר"
        assert c.request_search_url == "https://c.example/search" and c.engineering_url == "https://c.example/handasa"
        kinds = {x["url"]: x["kind"] for x in c.sources}
        assert kinds["https://c.example/docs/guide.pdf"] == "guideline" and kinds["https://c.example/docs/taba.pdf"] == "plan"
        assert all(x["status"] == "candidate" for x in c.sources) and c.kb_status == "SOURCES_FOUND"
        assert "https://c.example/privacy" not in kinds                     # not a regulatory source
        assert "https://other.example/x" not in calls                      # other sites are listed, never fetched
        # a second probe keeps admin-set values and does not duplicate sources
        committees.update(s, c, {"request_search_url": "https://c.example/official-search"})
        s.commit()
        committees.probe(s, c, fetch, sleep=lambda _: None)
        assert c.request_search_url == "https://c.example/official-search" and len(c.sources) == len(kinds)


def test_probe_search_by_url_and_engineering_on_own_site():
    seed(reset=True, samples=False)
    home = """<a href="/SearchPermitApplication">מידע הנדסי</a><a href="https://pay.example/eng">הנדסה</a><a href="/eng">אגף הנדסה</a>"""
    fetch, _ = _site({"https://d.example/": home})
    with SessionLocal() as s:
        committees.import_register(s)
        c = s.scalars(select(PlanningCommittee)).first()
        c.website_url, c.engineering_url = "https://d.example/", "https://pay.example/eng"
        c.kb_detail = {"auto_fields": ["engineering_url"]}                 # set by an earlier probe: may be corrected
        s.commit()
        committees.probe(s, c, fetch, sleep=lambda _: None)
        assert c.request_search_url == "https://d.example/SearchPermitApplication"
        assert c.engineering_url == "https://d.example/eng"


def test_probe_falls_back_to_home_page():
    seed(reset=True, samples=False)
    fetch, calls = _site({"https://e.example/": "<a href='/guide.pdf'>הנחיות מרחביות</a>"})
    with SessionLocal() as s:
        committees.import_register(s)
        c = s.scalars(select(PlanningCommittee)).first()
        c.website_url = "http://e.example/Pages/default.aspx"              # gone (404)
        s.commit()
        out = committees.probe(s, c, fetch, sleep=lambda _: None)
        assert out.get("fallback") and calls[:2] == ["http://e.example/Pages/default.aspx", "https://e.example/"]
        assert c.kb_status == "SOURCES_FOUND"


def test_probe_redirect_once_and_blocked():
    seed(reset=True, samples=False)
    fetch, calls = _site({"https://old.example/": "<a href='/x'>מידע הנדסי</a>"}, redirect_to=("new.example", {"old.example"}))
    with SessionLocal() as s:
        committees.import_register(s)
        a, b = s.scalars(select(PlanningCommittee).limit(2)).all()
        a.website_url, b.website_url = "https://old.example/", "https://down.example/"
        s.commit()
        out = committees.probe(s, a, fetch, sleep=lambda _: None)
        assert out.get("redirected_to") == "new.example" and a.kb_status == "SITE_PROBED"
        committees.probe(s, b, fetch, sleep=lambda _: None)
        assert b.kb_status == "BLOCKED" and b.kb_detail["probe"]["errors"]


def test_probe_queue_and_worker(monkeypatch):
    monkeypatch.setenv("BBP_AUTHORITY_CREATORS", '["u-ha-admin"]')
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        committees.import_register(s)
        s.commit()
    c = TestClient(app)
    assert c.post("/api/committees/probe", headers={"X-User": "u-ha-engineer"}, json={}).status_code == 403
    assert c.post("/api/committees/probe", headers={"X-User": "u-ha-admin"}, json={}).json()["queued"] == 131
    assert c.post("/api/committees/probe", headers={"X-User": "u-ha-admin"}, json={}).json()["queued"] == 0   # already queued
    fetch, _ = _site({})
    cid = committees.claim_probe(SessionLocal)
    committees.run_probe(SessionLocal, cid, fetch, sleep=lambda _: None)
    with SessionLocal() as s:
        done = s.get(PlanningCommittee, cid)
        assert done.kb_detail["probe"]["state"] == "done" and done.kb_status == "BLOCKED"


def test_interrupted_jobs_marked_failed():
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        committees.import_register(s)
        c = s.scalars(select(PlanningCommittee)).first()
        c.kb_detail = {"fetch": {"state": "running"}}
        cid = c.id
        s.commit()
    assert committees.fail_interrupted(SessionLocal) == 1
    with SessionLocal() as s:
        assert s.get(PlanningCommittee, cid).kb_detail["fetch"]["state"] == "failed"


def test_uploaded_documents_make_a_blocked_committee_ready():
    """A committee whose site is blocked gets its knowledge base from uploads; a later failed probe keeps that."""
    import pymupdf

    from app import committee_docs as CD
    seed(reset=True, samples=False)
    fetch, _ = _site({})
    with SessionLocal() as s:
        committees.import_register(s)
        c = s.scalars(select(PlanningCommittee).limit(1)).one()
        c.website_url = "https://down.example/"
        s.commit()
        committees.probe(s, c, fetch, sleep=lambda _: None)
        assert c.kb_status == "BLOCKED"
        d = pymupdf.open()
        d.new_page().insert_text((72, 72), "committee guideline uploaded by the administrator")
        CD.upload(s, c.id, d.tobytes(), "g.pdf", "guideline", "", "admin")
        s.commit()
        assert c.kb_status == "DOCUMENTS_FETCHED"
        committees.probe(s, c, fetch, sleep=lambda _: None)          # the site is still down
        assert c.kb_status == "DOCUMENTS_FETCHED" and c.kb_detail["probe"]["errors"]
