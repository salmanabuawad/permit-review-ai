"""Construction360: scheduling, approved vs observed with tolerance, passport OBSERVED facts, photo validation."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import PermitCase, PropertyFact
from app.seed import seed

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_inspection_flow():
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        c = PermitCase(tenant_id="hof-ashkelon", case_number="P-1", title="בית", permit_type="addition_extension", gush="2832", helka="27")
        s.add(c)
        s.commit()
        cid = c.id
    cl = TestClient(app)
    A = {"X-User": "u-ha-admin"}
    assert cl.post(f"/api/cases/{cid}/inspections", headers=A, json={"milestone": "roofing"}).status_code == 422
    i = cl.post(f"/api/cases/{cid}/inspections", headers=A, json={"milestone": "frame", "scheduled_for": "2026-12-01"}).json()
    assert i["status"] == "scheduled" and i["milestone_he"] == "שלד"
    r = cl.post(f"/api/inspections/{i['id']}/result", headers=A, json={"notes": "בדיקת שלד", "observations": [
        {"item": "גובה בניין", "unit": "מ׳", "approved": 9.0, "observed": 9.4, "tolerance": 0.1},
        {"item": "קו בניין קדמי", "unit": "מ׳", "approved": 5.0, "observed": 5.02, "tolerance": 0.05}]})
    d = r.json()
    assert r.status_code == 200 and d["result"] == "deviations"
    assert d["observations"][0]["deviation"]["beyond_tolerance"] and not d["observations"][1]["deviation"]["beyond_tolerance"]
    assert cl.post(f"/api/inspections/{i['id']}/result", headers=A, json={"observations": [{"item": "x"}]}).status_code == 409
    with SessionLocal() as s:
        facts = s.scalars(select(PropertyFact).where(PropertyFact.kind == "inspection")).all()
        assert len(facts) == 2 and all(f.status == "OBSERVED" for f in facts)
    assert cl.post(f"/api/inspections/{i['id']}/photos", headers=A, files={"file": ("x.gif", b"GIF89a....")}).status_code == 422
    ok = cl.post(f"/api/inspections/{i['id']}/photos", headers=A, files={"file": ("x.png", PNG)}, data={"lat": "31.6", "lon": "34.5"})
    assert ok.status_code == 200 and ok.json()["photos"][0]["lat"] == 31.6 and "path" not in ok.json()["photos"][0]
    sha = ok.json()["photos"][0]["sha256"]
    assert cl.get(f"/api/inspections/{i['id']}/photos/{sha}", headers=A).content == PNG
    assert cl.post(f"/api/cases/{cid}/inspections", headers={"X-User": "u-ha-engineer"}, json={"milestone": "start"}).status_code == 201
