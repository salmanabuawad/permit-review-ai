"""The rejected-applications evaluator: route from the register's application type, committee letters and decision
wording kept out of the engine input, labels never read by `run`."""
import importlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
ER = importlib.import_module("evaluate_rejected")


def _docx(path: Path, text: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:p><w:t>{text}</w:t></w:p></w:document>")
    return path


def test_route_from_application_type():
    m = {"case_id": "CASE_1", "submission_date": "01/02/2022", "application_type": "בקשה מקוונת ללא הקלות",
         "land": [{"block": "1", "parcel": "2", "lot": "3", "plan_defining_lot": "תמא 39"}]}
    f = ER.facts_from_metadata(m)
    assert f["application_type_code"] == "81" and f["land"][0]["תוכנית קובעת מגרש"] == "תמא 39"
    assert ER.facts_from_metadata({**m, "application_type": "בקשה מקוונת כולל הקלות"})["application_type_code"] == "82"
    assert ER.facts_from_metadata({**m, "application_type": "בקשה להיתר"})["application_type_code"] is None


def test_committee_letters_and_decisions_are_not_inputs(tmp_path):
    assert ER.screen(_docx(tmp_path / "a.docx", "לכבוד המבקש, הנחיות לפרסום בקשה להקלה")) == \
        (False, "committee letter, not an applicant submission")
    assert not ER.screen(_docx(tmp_path / "b.docx", "החלטה לסרב"))[0]
    assert not ER.screen(_docx(tmp_path / "c.docx", "בקשה 20180310"))[0]
    assert ER.screen(_docx(tmp_path / "d.docx", "תצהיר מהנדס"))[0]


def test_run_refuses_a_package_with_labels_beside_it(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "01_BLIND_REVIEW").mkdir(parents=True)
    (pkg / "02_RESTRICTED_VALIDATION").mkdir()
    with pytest.raises(SystemExit, match="restricted validation"):
        ER.cmd_run(pkg)


def test_request_text_leak_excludes_the_case(tmp_path):
    case = tmp_path / "CASE_000001"
    case.mkdir()
    (case / "application_metadata.json").write_text(json.dumps({
        "case_id": "CASE_000001", "submission_date": "01/01/2020", "application_type": "בקשה מקוונת ללא הקלות",
        "request_text": "מחסן (לא מאושר-ראה החלטת ועדה)", "land": []}, ensure_ascii=False), encoding="utf-8")
    (case / "document_manifest.json").write_text("[]", encoding="utf-8")
    assert "label leak" in ER.run_case(case)["excluded"]
