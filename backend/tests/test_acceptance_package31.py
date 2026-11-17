"""Acceptance tests on the real 2016 Bnei Brak committee-protocol package (31 applications).

The package contains personal names from a historic protocol, so it is not stored in the repo.
Set BBP_TEST_PACKAGE_31 (ZIP) and BBP_TEST_PROTOCOL (full protocol PDF), or keep the default
Downloads paths; the tests are skipped when the files are not present.
"""
import csv
import io
import os
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.intake import text as T
from app.main import app
from app.models import InferenceCost
from app.seed import seed

PKG = Path(os.environ.get("BBP_TEST_PACKAGE_31", r"C:\Users\A\Downloads\bnei_brak_31_permit_applications.zip"))
PROTOCOL = Path(os.environ.get("BBP_TEST_PROTOCOL", r"C:\Users\A\Downloads\samples.pdf"))
pytestmark = pytest.mark.skipif(not PKG.exists(), reason=f"real package not found at {PKG}")
H = {"X-User": "u-secretary"}


def index_rows():
    with zipfile.ZipFile(PKG) as z:
        text = z.read("index.csv").decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def do_import(c, name, data):
    pv = c.post("/api/import/analyze", headers=H, files=[("files", (name, data))])
    assert pv.status_code == 200, pv.text
    pv = pv.json()
    apps = [{"key": a["key"], "include": True, "fields": {}, "documents": [{"ref": d["ref"], "include": True} for d in a["documents"]]}
            for a in pv["applications"]]
    r = c.post("/api/import/commit", headers=H, json={"token": pv["token"], "applications": apps, "run_checks": False})
    assert r.status_code == 200, r.text
    return pv, r.json()


@pytest.fixture(scope="module")
def state():
    seed(reset=True, samples=False)
    with TestClient(app) as c:
        pv1, r1 = do_import(c, PKG.name, PKG.read_bytes())
        pv2, r2 = do_import(c, PKG.name, PKG.read_bytes())
        cases = {x["case_number"]: x for x in c.get("/api/cases", headers=H).json()}
        details = {n: c.get(f"/api/cases/{x['id']}", headers=H).json() for n, x in cases.items()}
        extracted = {n: c.get(f"/api/cases/{x['id']}/extracted", headers=H).json() for n, x in cases.items()}
        yield {"pv1": pv1, "r1": r1, "pv2": pv2, "r2": r2, "cases": cases, "details": details, "extracted": extracted, "client": c}


# 1 ---------------------------------------------------------------------------------------------
def test_01_imports_exactly_31_applications(state):
    assert state["r1"]["summary"]["created"] == 31
    assert state["r1"]["summary"]["failed"] == 0
    assert len(state["cases"]) == 31
    classes = Counter((d["classification"] or {}).get("doc_class") for d in state["pv1"]["documents"])
    assert classes["committee_protocol"] == 31                       # classified by content


# 2 ---------------------------------------------------------------------------------------------
def test_02_index_files_are_metadata_not_applications(state):
    docs = {d["name"]: d for d in state["pv1"]["documents"]}
    for name in ("index.csv", "index.json", "index.html"):
        assert docs[name]["status"] == "metadata"
        assert docs[name]["classification"]["doc_class"] == "metadata_index"
    assert state["r1"]["summary"]["metadata_files"] == 3
    assert not any(f["filename"].startswith("index.") for d in state["details"].values() for f in d["files"])


# 3 ---------------------------------------------------------------------------------------------
def test_03_each_pdf_matched_to_its_application(state):
    rows = index_rows()
    assert len(rows) == 31
    for r in rows:
        number, file = r["מספר בקשה"], r["קובץ"]
        case = state["details"][number]
        assert [f["filename"] for f in case["files"]] == [file], number
        ex = {f["field"]: f for f in state["extracted"][number]["fields"]}
        assert ex["application_number"]["value"] == number            # the number was read from the PDF itself
        assert ex["application_number"]["source"]["original_page"] == int(r["עמוד התחלה במקור"])
        assert ex["gush"]["value"] == r["גוש"] and ex["helka"]["value"] == r["חלקה"], number


# 4 ---------------------------------------------------------------------------------------------
def test_04_bialik_25_application_201600156(state):
    ex = state["extracted"]["201600156"]
    f = {x["field"]: x["value"] for x in ex["fields"]}
    assert f["application_number"] == "201600156"
    assert f["building_file_number"] == "61950349"
    assert f["address"] == "ביאליק 25"
    assert (f["gush"], f["helka"]) == ("6195", "349")
    assert f["zone"] == "אזור מגורים ג"
    assert f["application_type"] == "בקשה להיתר"
    assert "תוספת סוכה לדירה בקומה ב'" in f["description"] and "חדרי גג" in f["description"]
    assert f["permit_type"] == "roof_room_addition"
    assert "105" in f["applicable_plans"]
    assert "אי נסיגה בקומת הגג בצד צפון" in f["deviations"]
    areas = {(a["value"]["label"], a["value"]["value_m2"]) for a in ex["areas"]}
    assert {("חדרי גג", 35.0), ("מדרגות", 5.0), ("סוכה", 7.55), ("מרפסת גג", 13.37)} <= areas
    assert any(a["value"]["value_m2"] == 60.92 and a["value"]["status"] == "existing" for a in ex["areas"])
    src = next(x for x in ex["fields"] if x["field"] == "address")["source"]
    assert src["file"] == "11_201600156.pdf" and src["page"] == 1 and src["original_page"] == 32
    case = state["details"]["201600156"]
    assert case["permit_type"] == "roof_room_addition" and case["gush"] == "6195"


# 5 ---------------------------------------------------------------------------------------------
def test_05_committee_comments_and_decisions(state):
    ex = state["extracted"]["201600156"]
    by_dept = Counter(c["department_he"] for c in ex["comments"])
    assert by_dept == Counter({"מחלקת רישוי": 8, "אדריכל חזות העיר": 3, "מהנדס העיר": 2, "אדריכל רישוי": 2})
    texts = [c["text"] for c in ex["comments"]]
    assert "לסמן גובה מעקה." in texts and "יש להתייחס לניקוז הגגות של חדרי הגג." in texts
    d = ex["decisions"][0]
    assert d["outcome"] == "approved_with_conditions" and d["meeting_number"] == "20160084" and d["meeting_date"] == "2016-07-25"
    assert d["text"].startswith("לאשר בהערות מח' רשוי") and "היתר יוצא ע\"ג תכנית מתוקנת" in d["text"]
    assert d["source"]["original_page"] in (32, 33)
    # every application has a decision, and it agrees with the decision excerpt in the index
    rows = {r["מספר בקשה"]: r for r in index_rows()}
    agree = 0
    for n, e in state["extracted"].items():
        assert e["decisions"], n
        assert e["comments"], n
        dec = T.compact(e["decisions"][0]["text"])
        exc = T.compact(rows[n]["תחילת נוסח ההחלטה (לבדיקה במקור)"])
        windows = [exc[i:i + 10] for i in range(0, max(len(exc) - 10, 1), 10)]
        agree += sum(w in dec for w in windows) / len(windows) >= 0.5
    assert agree >= 29, f"only {agree}/31 decisions agree with the index excerpt"


# 6 ---------------------------------------------------------------------------------------------
def test_06_reimport_creates_no_duplicates(state):
    assert state["pv2"]["counts"]["applications_duplicate"] == 31
    assert state["r2"]["summary"]["created"] == 0 and state["r2"]["summary"]["duplicate"] == 31
    assert len(state["client"].get("/api/cases", headers=H).json()) == 31


def test_06b_full_protocol_adds_documents_not_applications(state):
    if not PROTOCOL.exists():
        pytest.skip("full protocol PDF not available")
    pv, r = do_import(state["client"], PROTOCOL.name, PROTOCOL.read_bytes())
    assert pv["counts"]["applications"] == 31 and pv["counts"]["planning_items"] == 4
    assert r["summary"]["created"] == 0 and r["summary"]["updated"] == 31
    rows = {x["מספר בקשה"]: (int(x["עמוד התחלה במקור"]), int(x["עמוד סיום במקור"])) for x in index_rows()}
    got = {a["application_number"]: tuple(a["documents"][0]["origin"]["pages"]) for a in pv["applications"]}
    assert got == rows                                                 # item page ranges == index page ranges
    assert len(state["client"].get("/api/cases", headers=H).json()) == 31


# 7 ---------------------------------------------------------------------------------------------
def test_07_ai_execution_log_records_local_provider(state):
    with SessionLocal() as s:
        rows = s.query(InferenceCost).filter(InferenceCost.task == "Extraction").all()
    assert rows and {r.provider_id for r in rows} == {"local_rules"}    # case documents stayed on-prem
    assert {r.outcome for r in rows} == {"OK"}
