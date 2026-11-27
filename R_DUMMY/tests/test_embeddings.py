"""Local embeddings: chunking, incremental indexing, semantic + keyword fusion, model isolation, fallback."""
import hashlib
import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import committees, embeddings as E
from app.db import SessionLocal
from app.main import app
from app.models import CommitteeChunk, CommitteeDocument, CommitteePassage, CommitteeSnapshot, PlanningCommittee
from app.seed import seed


def fake_model(texts):
    """Bag of word hashes → unit vector (deterministic stand-in for the real model)."""
    out = []
    for t in texts:
        v = [0.0] * E.DIM
        for w in t.replace(":", " ").split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % E.DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def test_chunks_cover_text_with_overlap():
    text = ("סעיף 1. קו בניין קדמי 5 מטר.\n" * 60)
    spans = E.chunks(text)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(b - a <= E.CHUNK + 1 for a, b in spans)
    assert all(spans[i + 1][0] < spans[i][1] for i in range(len(spans) - 1))     # overlap keeps neighbours together
    assert E.chunks("קצר") == []


def _passages(s):
    committees.import_register(s)
    c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "חוף אשקלון")).one()
    d = CommitteeDocument(committee_id=c.id, url="https://x/a.pdf", title="הנחיות", kind="guideline", status="ok", sha256="a" * 64)
    s.add(d)
    s.flush()
    sn = CommitteeSnapshot(document_id=d.id, sha256="a" * 64, content_type="application/pdf", size=1, path="aa/a.pdf",
                           pages=2, text_status="ok")
    s.add(sn)
    s.flush()
    s.add_all([CommitteePassage(snapshot_id=sn.id, page=1, text_he="קו בניין קדמי יהיה חמישה מטר מגבול המגרש הקדמי של החלקה"),
               CommitteePassage(snapshot_id=sn.id, page=2, text_he="גובה גדר בנויה לא יעלה על מטר וחצי מעל פני הקרקע הסמוכה")])
    s.commit()
    return c


def test_index_incremental_and_search(monkeypatch):
    monkeypatch.setenv("BBP_AUTHORITY_CREATORS", '["u-ha-admin"]')
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        _passages(s)
        first = E.index(s, model=fake_model)
        assert first == {"chunks_made": 2, "embedded": 2}
        assert E.index(s, model=fake_model) == {"chunks_made": 0, "embedded": 0}          # nothing new
        assert all(ch.model == E.MODEL_ID for ch in s.scalars(select(CommitteeChunk)))
        hits = E.semantic(s, "גובה גדר", model=fake_model)
        top = s.get(CommitteeChunk, hits[0][0])
        assert s.get(CommitteePassage, top.passage_id).page == 2
    monkeypatch.setattr(E, "embedder", lambda threads=2: fake_model)
    c = TestClient(app)
    r = c.get("/api/committees/passages", params={"q": "גובה גדר"}, headers={"X-User": "u-ha-admin"}).json()
    assert r[0]["page"] == 2 and set(r[0]["found_by"]) == {"keyword", "semantic"}
    r = c.get("/api/committees/passages", params={"q": "מרחק מגבול החלקה", "mode": "semantic"}, headers={"X-User": "u-ha-admin"}).json()
    assert r and r[0]["found_by"] == ["semantic"] and r[0]["page"] == 1


def test_other_model_vectors_never_mixed_and_fallback(monkeypatch):
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        _passages(s)
        E.index(s, model=fake_model)
        for ch in s.scalars(select(CommitteeChunk)):
            ch.model = "another-model@1"
        s.commit()
        assert E.semantic(s, "גובה גדר", model=fake_model) == []
    monkeypatch.setattr(E, "embedder", lambda threads=2: None)                          # model not installed
    monkeypatch.setenv("BBP_AUTHORITY_CREATORS", '["u-ha-admin"]')
    r = TestClient(app).get("/api/committees/passages", params={"q": "גובה גדר"}, headers={"X-User": "u-ha-admin"}).json()
    assert r and r[0]["found_by"] == ["keyword"]


def test_rrf():
    assert E.rrf([1, 2, 3], [3, 1]) [:2] == [1, 3]


@pytest.mark.skipif(not E.available(), reason="model files not installed here")
def test_real_model_ranks_hebrew_meaning():
    m = E.embedder()
    q = m(["query: מה המרחק המינימלי של קו בניין קדמי?"])[0]
    d = m(["passage: קו הבניין הקדמי יהיה 5 מטר מגבול המגרש", "passage: גובה גדר לא יעלה על 1.5 מטר"])
    sims = [sum(a * b for a, b in zip(q, v)) for v in d]
    assert sims[0] > sims[1]
