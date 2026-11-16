"""CAD / Excel / PDF ingestion and deterministic geometry."""
import math

import ezdxf
import pytest

from app.geometry import standard_measurements
from app.ingest import cad, excel, files, pdf

from .conftest import FIX


def test_dxf_units_mm_to_m_and_roles():
    r = cad.parse_dxf(FIX / "case1_extension_exceeds.dxf")
    assert r.status == "OK" and r.units == "mm" and r.metres_per_unit == 0.001
    assert {"PLOT_BOUNDARY", "BUILDING_LINE", "EXISTING", "PROPOSED", "BALCONY"} <= set(r.roles_found)
    m = standard_measurements(r.entities)
    assert m["plot_area_m2"].value == pytest.approx(500.0)
    assert m["proposed_addition_area_m2"].value == pytest.approx(30.0)
    assert m["proposed_outside_building_line_m2"].value == pytest.approx(18.0)


def test_block_insert_exploded_and_arc_flattened():
    r = cad.parse_dxf(FIX / "case1_extension_exceeds.dxf")
    balc = [e for e in r.entities if e.role == "BALCONY"]
    assert balc and balc[0].via_block == "BALCONY_R"
    # 3 x 1.2 rectangle + circular segment with bulge 0.4 on a 3 m chord
    chord, bulge = 3.0, 0.4
    theta = 4 * math.atan(bulge)
    radius = chord / (2 * math.sin(theta / 2))
    segment = radius ** 2 / 2 * (theta - math.sin(theta))
    assert balc[0].geom.area == pytest.approx(3 * 1.2 + segment, abs=0.01)


def test_roof_setback_measured_exactly():
    for name, expected in (("case3_roof_room_249.dxf", 2.49), ("case3b_roof_room_250.dxf", 2.50)):
        m = standard_measurements(cad.parse_dxf(FIX / name).entities)
        assert m["roof_room_front_setback_m"].value == pytest.approx(expected, abs=1e-6)


def test_dxf_without_units_blocks_measurement(tmp_path):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=True, dxfattribs={"layer": "PLOT"})
    p = tmp_path / "nounits.dxf"
    doc.saveas(p)
    assert cad.parse_dxf(p).status == "NEEDS_UNITS"
    r = cad.parse_dxf(p, declared_units_m=1.0)
    assert r.status == "OK" and r.warnings


def test_xref_reported_not_measured(tmp_path):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 6
    doc.add_xref_def("survey.dxf", "SURVEY_XREF")
    doc.modelspace().add_blockref("SURVEY_XREF", (0, 0))
    p = tmp_path / "xref.dxf"
    doc.saveas(p)
    r = cad.parse_dxf(p)
    assert "SURVEY_XREF" in r.xrefs and any("XREF" in w for w in r.warnings)


def test_missing_layer_yields_missing_input():
    m = standard_measurements(cad.parse_dxf(FIX / "case4_sukkah.dxf").entities)
    assert m["proposed_addition_area_m2"].status == "MISSING_INPUT"
    assert m["sukkah_to_plot_boundary_m"].value == pytest.approx(1.2)


def test_excel_area_table():
    r = excel.parse_area_table(FIX / "case1_area_table.xlsx")
    assert r.status == "OK"
    assert r.totals["proposed_main_m2"] == 26.0 and r.totals["existing_main_m2"] == 168.0


def test_pdf_text_and_boxes():
    r = pdf.parse_pdf(FIX / "application_form.pdf")
    assert r.status == "OK" and r.page_count == 1
    assert r.pages[0].words and all(len(w) == 5 for w in r.pages[0].words)


def test_intake_rejects_mismatched_content():
    with pytest.raises(files.IntakeError):
        files.detect_kind("fake.pdf", b"PK\x03\x04 not a pdf")
    with pytest.raises(files.IntakeError):
        files.detect_kind("evil.exe", b"MZ")
    assert files.detect_kind("a.dxf", b"  0\nSECTION\n") == "dxf"
