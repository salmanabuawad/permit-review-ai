"""Import pipeline on synthetic files: form extraction, multi-request PDF split, ZIP with folders
and a request list, ZIP safety, metadata-only uploads, and the analyze/commit API."""
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import batch_import as bi
from app.ai.gateway import AIGateway
from app.intake.pipeline import analyze_package
from app.main import app
from app.seed import seed

IMP = Path(__file__).resolve().parents[2] / "fixtures" / "import"
GW = AIGateway()


def run(files):
    return analyze_package(files, lambda t, d, p: GW.route(t, d, p))


# ---------------------------------------------------------------- application-form field extraction
def test_extract_fields_logical_text():
    text = ("מספר בקשה: 2026-0042\nגוש: 6188 חלקה: 12\nכתובת: רחוב הדוגמה 5\n"
            "מהות הבקשה: הרחבת דירה בקומה ב׳\nתכניות חלות: בב/105/ג, בב/מק/105/אגפים\nתאריך מדידה: 01/09/2026\n"
            "שם המבקש: ישראל ישראלי ת.ז. 012345678")
    f, s = bi.extract_fields(text, "form.pdf", 1)
    assert f["case_number"] == "2026-0042" and f["gush"] == "6188" and f["helka"] == "12"
    assert f["address"] == "רחוב הדוגמה 5" and f["permit_type"] == "addition_extension"
    assert f["survey_map_date"] == "2026-09-01"
    assert not any("012345678" in str(v) or "ישראלי" in str(v) for v in f.values())   # no applicant PII


def test_extract_fields_reversed_mixed_line():
    f, s = bi.extract_fields("( )הדגמה000 : חלקה0000 :גוש", "x.pdf", 1)
    assert f["gush"] == "0000" and f["helka"] == "000"
    assert "במהופך" in s["helka"].method and s["helka"].confidence < 0.9


# ---------------------------------------------------------------- formats
def test_multi_request_form_pdf_is_split():
    res, blobs = run([("two_requests.pdf", (IMP / "two_requests.pdf").read_bytes())])
    apps = res["applications"]
    assert sorted(a["application_number"] for a in apps) == ["T-2026-001", "T-2026-002"]
    assert res["documents"][0]["classification"]["doc_class"] == "permit_application"
    a1 = next(a for a in apps if a["application_number"] == "T-2026-001")
    assert a1["fields"]["helka"]["value"] == "11" and a1["fields"]["address"]["value"] == "רחוב הבדיקה 1"
    import pymupdf
    pages = sorted(pymupdf.open(stream=blobs[a["documents"][0]["ref"]], filetype="pdf").page_count for a in apps)
    assert pages == [1, 2]                                   # the annex page stays with request 1


def test_zip_with_folders_and_request_list():
    res, _ = run([("two_requests.zip", (IMP / "two_requests.zip").read_bytes())])
    assert res["counts"]["applications"] == 2 and res["counts"]["documents_metadata"] == 1
    a = next(x for x in res["applications"] if x["application_number"] == "Z-2026-010")
    kinds = {d["doc_type"] for d in a["documents"]}
    assert {"application_form", "survey_map", "architectural_plan", "area_table"} <= kinds   # grouped by folder
    assert a["fields"]["gush"]["value"] == "9999"


def test_request_list_alone_creates_no_application():
    csv_bytes = "מספר בקשה,גוש,חלקה,קובץ\n555,9999,1,missing.pdf\n".encode("utf-8")
    res, _ = run([("index.csv", csv_bytes)])
    assert res["counts"]["applications"] == 0 and res["counts"]["documents_metadata"] == 1
    assert any("ללא מסמך" in w for w in res["warnings"])


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in entries.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_zip_slip_rejected():
    with pytest.raises(bi.ImportError_):
        run([("evil.zip", _zip({"../../etc/passwd.pdf": b"%PDF-1.4"}))])


def test_zip_bomb_rejected():
    with pytest.raises(bi.ImportError_):
        run([("bomb.zip", _zip({"REQ/a.pdf": b"%PDF" + b"0" * 5_000_000}))])


def test_bad_files_do_not_stop_the_batch():
    res, _ = run([("x.zip", _zip({"R/inner.zip": b"PK", "R/photo.jpg": b"\xff\xd8", "R/broken.pdf": b"%PDF-1.4 broken",
                                  "R/two.pdf": (IMP / "two_requests.pdf").read_bytes()}))])
    st = {d["name"]: d["status"] for d in res["documents"]}
    assert st["photo.jpg"] == "skipped" and st["broken.pdf"] == "failed"
    assert any("מקונן" in w for w in res["warnings"])
    assert res["counts"]["applications"] == 2                 # the valid PDF was still processed


def test_nested_zip_opened_one_level():
    """An external body's response: a ZIP of PDFs inside the attachment ZIP is opened; a third level is skipped."""
    inner = _zip({"Response.pdf": b"%PDF-1.4 r", "deeper.zip": _zip({"x.pdf": b"%PDF-1.4"})})
    out, warnings = bi.unpack([("response.zip", _zip({"Response_1.zip": inner}))])
    assert [n for _, n, _ in out] == ["Response.pdf"]
    assert any("מקונן" in w and "deeper.zip" in w for w in warnings)


# ---------------------------------------------------------------- API
@pytest.fixture(scope="module")
def client():
    seed(reset=True, samples=False)
    with TestClient(app) as c:
        yield c


SEC = {"X-User": "u-secretary"}


def analyze(client, name, data=None):
    r = client.post("/api/import/analyze", headers=SEC, files=[("files", (name, data or (IMP / name).read_bytes()))])
    assert r.status_code == 200, r.text
    return r.json()


def accept_all(preview, **fields):
    return [{"key": a["key"], "include": True, "fields": dict(fields),
             "documents": [{"ref": d["ref"], "include": True} for d in a["documents"]]} for a in preview["applications"]]


def test_import_flow_and_idempotency(client):
    pv = analyze(client, "two_requests.zip")
    assert client.get("/api/cases", headers=SEC).json() == []              # analyze creates nothing
    r = client.post("/api/import/commit", headers=SEC, json={"token": pv["token"], "applications": accept_all(pv)})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["created"] == 2 and r.json()["summary"]["metadata_files"] == 1
    again = client.post("/api/import/commit", headers=SEC, json={"token": pv["token"], "applications": accept_all(pv)})
    assert again.status_code == 404                                          # a batch commits once
    pv2 = analyze(client, "two_requests.zip")
    assert pv2["counts"]["applications_duplicate"] == 2
    r2 = client.post("/api/import/commit", headers=SEC, json={"token": pv2["token"], "applications": accept_all(pv2)}).json()
    assert r2["summary"]["created"] == 0 and r2["summary"]["duplicate"] == 2
    assert len(client.get("/api/cases", headers=SEC).json()) == 2
    batches = client.get("/api/import/batches", headers=SEC).json()
    assert batches[0]["status"] == "committed" and batches[0]["summary"]["duplicate"] == 2


def test_import_page_preview_and_permissions(client):
    pv = analyze(client, "two_requests.pdf")
    ref = pv["applications"][0]["documents"][0]["ref"]
    img = client.get(f"/api/import/{pv['token']}/page/{ref}/1.png", headers=SEC)
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get(f"/api/import/{pv['token']}/page/../1.png", headers=SEC).status_code == 404
    assert client.post("/api/import/analyze", headers={"X-User": "u-planner"},
                       files=[("files", ("a.pdf", (IMP / "two_requests.pdf").read_bytes()))]).status_code == 403


def test_duplicate_numbers_inside_one_commit_rejected(client):
    pv = analyze(client, "two_requests.pdf")
    apps = accept_all(pv, application_number="SAME-1")
    r = client.post("/api/import/commit", headers=SEC, json={"token": pv["token"], "applications": apps})
    assert r.status_code == 422
