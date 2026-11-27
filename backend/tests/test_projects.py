"""Permit360 Pro projects: committee discovery from official boundaries (path B), verification (path A), creation,
package, workflow, assistant and committee uploads. Spatial accuracy on synthetic EPSG:2039 polygons."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import committees, jurisdiction as J, projects as P
from app.ai.gateway import AIResult
from app.db import SessionLocal
from app.main import app
from app.models import CadastreParcel, GeoQueryCache, PermitCase, PlanningCommittee
from app.seed import seed

H = {"X-User": "u-ha-planner"}
X0, Y0 = 160000, 610000


def sq(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]]}


AREA_HOF = sq(X0, Y0, X0 + 1000, Y0 + 1000)
AREA_ASH = sq(X0 + 1000, Y0, X0 + 2000, Y0 + 1000)
AREA_GLILI = sq(X0, Y0 + 1000, X0 + 1000, Y0 + 2000)
PARCELS = {(2832, 27): sq(X0 + 100, Y0 + 100, X0 + 200, Y0 + 200),          # inside Hof Ashkelon
           (2832, 28): sq(X0 + 950, Y0 + 100, X0 + 1050, Y0 + 200),         # straddles Hof Ashkelon / Ashkelon
           (2832, 29): sq(X0 + 100, Y0 + 1100, X0 + 200, Y0 + 1200),        # district-administered area
           (2832, 30): sq(X0 + 999.8, Y0 + 300, X0 + 1099.8, Y0 + 400)}     # 0.2 % across a border: a boundary artefact? no — 99.8 % in Ashkelon


def feats(*areas):
    return [{"attrs": {"MT_Heb": n, "CodeMT": c, "Sug_MT": t, "Machoz": "דרום", "Muni_In_MT": m}, "geometry": g} for n, c, t, m, g in areas]


@pytest.fixture
def env():
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        committees.import_register(s)
        committees.link_authorities(s)
        for (g, h), geo in PARCELS.items():
            s.add(CadastreParcel(gush=g, helka=h, gush_suffix=0, status="מוסדר", locality="זיקים", source="test 2026", geojson=json.dumps(geo)))
        s.commit()
        J.load(s, "planning_area", feats(("חוף אשקלון", "633", "מקומי", "מ.א. חוף אשקלון", AREA_HOF),
                                         ("אשקלון", "604", "מקומי", "עיריית אשקלון", AREA_ASH),
                                         ("גלילי - דרום", "699", "גלילי", " ", AREA_GLILI)))
        J.load(s, "village", [{"attrs": {"Vaad_Heb": "זיקים", "Muni_Heb": "חוף אשקלון"}, "geometry": AREA_HOF}])
    with TestClient(app) as c:
        yield c


def hof(s):
    return s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "חוף אשקלון")).one()


def test_linking_and_codes(env):
    with SessionLocal() as s:
        links = J.counts(s)["links"]
        assert links == {"name_exact": 2, "district_administered": 1}
        assert hof(s).planning_area_codes == ["633"]


def test_path_b_discovery_states(env):
    with SessionLocal() as s:
        r = J.discover(s, "2832", "27")
        assert r["status"] == "RESOLVED" and r["committee_id"] == hof(s).id and r["candidates"][0]["code"] == "633"
        assert r["localities"][0]["name_he"] == "זיקים" and not r["cached"]
        assert J.discover(s, "2832", "27")["cached"]
        r = J.discover(s, "2832", "28")
        assert r["status"] == "AMBIGUOUS" and {x["name_he"] for x in r["candidates"]} == {"חוף אשקלון", "אשקלון"}
        assert abs(sum(x["share"] for x in r["candidates"]) - 1) < 1e-6 and r["committee_id"] is None
        assert J.discover(s, "2832", "29")["status"] == "UNLINKED"
        assert J.discover(s, "2832", "30")["status"] == "RESOLVED"                  # 0.2 % sliver is not a candidate
        assert J.discover(s, "2832", "99")["reason"] == "parcel_not_found"
        assert J.discover(s, "abc", "1")["reason"] == "invalid_identifier"


def test_dataset_refresh_invalidates_cache_and_keeps_history(env):
    with SessionLocal() as s:
        J.discover(s, "2832", "27")
        out = J.load(s, "planning_area", feats(("אשקלון", "604", "מקומי", "עיריית אשקלון", sq(X0, Y0, X0 + 2000, Y0 + 1000))))
        assert out["changed"] and s.scalar(select(GeoQueryCache).limit(1)) is None
        r = J.discover(s, "2832", "27")
        assert r["candidates"][0]["name_he"] == "אשקלון"                       # the boundary changed: new answer
        from app.models import GeoDataset
        assert len(list(s.scalars(select(GeoDataset).where(GeoDataset.name == "iplan.gvulot_retzef.planning_area")))) == 2


def test_path_a_verification(env):
    with SessionLocal() as s:
        ash = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "אשקלון")).one()
        assert J.verify(s, hof(s).id, "2832", "27")["status"] == "VERIFIED"
        assert J.verify(s, ash.id, "2832", "27")["status"] == "MISMATCH"
        assert J.verify(s, ash.id, "2832", "28")["status"] == "AMBIGUOUS"


def test_create_projects_both_paths(env):
    with SessionLocal() as s:
        hid = hof(s).id
        ash = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "אשקלון")).one().id
    c = env
    assert c.post("/api/projects", json={"path": "B", "gush": "2832", "helka": "27"}, headers=H).status_code == 422   # not confirmed
    r = c.post("/api/projects", json={"path": "B", "gush": "2832", "helka": "27", "confirm": True}, headers=H)
    assert r.status_code == 201 and r.json()["jurisdiction"]["status"] == "RESOLVED" and r.json()["kind"] == "design"
    assert "xplan_discovery" in r.json()["workflow"]["knowledge"]["queued"]
    pid = r.json()["id"]
    r = c.post("/api/projects", json={"path": "B", "gush": "2832", "helka": "28", "confirm": True}, headers=H)
    assert r.status_code == 409 and len(r.json()["detail"]["result"]["candidates"]) == 2                    # never guessed
    r = c.post("/api/projects", json={"path": "B", "gush": "2832", "helka": "28", "committee_id": ash, "confirm": True}, headers=H)
    assert r.json()["jurisdiction"]["status"] == "CANDIDATE_SELECTED"
    assert c.post("/api/projects", json={"path": "A", "gush": "2832", "helka": "27", "committee_id": ash, "confirm": True},
                  headers=H).status_code == 409                                                               # mismatch
    r = c.post("/api/projects", json={"path": "A", "gush": "2832", "helka": "27", "committee_id": hid, "lot": "368", "confirm": True}, headers=H)
    assert r.json()["jurisdiction"]["status"] == "VERIFIED"
    assert c.post("/api/projects", json={"path": "A", "gush": "2832", "helka": "99", "committee_id": hid, "confirm": True},
                  headers=H).status_code == 409                                                               # no official data
    r = c.post("/api/projects", json={"path": "A", "gush": "2832", "helka": "99", "committee_id": hid, "confirm": True, "manual": True}, headers=H)
    assert r.json()["jurisdiction"]["status"] == "MANUAL_UNRESOLVED"
    assert c.post("/api/projects", json={"path": "B", "gush": "28x", "helka": "1", "confirm": True}, headers=H).status_code == 422
    # package / workflow / purpose
    v = c.get(f"/api/projects/{pid}", headers=H).json()
    assert v["package"]["jurisdiction"]["current"]["status"] == "RESOLVED"
    assert [x["key"] for x in v["workflow"]["stages"]][:3] == ["property", "jurisdiction", "knowledge"]
    assert v["workflow"]["stages"][0]["status"] == "done" and v["workflow"]["stages"][2]["status"] == "pending"
    assert any("מטרת הבקשה" in a for a in v["workflow"]["next_actions"])
    assert c.put(f"/api/projects/{pid}/purpose", json={"permit_type": "new_building", "purpose": "בית מגורים"}, headers=H).status_code == 200
    v = c.get(f"/api/projects/{pid}", headers=H).json()
    assert next(x for x in v["workflow"]["stages"] if x["key"] == "purpose")["status"] == "done"
    assert c.get(f"/api/projects/{pid}", headers={"X-User": "u-ha-reviewer"}).status_code in (403, 404)       # private
    with SessionLocal() as s:
        assert s.get(PermitCase, pid).committee_id == hid


def test_assistant_grounded_and_unavailable(env, monkeypatch):
    r = env.post("/api/projects", json={"path": "B", "gush": "2832", "helka": "27", "confirm": True}, headers=H).json()

    class GW:
        def route(self, task, data_class, payload, log=None):
            assert task == "Assistant" and data_class == "PROJECT" and payload["facts"]["property"]["gush"] == "2832"
            return AIResult(task, "OK", "local_ollama", "m", {"text": "יש לקרוא את הוראות התכנית."})
    from app import services
    monkeypatch.setattr(services, "gateway_for", lambda *a, **k: GW())
    out = env.post(f"/api/projects/{r['id']}/assistant", json={"question": "מה מותר לבנות?"}, headers=H).json()
    assert out["answer"] == "יש לקרוא את הוראות התכנית." and out["outcome"] == "OK"

    class Down:
        def route(self, *a, **k):
            return AIResult("Assistant", "MANUAL_REVIEW", None, None)
    monkeypatch.setattr(services, "gateway_for", lambda *a, **k: Down())
    out = env.post(f"/api/projects/{r['id']}/assistant", json={"question": "מה מותר לבנות?"}, headers=H).json()
    assert out["answer"] is None and "אינו זמין" in out["note_he"]


def test_assistant_rejects_invented_numbers():
    from app.ai import gateway as G
    payload = {"question": "גובה?", "facts": {"plans": ["633-0723718"]}, "passages": []}
    text, grounding = G.assistant_prompt(payload)
    assert "633-0723718" in grounding and G._ungrounded_numbers("הגובה המותר 12.5 מ'", grounding) == ["12.5"]


def test_directory_and_upload(env):
    c = env
    rows = c.get("/api/committees/directory?q=633", headers=H).json()
    assert rows and rows[0]["name_he"] == "חוף אשקלון"
    assert any(r["name_he"] == "חוף אשקלון" for r in c.get("/api/committees/directory?q=חוף", headers=H).json())
    with SessionLocal() as s:
        hid = hof(s).id
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "guidelines 2026")
    pdf = doc.tobytes()
    up = c.post(f"/api/committees/{hid}/upload", files={"file": ("guide.pdf", pdf, "application/pdf")},
                data={"kind": "guideline", "title": "הנחיות מרחביות"}, headers={"X-User": "u-ha-admin"})
    assert up.status_code == 201 and up.json()["kind"] == "guideline"
    assert c.post(f"/api/committees/{hid}/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")},
                  headers={"X-User": "u-ha-admin"}).status_code == 422
    assert c.post(f"/api/committees/{hid}/upload", files={"file": ("g.pdf", b"%PDF-1.4", "application/pdf")},
                  headers=H).status_code == 403                                                              # planners cannot


def test_wizard_submit_gives_confirmation_number_and_opens_committee_case(env, monkeypatch):
    from app import mailer
    from app.models import Municipality, Submission
    from pathlib import Path
    FIX = Path(__file__).resolve().parents[2] / "fixtures" / "demo"
    monkeypatch.setattr(mailer, "transport", [])
    pdf = (FIX / "survey_map.pdf").read_bytes()
    c = env
    with SessionLocal() as s:
        hid = hof(s).id
        ws = s.scalars(select(Municipality).where(Municipality.committee_id == hid, Municipality.is_demo.is_(False))).first()
        assert ws is not None
        wsid = ws.id
    pid = c.post("/api/projects", json={"path": "B", "gush": "2832", "helka": "27", "confirm": True}, headers=H).json()["id"]
    v = c.get(f"/api/projects/{pid}", headers=H).json()
    assert v["submission"] is None and v["committee_connected"] and not all(x["done"] for x in v["checklist"])
    assert c.post(f"/api/projects/{pid}/submit", json={"declaration": True}, headers=H).status_code == 422     # nothing yet
    assert c.put(f"/api/projects/{pid}/purpose", json={"permit_type": "new_building", "purpose": "בית מגורים"}, headers=H).status_code == 200
    assert c.post(f"/api/cases/{pid}/files", headers=H, files={"file": ("survey_map.pdf", pdf)},
                  data={"doc_type": "survey_map"}).status_code == 200
    assert c.post(f"/api/projects/{pid}/submit", json={"declaration": False}, headers=H).status_code == 422     # declaration
    r = c.post(f"/api/projects/{pid}/submit", json={"declaration": True}, headers=H)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["confirmation_number"].startswith("P360-") and len(out["confirmation_number"]) == 16 and out["connected"]
    assert c.post(f"/api/projects/{pid}/submit", json={"declaration": True}, headers=H).status_code == 409      # once
    assert c.post(f"/api/cases/{pid}/files", headers=H, files={"file": ("x.pdf", pdf + b" ")},
                  data={"doc_type": "other"}).status_code == 409                                                 # frozen
    assert c.put(f"/api/projects/{pid}/purpose", json={"permit_type": "new_building", "purpose": "x"}, headers=H).status_code == 409
    assert c.get(f"/api/projects/{pid}", headers=H).json()["submission"]["confirmation_number"] == out["confirmation_number"]
    assert c.get("/api/submissions", headers=H).json()[0]["project_id"] == pid
    with SessionLocal() as s:
        sub = s.scalars(select(Submission).where(Submission.project_id == pid)).one()
        t = s.get(PermitCase, sub.target_case_id)
        assert t.tenant_id == wsid and t.case_number == sub.confirmation_number and t.kind == "application"
        assert len(t.files) == 1 and t.declared["submitted_via"] == "permit360-pro" and t.source == "pro"
    # the committee's reviewers see it in their case list
    assert any(x["case_number"] == out["confirmation_number"] for x in c.get("/api/cases", headers={"X-User": "u-ha-admin"}).json())


def test_submission_to_unconnected_committee_still_gets_a_number(env, monkeypatch):
    from app import mailer
    from app import submissions as SB
    from app.models import CaseFile
    monkeypatch.setattr(mailer, "transport", [])
    with SessionLocal() as s:
        ash = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "אשקלון")).one()
        case = P.create(s, "hof-ashkelon", "u-ha-planner", "B", "2832", "28", committee_id=ash.id)
        case.declared = {**case.declared, "purpose": "תוספת חדר"}
        s.add(CaseFile(tenant_id=case.tenant_id, case_id=case.id, doc_type="survey_map", filename="a.pdf", kind="pdf",
                       sha256="0" * 64, size_bytes=1, storage_path="/nonexistent"))
        s.commit()
        out = SB.submit(s, case, "u-ha-planner", True)
        assert not out["connected"] and out["confirmation_number"].startswith("P360-") and "רישוי זמין" in out["note_he"]
        assert case.status == "SUBMITTED"
