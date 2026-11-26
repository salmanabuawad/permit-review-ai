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
    assert c.get("/api/committees", headers={"X-User": "u-reviewer"}).status_code == 403
    assert c.patch(f"/api/committees/{row['id']}", headers={"X-User": "u-ha-engineer"}, json={"vendor": "Complot"}).status_code == 403
    assert c.patch(f"/api/committees/{row['id']}", headers={"X-User": "u-ha-admin"}, json={"vendor": "nope"}).status_code == 422
    r = c.patch(f"/api/committees/{row['id']}", headers={"X-User": "u-ha-admin"},
                json={"request_search_url": "https://hoa.bartech-net.co.il/search", "committee_code": "614"})
    assert r.status_code == 200 and r.json()["committee_code"] == "614"
