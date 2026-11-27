"""Fetching committee candidate sources: scope, versions, linked documents, dedup, search, sandboxed extraction."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import committee_docs, committees
from app.db import SessionLocal
from app.main import app
from app.models import CommitteeDocument, CommitteeSnapshot, PlanningCommittee
from app.seed import seed
from app.source_monitor import fetch as F


def _site(files: dict):
    calls = []

    def fetch(url, cfg, allowed, etag=None, lm=None):
        calls.append(url)
        if F.host(url) not in allowed:
            return F.Fetched("error", url, message="כתובת מחוץ לרשם המקורות")
        if url not in files:
            return F.Fetched("error", url, 404, message="not found")
        ct, body = files[url]
        return F.Fetched("ok", url, 200, ct, body, final_url=url)
    return fetch, calls


def _committee(s, url, sources):
    c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "חוף אשקלון")).one()
    c.website_url, c.sources = url, sources
    s.commit()
    return c


def test_fetch_scope_versions_and_links():
    seed(reset=True, samples=False)
    files = {
        "https://v.example/guide": ("text/html", "<h1>הנחיות מרחביות</h1><p>גובה גדר 1.5 מ'</p><a href='/f/guide.pdf'>הנחיות מרחביות 2024</a><a href='/f/menu.pdf'>תפריט</a>".encode()),
        "https://v.example/f/guide.pdf": ("application/pdf", b"%PDF-guide-v1"),
        "https://v.example/f/taba.pdf": ("application/pdf", b"%PDF-taba"),
    }
    fetch, calls = _site(files)
    fake = lambda body, ext: [body.decode("latin1") + " עמוד 1", "עמוד 2"]  # noqa: E731
    with SessionLocal() as s:
        committees.import_register(s)
        c = _committee(s, "https://v.example/", [
            {"url": "https://v.example/guide", "title": "הנחיות מרחביות", "kind": "guideline"},
            {"url": "https://v.example/f/taba.pdf", "title": "תב\"ע", "kind": "plan"},
            {"url": "https://other.example/x.pdf", "title": "הנחיות", "kind": "guideline"},
            {"url": "https://v.example/old.doc", "title": "טפסים", "kind": "procedure"}])
        out = committee_docs.fetch_committee(s, c, fetch, sleep=lambda _: None, extract=fake)
        docs = {d.url: d for d in s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id))}
        assert docs["https://other.example/x.pdf"].status == "skipped" and "https://other.example/x.pdf" not in calls
        assert docs["https://v.example/old.doc"].status == "skipped"
        assert docs["https://v.example/f/guide.pdf"].found_on == "https://v.example/guide"      # followed one level
        assert docs["https://v.example/f/guide.pdf"].kind == "guideline"                      # its own title decides
        assert "https://v.example/f/menu.pdf" not in docs                                     # irrelevant link
        assert docs["https://v.example/f/taba.pdf"].status == "ok" and out["linked_documents"] == 1
        snap = s.scalars(select(CommitteeSnapshot).where(CommitteeSnapshot.document_id == docs["https://v.example/f/taba.pdf"].id)).one()
        assert snap.pages == 2 and snap.text_status == "ok" and (committee_docs.store_root() / snap.path).read_bytes() == b"%PDF-taba"
        # second run: same bytes -> unchanged, no new snapshot; a changed document -> a new version
        files["https://v.example/f/guide.pdf"] = ("application/pdf", b"%PDF-guide-v2")
        out2 = committee_docs.fetch_committee(s, c, fetch, sleep=lambda _: None, extract=fake)
        assert out2["new_versions"] == 1 and out2["unchanged"] >= 2
        g = docs["https://v.example/f/guide.pdf"]
        assert len(s.scalars(select(CommitteeSnapshot).where(CommitteeSnapshot.document_id == g.id)).all()) == 2


def test_same_file_text_reused_and_search(monkeypatch):
    monkeypatch.setenv("BBP_AUTHORITY_CREATORS", '["u-ha-admin"]')
    seed(reset=True, samples=False)
    files = {"https://v.example/a.pdf": ("application/pdf", b"%PDF-same")}
    fetch, _ = _site(files)
    calls = []
    def fake(body, ext):
        calls.append(body)
        return ["קו בניין קדמי 5 מטר"]
    with SessionLocal() as s:
        committees.import_register(s)
        c = _committee(s, "https://v.example/", [{"url": "https://v.example/a.pdf", "title": "הנחיות", "kind": "guideline"}])
        committee_docs.fetch_committee(s, c, fetch, sleep=lambda _: None, extract=fake)
        other = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == "אשקלון")).one()
        other.website_url, other.sources = "https://v.example/", [{"url": "https://v.example/a.pdf", "title": "הנחיות", "kind": "guideline"}]
        s.commit()
        committee_docs.fetch_committee(s, other, fetch, sleep=lambda _: None, extract=fake)
        assert len(calls) == 1                                       # identical bytes: extracted once
        cid = c.id
    client = TestClient(app)
    hits = client.get("/api/committees/passages", params={"q": "קו בניין"}, headers={"X-User": "u-ha-admin"}).json()
    assert {h["committee"] for h in hits} == {"חוף אשקלון", "אשקלון"} and all(h["verification"] == "UNVERIFIED" for h in hits)
    assert client.get("/api/committees/passages", params={"q": "קו"}, headers={"X-User": "u-planner"}).status_code == 403
    docs = client.get(f"/api/committees/{cid}/documents", headers={"X-User": "u-ha-admin"}).json()
    snap = docs[0]["snapshot"]
    r = client.get(f"/api/committees/snapshots/{snap['id']}/file", headers={"X-User": "u-ha-admin"})
    assert r.status_code == 200 and r.content == b"%PDF-same"
    assert client.post("/api/committees/fetch", headers={"X-User": "u-ha-engineer"}, json={}).status_code == 403
    n = client.post("/api/committees/fetch", headers={"X-User": "u-ha-admin"}, json={}).json()["queued"]
    assert n >= 2                                                    # committees with candidate sources only


def test_sandboxed_extraction():
    import pymupdf
    from app.safe_extract import extract
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "Spatial guidelines page one")
    pages = extract(d.tobytes(), ".pdf")
    assert len(pages) == 1 and "Spatial guidelines" in pages[0]
    import pytest
    with pytest.raises(ValueError):
        extract(b"%PDF-not really a pdf", ".pdf")
    assert extract(b"anything", ".exe") == []
    assert extract("שורה אחת\nשורה שתיים".encode(), ".txt") == ["שורה אחת\nשורה שתיים"]


def test_retry_failed_extraction():
    seed(reset=True, samples=False)
    files = {"https://v.example/a.pdf": ("application/pdf", b"%PDF-x")}
    fetch, _ = _site(files)
    def broken(body, ext):
        raise ValueError("boom")
    with SessionLocal() as s:
        committees.import_register(s)
        c = _committee(s, "https://v.example/", [{"url": "https://v.example/a.pdf", "title": "הנחיות", "kind": "guideline"}])
        committee_docs.fetch_committee(s, c, fetch, sleep=lambda _: None, extract=broken)
        snap = s.scalars(select(CommitteeSnapshot)).one()
        assert snap.text_status == "failed"
        out = committee_docs.retry_failed_extractions(s, extract=lambda b, e: ["טקסט"])
        assert out == {"retried": 1, "ok": 1, "still_failed": 0} and snap.text_status == "ok" and snap.pages == 1


def test_nul_bytes_are_removed():
    seed(reset=True, samples=False)
    files = {"https://v.example/a.pdf": ("application/pdf", b"%PDF-nul")}
    fetch, _ = _site(files)
    with SessionLocal() as s:
        committees.import_register(s)
        c = _committee(s, "https://v.example/", [{"url": "https://v.example/a.pdf", "title": "הנחיות", "kind": "guideline"}])
        committee_docs.fetch_committee(s, c, fetch, sleep=lambda _: None, extract=lambda b, e: ["קו\x00 בניין"])
        from app.models import CommitteePassage
        assert s.scalars(select(CommitteePassage)).one().text_he == "קו בניין"
