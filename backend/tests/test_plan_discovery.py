"""XPLAN plan discovery: a crawler job; declared plans, plan-cell geometry, COVERS / PARTIAL, land use, passport."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import plan_discovery as PD
from app.db import SessionLocal
from app.main import app
from app.models import ParcelPlanDiscovery, PermitCase, Property, PropertyFact
from app.regulatory import resolve_case
from app.seed import seed
from app.source_monitor import fetch as F

HEAD = {"X-User": "u-ha-admin"}
PLAN = "633-0723718"
CELL = [[[154000, 613000], [154000, 613100], [154100, 613100], [154100, 613000], [154000, 613000]]]   # clockwise (Esri outer)


def fake_xplan(calls=None, blocked=False):
    def fetch(url, cfg, hosts, form=None):
        assert hosts == {"ags.iplan.gov.il"} and url.startswith(PD.BASE)
        if blocked:
            return F.Fetched("blocked", url, 403)
        u = urlsplit(url)
        q = {k: str(v) for k, v in form.items()} if form is not None else {k: v[0] for k, v in parse_qs(u.query).items()}
        assert ("geometry" in q) == (form is not None)           # geometry always goes in a POST body
        path = u.path.split("MapServer", 1)[1]
        if calls is not None:
            calls.append((path, q))
        if path == "":
            d = {"layers": [{"id": 0, "geometryType": "esriGeometryPoint"}, {"id": 1, "geometryType": "esriGeometryPolygon"},
                            {"id": 4, "geometryType": "esriGeometryPolygon"}]}
        elif path == "/1":
            d = {"geometryType": "esriGeometryPolygon", "fields": [{"name": n} for n in ("pl_number", "station_desc", "pl_url", "pl_name")]}
        elif path == "/4":
            d = {"geometryType": "esriGeometryPolygon", "fields": [{"name": n} for n in ("pl_number", "num", "mavat_name")]}
        elif path == "/1/query" and "where" in q and "geometry" not in q:
            d = {"features": [{"attributes": {"pl_number": PLAN, "pl_name": "זיקים", "station_desc": "אישור", "pl_date_8": 1620691200000,
                                              "pl_url": "https://mavat.iplan.gov.il/SV4/1/6000987383/310", "ja_concat": "חוף אשקלון"}}]
                 if PLAN in q["where"] else []}
        elif path == "/4/query" and "geometry" not in q:
            d = {"features": [{"attributes": {"pl_number": PLAN, "num": "368", "mavat_name": "מגורים", "station_desc": "אישור", "legal_area": 10000},
                               "geometry": {"rings": CELL}},
                              {"attributes": {"pl_number": PLAN, "num": "367", "mavat_name": "מגורים", "station_desc": "אישור"}, "geometry": {"rings": CELL}}]}
        elif path == "/1/query" and q["spatialRel"] == "esriSpatialRelIntersects":
            json.loads(q["geometry"])["rings"]          # a real polygon, not an envelope
            off = int(q["resultOffset"])
            d = {"features": [{"attributes": {"pl_number": PLAN if off == 0 else "633-0098765", "station_desc": "אישור",
                                              "pl_url": "https://evil.example/x"}}], "exceededTransferLimit": off == 0}
        elif path == "/1/query":
            d = {"features": [{"attributes": {"pl_number": PLAN}}]}
        elif path == "/4/query":
            d = {"features": [{"attributes": {"pl_number": PLAN, "num": "368", "mavat_name": "מגורים", "station_desc": "אישור"}}]}
        else:
            raise AssertionError(path)
        return F.Fetched("ok", url, 200, "application/json", json.dumps(d).encode())
    return fetch


@pytest.fixture
def env():
    seed(reset=True, samples=False)
    with TestClient(app) as c:
        yield c


def _case(s, **kw):
    c = PermitCase(tenant_id="hof-ashkelon", case_number=kw.pop("n", "xp-1"), title="t", permit_type="new", gush="2832", helka="27",
                   declared={"submission_date": "2026-11-11", **kw.pop("declared", {})}, applicable_plans=kw.pop("plans", [PLAN]))
    s.add(c)
    s.add(Property(tenant_id="hof-ashkelon", gush="2832", cell="368", plan=PLAN))
    s.flush()
    return c


def test_plan_cell_discovery_end_to_end(env):
    calls = []
    with SessionLocal() as s:
        c = _case(s)
        s.commit()
        r = PD.refresh(s, c, fake_xplan(calls), user="u-ha-admin")
        assert r["state"] == "done" and r["status"] == "CANDIDATES_FOUND" and not r["coverage_complete"]
        assert "geometry" not in r
        src = r["geometry_source"]
        assert src["kind"] == "PLAN_CELL_XPLAN" and src["cell"] == "368" and src["cell_known_from"] == "authority_ledger"
        assert r["declared_plans"][0]["found"] and r["declared_plans"][0]["published"] == "2021-05-11"
        assert r["declared_plans"][0]["url"].startswith("https://mavat.iplan.gov.il/")
        rel = {p["plan"]: p for p in r["plans"]}
        assert rel[PLAN]["relation"] == "COVERS" and rel["633-0098765"]["relation"] == "PARTIAL"
        assert rel["633-0098765"]["url"] is None                     # only Mavat links are kept
        assert r["land_use"][0]["designation"] == "מגורים"
        res = resolve_case(s, c)
        assert res["discovery"]["status"] == "CANDIDATES_FOUND" and "geometry" not in res["discovery"]
        facts = {f.kind: f for f in s.scalars(select(PropertyFact))}
        assert facts["plan"].status == "APPROVED" and facts["plan"].source_type == "xplan"
        assert facts["plan_cell"].value["designation"] == "מגורים"
    assert all(p in ("", "/1", "/4", "/1/query", "/4/query") for p, _ in calls)


def test_declared_lot_wins_and_missing_plan_is_partial(env):
    with SessionLocal() as s:
        c = _case(s, declared={"lot": "367"}, plans=[PLAN, "999-0000001"])
        s.commit()
        r = PD.refresh(s, c, fake_xplan())
        assert r["geometry_source"]["cell"] == "367" and r["geometry_source"]["cell_known_from"] == "declared"
        assert r["status"] == "PARTIAL" and [d["found"] for d in r["declared_plans"]] == [True, False]


def test_no_geometry_and_unavailable(env):
    with SessionLocal() as s:
        c = PermitCase(tenant_id="hof-ashkelon", case_number="xp-2", title="t", permit_type="new", gush="9999", helka="1",
                       declared={}, applicable_plans=[PLAN])
        s.add(c)
        s.commit()
        r = PD.refresh(s, c, fake_xplan())
        assert r["status"] == "MISSING_GEOMETRY" and r["declared_plans"][0]["found"]
        r = PD.refresh(s, c, fake_xplan(blocked=True))
        assert r["status"] == "UNAVAILABLE" and r["state"] == "done"


def test_api_queues_for_crawler_and_crawler_runs_it(env, monkeypatch):
    with SessionLocal() as s:
        cid = _case(s).id
        s.commit()
    r = env.post(f"/api/cases/{cid}/discover-plans", headers=HEAD)
    assert r.status_code == 200 and r.json()["status"] == "QUEUED"
    assert env.post(f"/api/cases/{cid}/discover-plans", headers=HEAD).json()["status"] == "QUEUED"   # no duplicate job
    assert PD.claim(SessionLocal) == cid and PD.claim(SessionLocal) is None
    assert env.get(f"/api/cases/{cid}/plan-discovery", headers=HEAD).json()["status"] == "RUNNING"
    assert PD.fail_interrupted(SessionLocal) == 1                    # crawler restarted mid-job
    assert env.get(f"/api/cases/{cid}/plan-discovery", headers=HEAD).json()["state"] == "failed"
    env.post(f"/api/cases/{cid}/discover-plans", headers=HEAD)
    monkeypatch.delenv("BBP_XPLAN_ENABLED", raising=False)
    PD.run_claimed(SessionLocal, PD.claim(SessionLocal))             # network not enabled on this server
    j = env.get(f"/api/cases/{cid}/plan-discovery", headers=HEAD).json()
    assert j["state"] == "failed" and "BBP_XPLAN_ENABLED" in j["error"]
    env.post(f"/api/cases/{cid}/discover-plans", headers=HEAD)
    PD.run_claimed(SessionLocal, PD.claim(SessionLocal), fake_xplan())
    assert env.get(f"/api/cases/{cid}/plan-discovery", headers=HEAD).json()["status"] == "CANDIDATES_FOUND"
    with SessionLocal() as s:
        assert s.get(ParcelPlanDiscovery, cid).parcel_hash


def test_viewer_cannot_queue(env):
    with SessionLocal() as s:
        cid = _case(s).id
        s.commit()
    assert env.post(f"/api/cases/{cid}/discover-plans", headers={"X-User": "u-ha-planner"}).status_code == 403


def test_esri_rings_with_hole():
    outer = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]          # clockwise
    hole = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]               # counter-clockwise
    g = PD.esri_to_geojson({"rings": [outer, hole]})
    assert g["type"] == "Polygon" and len(g["coordinates"]) == 2
    from shapely.geometry import shape
    s, tol = PD.esri_polygon(shape(g))
    assert tol == 0 and len(json.loads(s)["rings"]) == 2
