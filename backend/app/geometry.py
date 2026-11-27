"""Deterministic measurements from normalised CAD geometry (metres, local drawing CRS).

The LLM is never used as a calculator. Each measurement carries its method, inputs and an
uncertainty (metres or m²) so the rule engine can return UNCERTAIN near thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import unary_union

# Uncertainty assumed for vector CAD input (drawing precision). DESIGN_ASSUMPTION — to be
# calibrated against manual reviewer measurements.
CAD_LENGTH_UNCERTAINTY_M = 0.0
CAD_AREA_REL_UNCERTAINTY = 0.0


@dataclass
class Measurement:
    key: str
    value: float | None
    units: str
    method: str
    uncertainty: float = 0.0
    status: str = "OK"                       # OK | MISSING_INPUT | NOT_APPLICABLE
    source_entities: list[str] = field(default_factory=list)
    overlay_wkt: str | None = None
    note_he: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _polys(entities, role):
    return [e for e in entities if e.role == role and isinstance(e.geom, Polygon) and not e.geom.is_empty]


def _lines(entities, role):
    out = []
    for e in entities:
        if e.role != role:
            continue
        g = e.geom
        out.append((e, g.exterior if isinstance(g, Polygon) else g))
    return out


def _ref(e) -> str:
    return f"{e.layer}#{e.handle or '?'}" + (f"@{e.via_block}" if e.via_block else "")


def area_of_role(entities, role: str, key: str) -> Measurement:
    polys = _polys(entities, role)
    if not polys:
        return Measurement(key, None, "m2", f"union area of closed polylines on role {role}", status="MISSING_INPUT",
                           note_he=f"לא נמצאו פוליגונים סגורים בשכבה מסוג {role}")
    u = unary_union([e.geom for e in polys])
    return Measurement(key, round(u.area, 4), "m2", f"shapely union area, role {role}",
                       uncertainty=round(u.area * CAD_AREA_REL_UNCERTAINTY, 4),
                       source_entities=[_ref(e) for e in polys], overlay_wkt=u.wkt)


def min_distance(entities, role_a: str, role_b: str, key: str) -> Measurement:
    a = _polys(entities, role_a) or [e for e, _ in _lines(entities, role_a)]
    b = _lines(entities, role_b)
    if not a or not b:
        missing = role_a if not a else role_b
        return Measurement(key, None, "m", f"min distance {role_a}->{role_b}", status="MISSING_INPUT",
                           note_he=f"חסרה שכבה מסוג {missing} — לא ניתן למדוד")
    ga = unary_union([e.geom for e in a])
    gb = MultiLineString([g for _, g in b]) if len(b) > 1 else b[0][1]
    d = ga.distance(gb)
    # overlay: the shortest connecting segment
    from shapely.ops import nearest_points
    p1, p2 = nearest_points(ga, gb)
    return Measurement(key, round(d, 4), "m", f"shapely min distance {role_a} to {role_b} line",
                       uncertainty=CAD_LENGTH_UNCERTAINTY_M,
                       source_entities=[_ref(e) for e in a] + [_ref(e) for e, _ in b],
                       overlay_wkt=LineString([p1, p2]).wkt)


def outside_envelope(entities, inner_role: str, envelope_role: str, key: str) -> Measurement:
    """Area (m²) of inner_role geometry lying outside the envelope polygon(s) (e.g. building lines)."""
    inner = _polys(entities, inner_role)
    env = _polys(entities, envelope_role)
    if not inner or not env:
        missing = inner_role if not inner else envelope_role
        return Measurement(key, None, "m2", f"area of {inner_role} outside {envelope_role}", status="MISSING_INPUT",
                           note_he=f"חסרה שכבה מסוג {missing} — לא ניתן לבדוק חריגה מקווי בניין")
    out = unary_union([e.geom for e in inner]).difference(unary_union([e.geom for e in env]))
    return Measurement(key, round(out.area, 4), "m2", f"shapely difference {inner_role} − {envelope_role}",
                       uncertainty=0.0, source_entities=[_ref(e) for e in inner + env],
                       overlay_wkt=None if out.is_empty else out.wkt)


def standard_measurements(entities) -> dict[str, Measurement]:
    ms = [
        area_of_role(entities, "PLOT_BOUNDARY", "plot_area_m2"),
        area_of_role(entities, "EXISTING", "existing_footprint_m2"),
        area_of_role(entities, "PROPOSED", "proposed_addition_area_m2"),
        area_of_role(entities, "BALCONY", "balcony_area_m2"),
        area_of_role(entities, "SUKKAH", "sukkah_area_m2"),
        area_of_role(entities, "ROOF_ROOM", "roof_room_area_m2"),
        min_distance(entities, "ROOF_ROOM", "ROOF_EDGE_FRONT", "roof_room_front_setback_m"),
        min_distance(entities, "PROPOSED", "PLOT_BOUNDARY", "proposed_to_plot_boundary_m"),
        min_distance(entities, "SUKKAH", "PLOT_BOUNDARY", "sukkah_to_plot_boundary_m"),
        outside_envelope(entities, "PROPOSED", "BUILDING_LINE", "proposed_outside_building_line_m2"),
        outside_envelope(entities, "BALCONY", "BUILDING_LINE", "balcony_outside_building_line_m2"),
    ]
    return {m.key: m for m in ms}
