"""Source C of the three-way area check: floor areas from the floor plans' cut walls (agent/floor_geometry.py) and
the comparison with the area diagrams (rule HA-AREA-FLOORPLANS)."""
import importlib.util
from pathlib import Path

import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from app.rules import evidence as E

AGENT = Path(__file__).resolve().parents[2] / "agent"
spec = importlib.util.spec_from_file_location("floor_geometry", AGENT / "floor_geometry.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
ZIKIM = Path.home() / "Downloads/10000612352/PERMIT 319-320-hagasha20261111.dwfx"


def test_xps_path_parser():
    assert F.subpaths("M0,0l10,0 0,10 -10,0z") == [[(0, 0), (10, 0), (10, 10), (0, 10)]]
    two = F.subpaths("F1 M0,0h10v10h-10z M20,0 l5,0 0,5z")
    assert len(two) == 2 and two[1] == [(20, 0), (25, 0), (25, 5)]
    assert F.subpaths("M1E2,0L2e2,0 200,100z")[0][1] == (200.0, 0.0)


def test_wall_colours():
    assert F.wall_colour("#F60804") == "red" and F.wall_colour("#0632F4") == "blue"
    assert F.wall_colour("#989898") is None and F.wall_colour("#BB00BB") is None and F.wall_colour("#DCD6D0") is None


def _ring(x0, y0, x1, y1, t=25):
    return box(x0, y0, x1, y1).difference(box(x0 + t, y0 + t, x1 - t, y1 - t))


def test_outline_bridges_openings_and_keeps_recesses():
    # 10 x 8 m (model cm, 1 logical unit per cm) with a 2 m glass front: closed, 80 m²
    walls = _ring(0, 0, 1000, 800).difference(box(400, -1, 600, 30))
    ext, bridge, area, nxt = F._closed_outline(walls, 1.0)
    assert area == pytest.approx(80.0, abs=0.01) and bridge >= 2.0
    # an L-shaped house: the 4 x 3 m re-entrant corner is not filled in
    l_shape = box(0, 0, 1000, 800).difference(box(600, 500, 1001, 801))
    walls = l_shape.difference(l_shape.buffer(-25, join_style=2))
    ext, bridge, area, nxt = F._closed_outline(walls, 1.0)
    assert area == pytest.approx(68.0, abs=0.01)


def test_section_slab_cut():
    slab = unary_union([box(0, 600, 1000, 625), box(0, 0, 25, 600), box(975, 0, 1000, 600)])
    assert F._slab_cut(slab, 0, 1000, 0, 625, 1.0)
    plan_concrete = unary_union([box(0, 0, 300, 25), box(0, 0, 25, 300), box(700, 400, 725, 425)])
    assert not F._slab_cut(plan_concrete, 0, 1000, 0, 800, 1.0)


@pytest.mark.skipif(not ZIKIM.exists(), reason="Zikim plan not on this machine")
def test_zikim_floor_plans():
    r = F.measure(ZIKIM)
    floors = sorted(f["gross_m2"] for f in r["floors"])
    assert len(floors) == 2 and floors[0] == pytest.approx(158.68, abs=0.1) and floors[1] == pytest.approx(247.55, abs=0.1)
    ground = max(r["floors"], key=lambda f: f["gross_m2"])
    assert len(ground["copies"]) >= 2 and ground["copies_spread_m2"] < 0.1          # copies on other sheets agree


def _ctx(floors, diagrams):
    return E.Context([], {}, "", "368", {}, [], {
        "file": "plan.dwfx", "floor_geometry": {"algorithm": F.ALGORITHM, "floors": floors},
        "area_geometry": {"sheets": [{"sheet": 5, "diagrams": diagrams}]}})


def _floor(gross):
    return {"gross_m2": gross, "size_m": [27.22, 9.5], "bridge_m": 2.5, "sensitivity_m2": 0.0, "copies_spread_m2": 0.0,
            "sheet": 6, "scale": "1:100", "copies": [{}]}


GROUND = {"area_m2": {"primary": 109.73, "protected_room_floor": 9.9, "protected_room_walls": 4.14, "covered_service": 49.48}}
UPPER = {"area_m2": {"primary": 72.42, "open_uncounted": 16.22}}


def test_floors_match_diagrams():
    r = E.r_floor_plans(_ctx([_floor(247.54), _floor(144.84)], [GROUND, GROUND, UPPER, UPPER]))
    assert r.status == "PASS" and "סככות" in r.explanation_he          # canopies outside the walls: said, not measured


def test_walls_enclose_more_is_unresolved_not_a_defect():
    r = E.r_floor_plans(_ctx([_floor(247.54), _floor(158.68)], [GROUND, GROUND, UPPER, UPPER]))
    assert r.status == "UNCERTAIN" and r.review == "UNRESOLVED" and r.internal
    assert r.items[0]["review"] == "UNRESOLVED" and "+13.84" in r.items[0]["diff"]


def test_counted_outside_the_walls_is_a_discrepancy():
    r = E.r_floor_plans(_ctx([_floor(230.00), _floor(144.84)], [GROUND, GROUND, UPPER, UPPER]))
    assert r.status == "FAIL" and r.review == "DOCUMENTED_DISCREPANCY"
    assert any(i["review"] == "DOCUMENTED_DISCREPANCY" for i in r.items)


def test_fragmented_outlines_are_unresolved_never_a_discrepancy():
    # 311-312 / 339-340: the ground floor's walls broke into several outlines — partial areas must not be compared
    up = {**UPPER, "same_as": None}
    diags = [GROUND, {**GROUND, "same_as": 0}, up, {**UPPER, "same_as": 2}]
    r = E.r_floor_plans(_ctx([_floor(158.66), _floor(126.48), _floor(68.29), _floor(39.61)], diags))
    assert r.status == "UNCERTAIN" and r.review == "UNRESOLVED" and r.internal and not r.items
