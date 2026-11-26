"""V9 engines: spatial margins with uncertainty, well protection zones by the plan's wording, the legacy DWF decoder
gate (blocked, never measured), archive limits, and plan scoping (no plan is assumed to apply)."""
import datetime as dt
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

from app.rules import route as R
from app.rules import spatial as SP

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("dwf_legacy", ROOT / "agent" / "dwf_legacy.py")
DW = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DW)
ZIKIM_DWF = Path.home() / "Downloads/10000612352/מגרש 368- יחידות 319+320 -נספח סניטרי.dwf"


# ------------------------------------------------------------------ spatial margins

def test_v5_building_line_screen_stays_unresolved():
    # V5 local building line: two methods give -0.240 m and +0.009 m — they disagree, nothing is decided
    out = SP.classify_margin("קו בניין מקומי", [SP.Measurement(-0.240, 0.05, "DWFX transform"),
                                                SP.Measurement(0.009, 0.05, "GIS overlay")])
    assert out.status == "UNRESOLVED" and "אינן מסכימות" in out.explanation_he


def test_margin_within_uncertainty_is_unresolved():
    assert SP.classify_margin("קו בניין", [SP.Measurement(0.03, 0.10, "x", verified=True)]).status == "UNRESOLVED"
    assert SP.classify_margin("קו בניין", [SP.Measurement(-0.03, 0.10, "x", verified=True)]).status == "UNRESOLVED"


def test_clear_margins_and_candidate_geometry():
    assert SP.classify_margin("קו בניין", [SP.Measurement(0.80, 0.10, "x")]).status == "PASS"
    # a clear violation on candidate (unverified) geometry is still not certified
    assert SP.classify_margin("קו בניין", [SP.Measurement(-0.80, 0.10, "x")]).status == "UNRESOLVED"
    assert SP.classify_margin("קו בניין", [SP.Measurement(-0.80, 0.10, "x", verified=True)]).status == "CONFIRMED_DEFECT"
    assert SP.classify_margin("קו בניין", []).status == "NOT_CHECKED"


def test_well_zone_overlap_is_not_automatically_a_violation():
    # zone C forbids severe-pollution works (sewage facilities), not a residential building — plan 633-0723718 §6.4
    assert SP.well_zone("C", 40.0).status == "PASS"
    assert SP.well_zone("C", 40.0, permit_condition=True).status == "FUTURE_STAGE"
    assert SP.well_zone("B", 5.0).status == "UNRESOLVED"                       # unverified geometry
    assert SP.well_zone("B", 5.0, geometry_verified=True).status == "CONFIRMED_DEFECT"
    assert SP.well_zone("C", None).status == "NOT_CHECKED" and SP.well_zone("C", 0).status == "PASS"


def test_well_zone_wording_is_from_the_scanned_plan():
    text = (ROOT / "knowledge/source_texts/ha_633_0723718/ocr/approved_2021_p14.txt").read_text(encoding="utf-8")
    assert "באזור מגן ג'" in text and "מתקן ביוב" in text


# ------------------------------------------------------------------ legacy DWF

def _dwf(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in members.items():
            z.writestr(n, b)
    return b"(DWF V06.00)" + buf.getvalue()


def test_dwf_without_decoder_is_blocked_and_never_measured(tmp_path, monkeypatch):
    monkeypatch.setattr(DW, "DECODERS", {"ezdwf": lambda: False})
    f = tmp_path / "a.dwf"
    f.write_bytes(_dwf({"sec/descriptor.xml": '<ePlot:Page xmlns:ePlot="DWF-ePlot:1.2" name="P" objectId="{1}">'
                                              '<ePlot:Paper units="mm" width="841" height="594"/></ePlot:Page>',
                        "sec/x.w2d": b"(W2D V06.00)(Creator 'test')" + b"\0" * 100}))
    out = DW.process(f, decode=True)
    assert out["status"] == "BLOCKED_NO_DECODER" and out["measured"] is False and out["blocker"]
    assert out["pages"][0]["paper"]["kind"] == "paper_metadata_not_measurement"      # paper mm are not metres
    assert out["streams"][0]["w2d_version"] == "06.00" and len(out["file_sha256"]) == 64


def test_found_but_unvalidated_decoder_is_still_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(DW, "DECODERS", {"ezdwf": lambda: True})
    f = tmp_path / "a.dwf"
    f.write_bytes(_dwf({"sec/x.w2d": b"(W2D V06.00)"}))
    assert DW.process(f, decode=True)["status"] == "BLOCKED_DECODER_UNVALIDATED"


def test_archive_limits(tmp_path):
    f = tmp_path / "evil.dwf"
    f.write_bytes(_dwf({"../../etc/x": b"1"}))
    with pytest.raises(DW.ArchiveRejected, match="unsafe"):
        DW.inventory(f)


@pytest.mark.skipif(not ZIKIM_DWF.exists(), reason="Zikim sanitary annex not on this machine")
def test_zikim_sanitary_annex_is_blocked():
    out = DW.process(ZIKIM_DWF, decode=True)
    assert out["status"].startswith("BLOCKED") and out["streams"][0]["w2d_version"] == "06.00"


# ------------------------------------------------------------------ plan scoping

def test_no_plan_is_assumed_for_zikim():
    # Zikim lot 368 is governed by 633-0723718; plan 633-0928358 (cited in another committee's opinion) is not assumed
    rights, note = R.load_rights(["633-0723718"], "מגורים", dt.date(2026, 11, 11))
    assert rights is None or "0928358" not in str(rights.get("plan")) + str(rights.get("aliases"))
    for p in (ROOT / "knowledge").rglob("*.yaml"):
        assert "633-0928358" not in p.read_text(encoding="utf-8"), p
