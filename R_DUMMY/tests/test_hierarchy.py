"""Regulatory hierarchy, terminology, clause cutting and hierarchy-scoped search."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import committees, hierarchy as H
from app.db import SessionLocal
from app.main import app
from app.models import (CommitteeDocument, CommitteePassage, CommitteeSnapshot, Municipality, PlanningCommittee,
                        RegulatoryClause)
from app.seed import seed

PAGE = """הנחיות מרחביות — הוועדה המקומית
1. כללי
1.1 ההנחיות חלות על כל שטח הוועדה.
2. גדרות
2.1 גובה גדר בנויה לא יעלה על 1.5 מטר.
א. בחזית הפונה לרחוב — עד 1.2 מטר.
ב. בגבול צדדי — עד 1.8 מטר.
3. חנייה
3.1 בכל יחידת דיור יוסדרו 2 מקומות חנייה."""


def test_split_clauses_numbering_and_parents():
    cs = H.split_clauses(PAGE)
    nums = [c["number"] for c in cs]
    assert nums == [None, "1", "1.1", "2", "2.1", "א", "ב", "3", "3.1"]
    by = {c["number"]: c for c in cs}
    assert cs[by["2.1"]["parent"]]["number"] == "2" and cs[by["א"]["parent"]]["number"] == "2.1"
    assert H.split_clauses("טקסט בלי מספור כלל") == [{"number": None, "depth": 0, "start": 0, "end": 18, "parent": None}]


def test_terminology_synonyms_and_distinct_concepts():
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        H.seed_terms(s)
        idx = H.term_index(s)
        assert H.topics_of("מקומות חנייה בחצר", idx) == ["parking"]
        assert "חניה" in H.expand("חנייה", idx) and "מצללה" in H.expand("פרגולה", idx)
        assert H.topics_of("גובה פנימי של הקומה", idx) == ["internal_height"]      # not merged with building height
        assert "גובה הבניין" not in H.expand("גובה פנימי", idx)
        assert H.topics_of("בקווי הבנין המותרים", idx) == ["building_line"]        # prefix and spelling


def _clauses_for(s, name, text):
    c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == name)).one()
    d = CommitteeDocument(committee_id=c.id, url=f"https://{c.id}/g.pdf", title="הנחיות", kind="guideline", status="ok", sha256=c.id.ljust(64, "0"))
    s.add(d)
    s.flush()
    sn = CommitteeSnapshot(document_id=d.id, sha256=d.sha256, content_type="application/pdf", size=1, path="x", pages=1, text_status="ok")
    s.add(sn)
    s.flush()
    s.add(CommitteePassage(snapshot_id=sn.id, page=1, text_he=text))
    s.commit()


def test_hierarchy_chain_and_scoped_search():
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        committees.import_register(s)
        counts = H.build(s)
        s.commit()
        assert counts["NATIONAL"] == 1 and counts["DISTRICT"] == 6 and counts["PLANNING_COMMITTEE"] == 131
        hof = s.get(Municipality, "hof-ashkelon")
        assert H.chain(s, "hof-ashkelon") == ["authority:hof-ashkelon", f"committee:{hof.committee_id}", "district:דרום", "IL"]
        _clauses_for(s, "חוף אשקלון", PAGE)
        _clauses_for(s, "חיפה", "1. חנייה\n1.1 בחיפה נדרשים 3 מקומות חנייה ליחידה.")
        assert H.extract_clauses(s) >= 9
        assert H.extract_clauses(s) == 0                                      # incremental
        r = H.search(s, "hof-ashkelon", "חניה")
        texts = [c["text_he"] for c in r["clauses"]]
        assert any("2 מקומות חנייה" in t for t in texts) and not any("בחיפה" in t for t in texts)   # Haifa's is out of scope
        assert "חנייה" in r["expanded"] and r["concepts"] == ["parking"]
        two_one = s.scalars(select(RegulatoryClause).where(RegulatoryClause.number == "א")).first()
        assert s.get(RegulatoryClause, two_one.parent_id).number == "2.1" and "fence" in s.get(RegulatoryClause, two_one.parent_id).topics


def test_api(monkeypatch):
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        committees.import_register(s)
        H.build(s)
        s.commit()
        _clauses_for(s, "חוף אשקלון", PAGE)
        H.extract_clauses(s)
    c = TestClient(app)
    r = c.get("/api/knowledge/clauses", params={"q": "גדר"}, headers={"X-User": "u-ha-admin"}).json()
    assert r["clauses"] and r["scope"][0] == "authority:hof-ashkelon"
    levels = [j["kind"] for j in c.get("/api/knowledge/hierarchy", headers={"X-User": "u-ha-admin"}).json()]
    assert levels == ["LOCAL_AUTHORITY", "PLANNING_COMMITTEE", "DISTRICT", "NATIONAL"]
    assert any(t["concept"] == "pergola" for t in c.get("/api/terminology", headers={"X-User": "u-ha-admin"}).json())
    assert c.post("/api/terminology", json={"concept": "pergola", "term": "סוכך"}, headers={"X-User": "u-ha-engineer"}).status_code == 201
    assert c.post("/api/terminology", json={"concept": "pergola", "term": "סוכך"}, headers={"X-User": "u-ha-engineer"}).status_code == 409
