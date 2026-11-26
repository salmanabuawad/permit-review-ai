"""Building360: passports from register snapshots, signed tables and cases; standing, supersession, as-of queries."""
import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import building as B
from app.db import SessionLocal
from app.main import app
from app.models import PermitCase, Property, PropertyFact
from app.seed import seed


def test_ledger_sync_standing_and_idempotence():
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        first = B.sync_ledgers(s, "hof-ashkelon")
        s.commit()
        assert first["new"] >= 50 and first["changed"] == 0
        again = B.sync_ledgers(s, "hof-ashkelon")
        assert again["new"] == 0 and again["changed"] == 0 and again["same"] == first["new"]
        cell = s.scalars(select(Property).where(Property.gush == "2832", Property.cell == "368")).one()
        pp = B.passport(s, "hof-ashkelon", cell)
        assert set(pp["by_status"]) <= set(B.STATUSES) and pp["by_status"].get("APPROVED", 0) > 0
        assert any(f["status"] == "UNVERIFIED" and "unverified_reason" in f["value"] for f in pp["facts"])
        table = [f for f in pp["facts"] if f["kind"] == "area_table"]
        assert table and all((f["status"] == "APPROVED") == all(a["closes"] for a in f["value"]["arithmetic"]) for f in table)
        old = B.passport(s, "hof-ashkelon", cell, as_of=dt.date(1970, 1, 1))
        assert 0 < len(old["facts"]) < len(pp["facts"])                  # only what was valid in 1970 (and undated facts)


def test_supersession_keeps_history_and_case_api():
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        c = PermitCase(tenant_id="hof-ashkelon", case_number="T-1", title="בדיקה", permit_type="addition_extension",
                       gush="2832", helka="27", declared={"floors": 2, "submission_date": "2026-01-01"})
        s.add(c)
        s.commit()
        cid = c.id
        assert B.sync_cases(s, "hof-ashkelon")["new"] == 2
        before = dt.datetime.now(dt.timezone.utc)
        c.declared = {"floors": 3, "submission_date": "2026-01-01"}
        s.commit()
        assert B.sync_cases(s, "hof-ashkelon")["changed"] == 1
        s.commit()
        prop = s.scalars(select(Property).where(Property.helka == "27")).one()
        now_ = {f["key"]: f for f in B.passport(s, "hof-ashkelon", prop)["facts"]}
        then = {f["key"]: f for f in B.passport(s, "hof-ashkelon", prop, known_at=before)["facts"]}
        assert now_["T-1:floors"]["value"]["value"] == 3 and then["T-1:floors"]["value"]["value"] == 2
        assert s.scalar(select(PropertyFact.id).where(PropertyFact.key == "T-1:floors", PropertyFact.superseded_at.is_not(None)))
    c = TestClient(app)
    r = c.get(f"/api/cases/{cid}/properties", headers={"X-User": "u-ha-admin"})
    assert r.status_code == 200 and r.json()[0]["property"]["helka"] == "27"
    assert c.post("/api/properties/sync", headers={"X-User": "u-ha-admin"}).status_code == 200
    assert c.get("/api/properties?gush=2832", headers={"X-User": "u-ha-admin"}).json()
