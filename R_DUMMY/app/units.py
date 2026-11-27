"""Explicit unit handling. Every measurement in the system is stored in metres / m²."""
from __future__ import annotations

# DXF $INSUNITS codes -> metres per drawing unit (subset relevant to architecture)
INSUNITS_TO_M: dict[int, tuple[str, float]] = {
    1: ("inch", 0.0254),
    2: ("foot", 0.3048),
    4: ("mm", 0.001),
    5: ("cm", 0.01),
    6: ("m", 1.0),
    14: ("dm", 0.1),
}


def scale_for_insunits(code: int | None) -> tuple[str, float | None]:
    """Return (unit_name, metres_per_unit). Unknown/unitless -> (name, None): caller must
    require a declared unit instead of guessing."""
    if code in INSUNITS_TO_M:
        return INSUNITS_TO_M[code]
    return ("unitless" if code in (0, None) else f"code_{code}", None)
