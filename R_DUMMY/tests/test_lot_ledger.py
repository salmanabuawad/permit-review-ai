"""Lot ledger (scripts/import_lot_ledger.py) and the checks that compare a request with it."""
import importlib.util
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.rules import evidence as E

from .test_evidence import pdf

spec = importlib.util.spec_from_file_location("ledger", Path(__file__).resolve().parents[2] / "scripts" / "import_lot_ledger.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def test_roles_and_buildings():
    assert L.role({"essence": "עבודות פיתוח ותשתיות, ותכנית בינוי"}) == "infrastructure"
    assert L.role({"essence": "הסדרה בדיעבד בית מגורים- בית מס' 41"}) == "legalization"
    assert L.role({"essence": "תוספת של כ-14 מ\"ר לבית מגורים קיים מהיתר מספר 20190723"}) == "addition"
    assert L.role({"essence": "הקמת בית מגורים דו משפחתי", "housing_unit_numbers": [319, 320]}) == "new_dwelling"
    assert L.building_no({"housing_unit_numbers": [320, 319]}) == "319-320"
    assert L.building_no({"essence": "הסדרה בדיעבד בית מגורים- בית מס' 41"}) == "41"


def table(tmp_path, rows, printed):
    """Area table rows laid out as the real PDF: [total, service%, service, main%, main, units, lot, building]."""
    xs = [40, 110, 170, 240, 300, 370, 420, 480]
    lines = [[(x, v) for x, v in zip(xs, r)] for r in rows]
    lines.append([(40, printed[0]), (110, "18.75%"), (170, printed[1]), (240, "81.25%"), (300, printed[2]), (370, printed[3]), (480, "סה")])
    head = [[(40, "סה\"כ"), (110, "אחוז משירות"), (170, "שירות"), (240, "אחוז מעיקרי"), (300, "עיקרי"), (370, "יח\"ד"), (480, "מבנה")]]
    return pdf(tmp_path, "areas.pdf", ["משטח מגרש 368"], table=head + lines)


ROWS = [["500.00", "0.1%", "100.00", "0.5%", "400.00", "2", "368", "301-302"],
        ["500.00", "0.1%", "100.00", "0.5%", "400.00", "2", "368", "313-314"],
        ["600.00", "0.1%", "100.00", "0.6%", "500.00", "2", "368", "335-336"]]


def test_area_table_rows_and_arithmetic(tmp_path):
    docs = E.load_docs([table(tmp_path, ROWS, ("1600.10", "300.00", "1300.00", "6"))])
    rows, printed, _ = E.area_table_rows(docs)
    assert [r["building"] for r in rows] == ["301-302", "313-314", "335-336"] and rows[0]["main"] == Decimal("400.00")
    r = E.r_table_arithmetic(E.Context(docs, {}, "", "368", {}, []))
    assert r.status == "FAIL" and "1600.00" in r.explanation_he and "0.10" in r.explanation_he


def test_table_against_registry(tmp_path, monkeypatch):
    docs = E.load_docs([table(tmp_path, ROWS, ("1600.00", "300.00", "1300.00", "6"))])
    ledger = {"records": [
        {"application_id": "1", "role": "new_dwelling", "units": [301, 302], "primary_m2": "400.00", "service_m2": "100.00", "flags": []},
        {"application_id": "2", "role": "new_dwelling", "units": [313, 314], "primary_m2": "400.00", "service_m2": "50.00", "flags": []},
        {"application_id": "3", "role": "new_dwelling", "units": [335, 336], "primary_m2": "600.00", "service_m2": None,
         "flags": ["total_in_primary"]},
        {"application_id": "4", "role": "legalization", "units": [], "primary_m2": "15.58", "service_m2": "31.77", "flags": ["areas_are_delta"]}]}
    monkeypatch.setattr(E, "load_ledger", lambda gush, cell: ledger)
    ctx = E.Context(docs, {"description": "יחידות 313-314"}, "", "368", {}, [], {}, "2832")
    r = E.r_table_vs_registry(ctx)
    assert r.status == "FAIL" and "313-314" in r.explanation_he and "301-302" not in r.explanation_he.split("במאגר, שדה")[0]
    assert "335-336" in r.explanation_he                      # misfiled total: noted, not a conflict
    ledger["records"][1]["service_m2"] = "100.00"
    assert E.r_table_vs_registry(ctx).status == "PASS"


def test_registry_status(monkeypatch):
    monkeypatch.setattr(E, "load_ledger", lambda gush, cell: {"records": [
        {"application_id": "20260611", "units": [319, 320], "status": "בקרה מרחבית לא תקינה", "source_url": "https://x"}]})
    ctx = E.Context([], {"description": "יחידות 320 -319"}, "", "368", {}, [], {}, "2832")
    assert E.r_registry_status(ctx).status == "FAIL"
    assert E.r_registry_status(E.Context([], {"description": "יחידות 401-402"}, "", "368", {}, [], {}, "2832")) is None


def test_redaction_keeps_wording_not_people():
    assert L.redact("תוספת לבית קיים, משפ' כהן לוי ( 0501234567 ) מבנה 48") == "תוספת לבית קיים, משפ' [שם] ( [טלפון] ) מבנה 48"
    assert L.redact("הקמת בית מגורים דו משפחתי יחידות 314-313 דגם U - טרם שויך") == "הקמת בית מגורים דו משפחתי יחידות 314-313 דגם U - טרם שויך"
    assert L.redact("יחידות 351-352 דגם U 351- דנה ורון כהן. 352 - אבי לוי") == "יחידות 351-352 דגם U [שמות בעלים הושמטו]"
    assert "מגרש 168- הכוללת" in L.redact("בחלק המערבי של מגרש 168- הכוללת סלילת כבישים")


def test_delta_chains_and_indirect():
    recs = [{"application_id": "1", "building": "112", "primary_m2": "93.04", "flags": ["areas_are_delta"]},
            {"application_id": "2", "building": "112", "primary_m2": "13.44", "flags": ["areas_are_delta"]},
            {"application_id": "3", "building": "114", "primary_m2": "111.69", "flags": ["areas_are_delta"]},
            {"application_id": "4", "building": "114", "primary_m2": None, "flags": ["areas_are_delta"]}]
    c = {x["building"]: x for x in L.chains(recs)}
    assert c["112"]["primary_m2"] == "106.48" and c["112"]["delta_primary_m2"] == ["13.44"] and not c["112"]["resolved"]
    assert c["114"]["primary_m2"] is None


def test_real_snapshot_counts():
    """The 25.11.2026 snapshot: 51 lot-368 records, 49 direct with the spec's status counts."""
    import yaml
    d = yaml.safe_load((Path(__file__).resolve().parents[2] / "knowledge/lots/hof_ashkelon_2832_368.yaml").read_text(encoding="utf-8"))
    s = d["snapshot"]
    assert (s["records"], s["direct_records"]) == (51, 49) and sorted(s["indirect"]) == ["20080414", "20250148"]
    assert s["status_counts"] == {"היתר בניה": 27, "היתר / תעודת גמר": 4, "בקרה מרחבית לא תקינה": 14, "מאושר": 3, "הגשה": 1}
    infra = next(r for r in d["records"] if r["application_id"] == "20200565")
    assert infra["role"] == "infrastructure" and "not_dwellings" in infra["flags"]
