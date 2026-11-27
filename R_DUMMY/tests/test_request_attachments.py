"""Uploading a request form downloads the files it links to before analysis (intake/attachments.py)."""
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.intake import attachments as A
from app.main import app
from app.seed import seed

API = "https://p-api.rishuybniya.moin.gov.il/api/FormDownload/DownloadAttachment?hash={}&docName={}"


def pdf_with_links(text: str, urls: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    for i, u in enumerate(urls):
        page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 100 + 20 * i, 300, 115 + 20 * i), "uri": u})
    return doc.tobytes()


INFO = pdf_with_links("permit info", [API.format("c", "rami.pdf"), "https://www.gov.il/he/departments/guides/x"])
FORM = pdf_with_links("request 10000612352-1", [
    API.format("a", "survey.dwfx"), API.format("b", "info.pdf"), API.format("b", "info.pdf"),   # same link twice
    API.format("d", "copy.pdf"), API.format("e", "gone.pdf"),
    "https://evil.example.com/api/FormDownload/x", "http://p-api.rishuybniya.moin.gov.il/api/FormDownload/plain",
    "https://p-api.rishuybniya.moin.gov.il/other/path"])
FILES = {"a": b"PK\x03\x04dwfx", "b": INFO, "c": b"%PDF-1.4 rami", "d": FORM}


def fake_fetch(calls):
    def fetch(url, limit):
        calls.append(url)
        q = A.urllib.parse.parse_qs(A.urllib.parse.urlparse(url).query)
        key = q["hash"][0]
        if key not in FILES:
            raise A.urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return q["docName"][0], FILES[key]
    return fetch


def test_only_the_download_api_is_followed():
    assert A.is_download_link(API.format("x", "a.pdf"))
    for url in ("https://evil.example.com/api/FormDownload/x", "http://p-api.rishuybniya.moin.gov.il/api/FormDownload/x",
                "https://p-api.rishuybniya.moin.gov.il/other", "https://p-api.rishuybniya.moin.gov.il.evil.com/api/FormDownload/x",
                "file:///etc/passwd"):
        assert not A.is_download_link(url), url


def test_expand_downloads_recursively_once_each():
    calls = []
    files, exp = A.expand([("10000612352.pdf", FORM)], fetch=fake_fetch(calls))
    names = [n for n, _ in files]
    assert names == ["10000612352.pdf", "survey.dwfx", "info.pdf", "rami.pdf"]      # rami.pdf: linked from info.pdf
    assert len(calls) == len(set(calls)) == 5                                       # each link fetched once
    assert [d["name"] for d in exp.duplicates] == ["copy.pdf"]                      # same bytes as the upload
    assert [f["name"] for f in exp.failed] == ["gone.pdf"]
    assert exp.other_links == 4                                                     # gov.il page + 3 refused links
    assert any("הורדו 3 קבצים" in w for w in exp.warnings_he())


def test_package_size_budget(monkeypatch):
    monkeypatch.setattr(A.settings.__class__, "max_package_mb", property(lambda self: 0), raising=False)
    files, exp = A.expand([("f.pdf", FORM)], fetch=fake_fetch([]))
    assert files == [("f.pdf", FORM)] and exp.truncated


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def test_analyze_includes_linked_files(client, monkeypatch):
    monkeypatch.setattr(A, "_fetch", fake_fetch([]))
    r = client.post("/api/import/analyze", headers={"X-User": "u-secretary"},
                    files=[("files", ("10000612352.pdf", FORM, "application/pdf"))])
    assert r.status_code == 200, r.text
    pv = r.json()
    assert {d["name"] for d in pv["documents"]} >= {"10000612352.pdf", "survey.dwfx", "info.pdf", "rami.pdf"}
    assert [d["name"] for d in pv["linked_files"]["downloaded"]] == ["survey.dwfx", "info.pdf", "rami.pdf"]
    assert any("לא ניתן להוריד את 'gone.pdf'" in w for w in pv["warnings"])


def test_linked_files_join_the_request_that_links_them():
    exp = A.Expansion(downloaded=[{"name": "info.pdf", "size": 1, "from": "form.pdf"},
                                  {"name": "rami.pdf", "size": 1, "from": "info.pdf"},
                                  {"name": "plan.dwfx", "size": 1, "from": "form.pdf"}])
    doc = lambda ref, name, status="ok", dt="other": {"ref": ref, "name": name, "status": status, "doc_type": dt,  # noqa: E731
                                                      "classification": {"doc_class": "x"}, "sha256": ref, "messages": [],
                                                      "applications": []}
    pv = {"documents": [doc("f", "form.pdf", dt="application_form"), doc("i", "info.pdf", dt="application_form"),
                        doc("r", "rami.pdf", "unassigned"), doc("p", "plan.dwfx", "unassigned"),
                        doc("o", "other_form.pdf", dt="application_form")],
          "applications": [
              {"key": "1", "application_number": "10000612352-1", "status": "new",
               "documents": [{"ref": "f", "name": "form.pdf", "doc_type": "application_form", "origin": None}]},
              {"key": "2", "application_number": "10000583665-2", "status": "new",       # the info file, misread as a request
               "documents": [{"ref": "i2", "name": "info_p9-11.pdf", "doc_type": "application_form",
                              "origin": {"file": "info.pdf"}}]},
              {"key": "3", "application_number": "999", "status": "new",                # a separate uploaded request
               "documents": [{"ref": "o", "name": "other_form.pdf", "doc_type": "application_form", "origin": None}]}],
          "counts": {}, "warnings": []}
    A.group_linked(pv, ["form.pdf", "other_form.pdf"], exp)
    assert [a["application_number"] for a in pv["applications"]] == ["10000612352-1", "999"]
    names = [d["name"] for d in pv["applications"][0]["documents"]]
    assert names == ["form.pdf", "info.pdf", "rami.pdf", "plan.dwfx"]
    assert pv["counts"]["documents_unassigned"] == 0 and pv["counts"]["applications"] == 2
    assert [d["name"] for d in pv["applications"][1]["documents"]] == ["other_form.pdf"]


def test_requests_in_the_uploads_are_never_merged():
    """Two requests inside one uploaded PDF stay two, even when files were downloaded for the package."""
    exp = A.Expansion(downloaded=[{"name": "x.pdf", "size": 1, "from": "two.pdf"}])
    pv = {"documents": [], "counts": {}, "warnings": [], "applications": [
        {"key": k, "application_number": n, "status": "new",
         "documents": [{"ref": k, "name": f"two_p{k}.pdf", "doc_type": "application_form", "origin": {"file": "two.pdf"}}]}
        for k, n in (("1", "A-1"), ("2", "A-2"))]}
    A.group_linked(pv, ["two.pdf"], exp)
    assert [a["application_number"] for a in pv["applications"]] == ["A-1", "A-2"]
