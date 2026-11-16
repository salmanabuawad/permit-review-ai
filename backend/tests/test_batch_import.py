"""Batch import: field extraction, multi-request PDF split, ZIP + request list, ZIP safety, API flow."""
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import batch_import as bi
from app.main import app
from app.seed import seed

IMP = Path(__file__).resolve().parents[2] / "fixtures" / "import"


# ---------------------------------------------------------------- extraction
def test_extract_fields_logical_text():
    text = ("מספר בקשה: 2026-0042\nגוש: 6188 חלקה: 12\nכתובת: רחוב הדוגמה 5\n"
            "מהות הבקשה: הרחבת דירה בקומה ב׳\nתכניות חלות: בב/105/ג, בב/מק/105/אגפים\nתאריך מדידה: 01/09/2026\n"
            "שם המבקש: ישראל ישראלי ת.ז. 012345678")
    f, s = bi.extract_fields(text, "form.pdf", 1)
    assert f["case_number"] == "2026-0042" and f["gush"] == "6188" and f["helka"] == "12"
    assert f["address"] == "רחוב הדוגמה 5" and f["permit_type"] == "addition_extension"
    assert f["applicable_plans"] == ["בב/105/ג", "בב/מק/105/אגפים"]
    assert f["survey_map_date"] == "2026-09-01"
    assert s["gush"].page == 1 and s["gush"].file == "form.pdf"
    assert not any("012345678" in str(v) or "ישראלי" in str(v) for v in f.values())   # no applicant PII


def test_extract_fields_reversed_mixed_line():
    # exact shape PyMuPDF returns for a visual-order line "גוש: 0000 חלקה: 000"
    f, s = bi.extract_fields("( )הדגמה000 : חלקה0000 :גוש", "x.pdf", 1)
    assert f["gush"] == "0000" and f["helka"] == "000"
    assert "במהופך" in s["helka"].method and s["helka"].confidence < 0.9


@pytest.mark.parametrize("text,expected", [
    ("בקשה לחדר יציאה לגג ותוספת", "roof_room_addition"),
    ("מרפסת סוכה בקומה ג׳", "addition_sukkah"),
    ("סגירת מרפסת", "addition_balcony"),
    ("הרחבת דירה", "addition_extension"),
    ("שינוי שימוש", None),
])
def test_infer_permit_type(text, expected):
    assert bi.infer_permit_type(text) == expected


# ---------------------------------------------------------------- formats
def test_multi_request_pdf_is_split():
    drafts, blobs, _ = bi.analyze([("two_requests.pdf", (IMP / "two_requests.pdf").read_bytes())])
    assert [d.fields["case_number"] for d in drafts] == ["T-2026-001", "T-2026-002"]
    assert [d.fields["helka"] for d in drafts] == ["11", "12"]
    assert drafts[0].fields["address"] == "רחוב הבדיקה 1"
    assert [d.fields["permit_type"] for d in drafts] == ["addition_extension", "addition_sukkah"]
    import pymupdf
    pages = [pymupdf.open(stream=blobs[d.files[0]["ref"]], filetype="pdf").page_count for d in drafts]
    assert pages == [2, 1]                          # the annex page stays with request 1


def test_zip_with_folders_and_request_list():
    drafts, _, warnings = bi.analyze([("two_requests.zip", (IMP / "two_requests.zip").read_bytes())])
    assert not warnings and len(drafts) == 2
    a = next(d for d in drafts if d.fields["case_number"] == "Z-2026-010")
    assert a.fields["permit_type"] == "addition_extension" and a.fields["applicable_plans"] == ["DEMO/1"]
    assert a.sources["case_number"]["method"].startswith("רשימת בקשות")          # list wins over extraction
    assert {f["doc_type"] for f in a.files} == {"application_form", "survey_map", "architectural_plan", "area_table"}
    b = next(d for d in drafts if d.fields["case_number"] == "Z-2026-011")
    assert b.fields["permit_type"] == "roof_room_addition"


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in entries.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_zip_slip_rejected():
    with pytest.raises(bi.ImportError_):
        bi.analyze([("evil.zip", _zip({"../../etc/passwd.pdf": b"%PDF-1.4"}))])


def test_zip_bomb_rejected():
    with pytest.raises(bi.ImportError_):
        bi.analyze([("bomb.zip", _zip({"REQ/a.pdf": b"%PDF" + b"0" * 5_000_000}))])


def test_nested_zip_and_unsupported_skipped():
    drafts, _, warnings = bi.analyze([("x.zip", _zip({"R/inner.zip": b"PK", "R/photo.jpg": b"\xff\xd8"}))])
    assert any("מקונן" in w for w in warnings) and any("לא נתמך" in w for w in warnings)


# ---------------------------------------------------------------- API
@pytest.fixture(scope="module")
def client():
    seed(reset=True, samples=False)
    with TestClient(app) as c:
        yield c


SEC = {"X-User": "u-secretary"}


def analyze(client, name):
    r = client.post("/api/import/analyze", headers=SEC, files=[("files", (name, (IMP / name).read_bytes()))])
    assert r.status_code == 200, r.text
    return r.json()


def as_requests(preview):
    return [{"key": d["key"], "include": True, "fields": d["fields"],
             "files": [{"ref": f["ref"], "doc_type": f["doc_type"]} for f in d["files"]]} for d in preview["drafts"]]


def test_import_flow_creates_cases_with_files_and_runs(client):
    prev = analyze(client, "two_requests.zip")
    assert client.get("/api/cases", headers=SEC).json() == []          # analyze creates nothing
    r = client.post("/api/import/commit", headers=SEC, json={"token": prev["token"], "requests": as_requests(prev)})
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert {c["case_number"] for c in created} == {"Z-2026-010", "Z-2026-011"}
    assert all(c["run"] for c in created) and sum(c["files"] for c in created) == 6
    case = client.get(f"/api/cases/{created[0]['id']}", headers=SEC).json()
    assert case["gush"] == "9999" and case["files"]
    audit = client.get("/api/audit", headers={"X-User": "u-admin"}).json()
    ev = next(e for e in audit["events"] if e["action"] == "case.create" and e["detail"].get("source") == "import")
    assert ev["detail"]["field_sources"]                                  # provenance kept in the audit log
    # token is single-use
    again = client.post("/api/import/commit", headers=SEC, json={"token": prev["token"], "requests": as_requests(prev)})
    assert again.status_code == 404


def test_import_rejects_duplicates_and_missing_type(client):
    prev = analyze(client, "two_requests.zip")                             # Z-2026-010/011 already exist
    assert all(any("כבר קיים" in w for w in d["warnings"]) for d in prev["drafts"])
    r = client.post("/api/import/commit", headers=SEC, json={"token": prev["token"], "requests": as_requests(prev)})
    assert r.status_code == 422 and "כבר קיים" in r.json()["detail"]
    reqs = as_requests(prev)
    for q in reqs:
        q["fields"]["case_number"] = q["fields"]["case_number"] + "-B"
    reqs[0]["fields"]["permit_type"] = None
    r = client.post("/api/import/commit", headers=SEC, json={"token": prev["token"], "requests": reqs})
    assert r.status_code == 422 and "סוג בקשה" in r.json()["detail"]


def test_import_pdf_split_end_to_end_and_permissions(client):
    assert client.post("/api/import/analyze", headers={"X-User": "u-planner"},
                       files=[("files", ("a.pdf", (IMP / "two_requests.pdf").read_bytes()))]).status_code == 403
    prev = analyze(client, "two_requests.pdf")
    reqs = as_requests(prev)
    r = client.post("/api/import/commit", headers=SEC, json={"token": prev["token"], "requests": reqs, "run_checks": False})
    assert r.status_code == 200
    nums = {c["case_number"] for c in r.json()["created"]}
    assert nums == {"T-2026-001", "T-2026-002"}
    assert all(c["run"] is None for c in r.json()["created"])
