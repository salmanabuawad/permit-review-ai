"""Component-level validation: every building component and every attribute is checked on its own, against the limit
the ApplicableRegulationResolver found for exactly that component and attribute.

Internal and external heights are separate attributes with separate limits; a value is only ever compared with the
limit of its own attribute, so an internal height can never "pass" against an external limit or the reverse.
Each measurement carries its evidence source: "measured" (deterministic geometry), "drawing_read" (local image model),
"declared" (the application's own number), "committee_reported" (a number quoted from the committee's documents —
kept as such and never presented as independently calculated geometry).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

COMPONENTS = ("covered_parking", "garage", "storage", "basement", "protected_room", "pergola", "balcony", "roof",
              "external_stairs", "retaining_wall", "fence", "auxiliary_building")
ATTRIBUTES = ("area_m2", "inner_height_m", "outer_height_m", "width_m", "length_m", "ridge_height_m", "flat_height_m",
              "main_area_m2", "setback_front_m", "setback_side_m", "setback_rear_m")
EVIDENCE = ("measured", "drawing_read", "declared", "committee_reported")
TOL = 0.005


@dataclass
class Measure:
    value: float
    source: str                                   # one of EVIDENCE
    ref: str = ""                                 # where it was read (document, sheet, protocol)

    def __post_init__(self):
        if self.source not in EVIDENCE:
            raise ValueError(f"unknown evidence source {self.source}")


@dataclass
class Component:
    kind: str
    measures: dict = field(default_factory=dict)  # attribute -> Measure
    location: str | None = None                   # e.g. "within building lines", "front 0.0"
    use: str | None = None
    reliefs: list = field(default_factory=list)   # attributes for which a relief is requested

    def __post_init__(self):
        if self.kind not in COMPONENTS:
            raise ValueError(f"unknown component {self.kind}")
        bad = set(self.measures) - set(ATTRIBUTES)
        if bad:
            raise ValueError(f"unknown attributes {bad}")


@dataclass
class ComponentFinding:
    component: str
    attribute: str
    status: str            # WITHIN | EXCEEDS | RELIEF_REQUESTED | NO_MEASUREMENT | NO_APPLICABLE_LIMIT | UNRESOLVED_LIMIT
    permitted: float | None = None
    value: float | None = None
    deviation_abs: float | None = None
    deviation_pct: float | None = None
    evidence_source: str | None = None
    evidence_ref: str = ""
    regulation: dict = field(default_factory=dict)  # plan, source_id, clause, page
    independent: bool = False                     # True only for measured geometry

    def as_dict(self) -> dict:
        return asdict(self)


def validate_component(c: Component, limits: dict) -> list[ComponentFinding]:
    out = []
    attrs = sorted(set(c.measures) | {a for (k, a) in limits if k == c.kind} | set(c.reliefs))
    for a in attrs:
        lim = limits.get((c.kind, a))
        m = c.measures.get(a)
        reg = {"plan": lim.plan, "source_id": lim.source_id, "clause": lim.clause, "page": lim.page} if lim else {}
        if lim is None:
            out.append(ComponentFinding(c.kind, a, "NO_APPLICABLE_LIMIT", value=m.value if m else None,
                                        evidence_source=m.source if m else None))
            continue
        if lim.status == "UNRESOLVED_CONFLICT" or lim.value is None:
            out.append(ComponentFinding(c.kind, a, "UNRESOLVED_LIMIT", value=m.value if m else None,
                                        evidence_source=m.source if m else None, regulation=reg | {"note": lim.note}))
            continue
        if m is None:
            out.append(ComponentFinding(c.kind, a, "NO_MEASUREMENT", permitted=lim.value, regulation=reg))
            continue
        dev = round(m.value - lim.value, 3)
        pct = round(100 * dev / lim.value, 2) if lim.value else None
        st = "WITHIN" if m.value <= lim.value + TOL else ("RELIEF_REQUESTED" if a in c.reliefs else "EXCEEDS")
        out.append(ComponentFinding(c.kind, a, st, lim.value, m.value, dev if dev > TOL else 0.0,
                                    pct if dev > TOL else 0.0, m.source, m.ref, reg, m.source == "measured"))
    return out
