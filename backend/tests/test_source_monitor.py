"""Source monitor (crawl the official rule sources) and bulk recheck — no network: the fetcher is faked."""
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed
from app.source_monitor import fetch as F
from app.source_monitor import service as S
from app.source_monitor.drafts import find_drafts

REAL_FETCH = F.fetch

INDEX = "https://www.bnei-brak.muni.il/construction-planning-policy/"
SG = "https://www.bnei-brak.muni.il/wp-content/uploads/2026/02/הנחיות-מרחביות-בהתאם-לתיקון-101-לחוק-התיכנון-והבניה.cleaned.pdf"
NEW_DOC = "https://www.bnei-brak.muni.il/wp-content/uploads/2026/05/הנחיות-מרחביות-למרפסות.pdf"
TAX = "https://www.bnei-brak.muni.il/wp-content/uploads/2026/02/צו-הארנונה-לשנת-2026.pdf"

PAGE_TEXT = [
    "15\nכללי\n. 30\nלבקשות להיתר לתוספות יצורפו תמונות של הבניין הקיים לצורך תכנון מיטבי.  30.6\n"
    "רוחב כל קורה בפרגולה לא יעלה על 20 ס\"מ ובלבד שרוחב כל הקורות זהה.\n"
    "לא יותר קירוי או סגירה כלשהיא מעל או מסביב לפרגולה.\n"
    "התכנית אושרה בשנת 2016 בהתאם לתיקון 101 לחוק.\n",
]


def make_pdf(lines: list[str]) -> bytes:
    """A text PDF whose Hebrew extracts in logical order (as the municipal PDFs do)."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_htmlbox(pymupdf.Rect(50, 50, 550, 800), "".join(f'<p dir="rtl">{ln}</p>' for ln in lines),
                        css="* {font-family: sans-serif; font-size: 11pt;}")
    return doc.tobytes(no_new_id=True)


def test_find_drafts_kinds_values_and_noise():
    ds = find_drafts(PAGE_TEXT)
    kinds = {d.kind for d in ds}
    assert kinds == {"required_document", "numeric_limit", "prohibition"}
    num = next(d for d in ds if d.kind == "numeric_limit")
    assert num.values == [{"value": 20.0, "unit": 'ס"מ', "op": "<="}]
    assert "פרגולה" in num.topics
    doc = next(d for d in ds if d.kind == "required_document")
    assert doc.section == "30.6" and doc.page == 1
    assert not any("2016" in d.text_he for d in ds)           # a year sentence without a requirement is ignored
    assert len({d.key for d in ds}) == len(ds)


def test_discover_links_keeps_relevant_documents_only():
    html = (f'<a href="{SG}">הנחיות מרחביות - כללי</a><a href="{TAX}">צו הארנונה לשנת 2026</a>'
            '<a href="https://other.example.com/x.pdf">הנחיות</a><a href="/about">אודות</a>')
    links, ignored = F.discover_links(html, INDEX, S.load_config())
    assert [ln["url"] for ln in links] == [F.canonical(SG)] and ignored == 1


class FakeWeb:
    """Serves fixed responses per URL; everything outside the plan is unreachable."""

    def __init__(self):
        self.calls: list[str] = []
        self.sg = make_pdf(["רוחב כל קורה בפרגולה לא יעלה על 20 ס\"מ.", "לבקשות יצורפו תמונות של הבניין הקיים."])
        self.new = make_pdf(["המעקה יהיה בגובה שלא יפחת מ 1.05 מ' מעל פני הרצפה."])
        self.other = make_pdf(["מסמך מדיניות."])

    def __call__(self, url, cfg, hosts, etag=None, last_modified=None):
        self.calls.append(url)
        u = F.canonical(url)
        if u == F.canonical(INDEX):
            html = (f'<html><title>מסמכי מדיניות</title><a href="{SG}">הנחיות מרחביות - כללי</a>'
                    f'<a href="{NEW_DOC}">הנחיות מרחביות למרפסות</a><a href="{TAX}">צו הארנונה</a></html>')
            return F.Fetched("ok", url, 200, "text/html", html.encode())
        if u == F.canonical(SG):
            return F.Fetched("ok", url, 200, "application/pdf", self.sg)
        if u == F.canonical(NEW_DOC):
            return F.Fetched("ok", url, 200, "application/pdf", self.new)
        if "gov.il/he/pages" in u:
            return F.Fetched("blocked", url, 403, message="האתר חוסם גישה אוטומטית (HTTP 403)")
        if "bnei-brak" in u:
            return F.Fetched("ok", url, 200, "application/pdf", self.other)
        return F.Fetched("unreachable", url, message="האתר אינו זמין מהשרת")


@pytest.fixture(scope="module")
def env():
    seed(reset=True, samples=False)
    web = FakeWeb()
    mp = pytest.MonkeyPatch()
    mp.setattr(F, "fetch", web)
    fast = {**S.load_config(), "delay_between_requests_s": 0}
    mp.setattr(S, "load_config", lambda: fast)
    with TestClient(app) as c:
        yield c, web
    mp.undo()


ENG = {"X-User": "u-engineer"}


def docs_by_url(c):
    return {d["url"]: d for d in c.get("/api/source-monitor", headers=ENG).json()["documents"]}


def test_crawl_permissions(env):
    c, _ = env
    assert c.post("/api/source-monitor/crawl?wait=true", headers={"X-User": "u-reviewer"}).status_code == 403


def test_first_crawl_fetches_versions_and_drafts(env):
    c, web = env
    r = c.post("/api/source-monitor/crawl?wait=true", headers=ENG)
    assert r.status_code == 200, r.text
    crawl = r.json()
    assert crawl["status"] == "done", crawl["summary"]
    sm = crawl["summary"]
    assert sm["blocked"] >= 1 and sm["new"] >= 3 and sm["drafts_new"] >= 3
    assert F.canonical(TAX) not in [F.canonical(u) for u in web.calls]          # irrelevant link never fetched
    d = docs_by_url(c)
    page = d[F.canonical(INDEX)]
    assert page["kind"] == "page" and page["links"] == 2 and page["source_id"] is None
    sg = d[F.canonical(SG)]
    assert sg["source_id"] == "BB-SG-2016" and sg["change_state"] == "new" and sg["page_count"] == 1 and sg["has_file"]
    new = d[F.canonical(NEW_DOC)]
    assert new["source_id"] is None and new["discovered_from"] == F.canonical(INDEX)   # not in the register: flagged
    blocked = [x for x in d.values() if x["fetch_status"] == "blocked"]
    assert blocked and all("403" in x["message"] for x in blocked)
    drafts = c.get(f"/api/source-monitor/documents/{sg['id']}/drafts", headers=ENG).json()
    assert {x["kind"] for x in drafts} == {"numeric_limit", "required_document"}
    assert c.get(f"/api/source-monitor/documents/{sg['id']}/file", headers=ENG).content[:4] == b"%PDF"
    assert c.get(f"/api/source-monitor/documents/{sg['id']}/page/1.png", headers=ENG).content[:4] == b"\x89PNG"


def test_second_crawl_is_unchanged(env):
    c, _ = env
    sm = c.post("/api/source-monitor/crawl?wait=true", headers=ENG).json()["summary"]
    assert sm["new"] == 0 and sm["changed"] == 0 and sm["drafts_new"] == 0 and sm["unchanged"] >= 3


def test_changed_document_is_flagged_and_old_clauses_superseded(env):
    c, web = env
    sg = docs_by_url(c)[F.canonical(SG)]
    assert c.post(f"/api/source-monitor/documents/{sg['id']}/acknowledge", headers=ENG).json()["ok"]
    web.sg = make_pdf(["רוחב כל קורה בפרגולה לא יעלה על 25 ס\"מ."])
    sm = c.post("/api/source-monitor/crawl?wait=true", headers=ENG).json()["summary"]
    assert sm["changed"] == 1 and sm["drafts_new"] == 1
    sg = docs_by_url(c)[F.canonical(SG)]
    assert sg["change_state"] == "changed" and sg["acknowledged"] is False
    drafts = c.get(f"/api/source-monitor/documents/{sg['id']}/drafts", headers=ENG).json()
    by_status = {x["status"] for x in drafts}
    assert "superseded" in by_status and "open" in by_status
    assert any(v["value"] == 25.0 for x in drafts if x["status"] == "open" for v in x["values"])


def test_draft_decisions_and_yaml_export(env):
    c, _ = env
    sg = docs_by_url(c)[F.canonical(SG)]
    draft = next(x for x in c.get(f"/api/source-monitor/documents/{sg['id']}/drafts", headers=ENG).json() if x["status"] == "open")
    assert c.post(f"/api/source-monitor/drafts/{draft['id']}", json={"status": "bogus"}, headers=ENG).status_code == 422
    assert c.post(f"/api/source-monitor/drafts/{draft['id']}", json={"status": "for_authoring"}, headers=ENG).json()["ok"]
    y = c.get("/api/source-monitor/drafts.yaml", headers=ENG)
    assert y.status_code == 200 and "NOT loaded by the rule engine" in y.text
    assert f"DRAFT-BB-SG-2016-{draft['id']}" in y.text and "review_state: DRAFT" in y.text and "threshold: 25.0" in y.text


def test_manual_upload_for_blocked_source(env):
    c, _ = env
    blocked = next(x for x in docs_by_url(c).values() if x["fetch_status"] == "blocked")
    pdf = make_pdf(["לבקשה יש לצרף צילום של הבניין הקיים."])
    r = c.post("/api/source-monitor/upload", headers=ENG, data={"document_id": str(blocked["id"])},
               files={"file": ("steps.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["has_file"] and r.json()["page_count"] == 1
    r2 = c.post("/api/source-monitor/upload", headers=ENG, data={"source_id": "REG-RISHUY-2016"},
                files={"file": ("regs.pdf", pdf, "application/pdf")})
    assert r2.status_code == 200 and r2.json()["kind"] == "manual" and r2.json()["source_id"] == "REG-RISHUY-2016"
    assert c.post("/api/source-monitor/upload", headers=ENG, data={"source_id": "NOPE"},
                  files={"file": ("x.pdf", pdf, "application/pdf")}).status_code == 404


def test_fetch_refuses_hosts_outside_register():
    res = REAL_FETCH("https://evil.example.com/x.pdf", {"user_agent": "t", "timeout_s": 5, "max_bytes": 10}, {"www.bnei-brak.muni.il"})
    assert res.status == "error"


# ------------------------------------------------------------------ bulk recheck

def test_bulk_recheck_selected_and_all():
    seed(reset=True)                                        # demo tenant with sample cases
    with TestClient(app) as c:
        R = {"X-User": "u-reviewer"}
        cases = c.get("/api/cases", headers=R).json()
        assert c.post("/api/cases/recheck", json={"case_ids": None}, headers={"X-User": "u-planner"}).status_code == 403
        assert c.post("/api/cases/recheck", json={"case_ids": []}, headers=R).status_code == 422
        one = c.post("/api/cases/recheck", json={"case_ids": [cases[0]["id"]]}, headers=R).json()
        assert one["requested"] == 1 and len(one["done"]) + len(one["skipped"]) == 1
        before = {x["id"]: (x["last_run"] or {}).get("version", 0) for x in cases}
        allr = c.post("/api/cases/recheck", json={"case_ids": None}, headers=R).json()
        assert allr["requested"] == len(cases) and not allr["failed"]
        after = {x["id"]: (x["last_run"] or {}).get("version", 0) for x in c.get("/api/cases", headers=R).json()}
        for d in allr["done"]:
            assert after[d["case_id"]] > before[d["case_id"]]
        assert all(s["reason"] for s in allr["skipped"])
        # another tenant's case id is simply not found in this tenant
        other = c.post("/api/cases/recheck", json={"case_ids": ["not-a-case"]}, headers=R).json()
        assert other["requested"] == 0
