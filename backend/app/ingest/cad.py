"""DXF/DWG parsing into normalised geometry (metres).

Deterministic: geometry comes from the vector file, never from an image of a plan.
Handles units ($INSUNITS), layers, LWPOLYLINE/POLYLINE (incl. bulge arcs), LINE, ARC,
CIRCLE, block INSERTs (exploded with their transform) and reports XREFs as unresolved.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
import yaml
from ezdxf import path as ezpath
from shapely.geometry import LineString, Polygon
from shapely.validation import make_valid

from ..config import settings
from ..units import scale_for_insunits

ARC_SAGITTA_M = 0.002          # max chord deviation when flattening arcs (2 mm)


@dataclass
class CadEntityOut:
    layer: str
    role: str | None
    dxftype: str
    geom: object                # shapely geometry in metres
    closed: bool
    handle: str | None
    via_block: str | None = None


@dataclass
class CadResult:
    status: str                                  # OK | NEEDS_UNITS | NEEDS_CONVERSION | ERROR
    units: str = "unknown"
    metres_per_unit: float | None = None
    layers: list[str] = field(default_factory=list)
    roles_found: dict[str, list[str]] = field(default_factory=dict)   # role -> layers
    unmapped_layers: list[str] = field(default_factory=list)
    entities: list[CadEntityOut] = field(default_factory=list)
    xrefs: list[str] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> dict:
        return {
            "status": self.status, "units": self.units, "metres_per_unit": self.metres_per_unit,
            "layers": self.layers, "roles_found": self.roles_found,
            "unmapped_layers": self.unmapped_layers, "entity_count": len(self.entities),
            "xrefs_unresolved": self.xrefs, "skipped": self.skipped, "warnings": self.warnings,
        }


def load_convention(path: Path | None = None) -> dict:
    path = path or settings.knowledge_dir / "layer_convention.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def classify_layer(name: str, convention: dict) -> str | None:
    for role, spec in convention["roles"].items():
        for pat in spec["patterns"]:
            if re.search(pat, name, flags=re.IGNORECASE):
                return role
    return None


def _flatten(entity, scale: float):
    """Entity -> list of (x, y) in metres, closed flag. Uses ezdxf.path for arcs/bulges."""
    p = ezpath.make_path(entity)
    pts = [(v.x * scale, v.y * scale) for v in p.flattening(distance=ARC_SAGITTA_M / scale)]
    closed = bool(getattr(entity, "closed", False)) or entity.dxftype() == "CIRCLE"
    if entity.dxftype() == "LWPOLYLINE":
        closed = entity.closed
    elif entity.dxftype() == "POLYLINE":
        closed = entity.is_closed
    return pts, closed


def _to_geom(pts, closed):
    if closed and len(pts) >= 3:
        poly = Polygon(pts)
        return poly if poly.is_valid else make_valid(poly)
    if len(pts) >= 2:
        return LineString(pts)
    return None


SUPPORTED = {"LWPOLYLINE", "POLYLINE", "LINE", "ARC", "CIRCLE"}


def parse_dxf(path: Path, declared_units_m: float | None = None, convention: dict | None = None) -> CadResult:
    convention = convention or load_convention()
    try:
        doc = ezdxf.readfile(str(path))
    except Exception as exc:  # noqa: BLE001 — report, never crash ingest
        return CadResult(status="ERROR", warnings=[f"DXF read error: {exc}"])

    code = doc.header.get("$INSUNITS", 0)
    unit_name, scale = scale_for_insunits(code)
    res = CadResult(status="OK", units=unit_name)
    if scale is None:
        if declared_units_m:
            scale = declared_units_m
            res.warnings.append(f"$INSUNITS={code}; using unit declared at upload ({declared_units_m} m/unit)")
        else:
            res.status = "NEEDS_UNITS"
            res.warnings.append("Drawing has no units ($INSUNITS). Measurement blocked until a unit is declared.")
            scale = 1.0  # geometry kept for display only
    res.metres_per_unit = scale

    for blk in doc.blocks:
        if blk.block.is_xref:
            res.xrefs.append(blk.name)
    if res.xrefs:
        res.warnings.append("External references (XREF) are not embedded; their content was not measured.")

    res.layers = sorted(layer.dxf.name for layer in doc.layers)

    def handle(entity, via_block=None):
        t = entity.dxftype()
        if t == "INSERT":
            if entity.dxf.name in res.xrefs:
                return
            for sub in entity.virtual_entities():
                handle(sub, via_block=entity.dxf.name)
            return
        if t not in SUPPORTED:
            res.skipped[t] = res.skipped.get(t, 0) + 1
            return
        try:
            pts, closed = _flatten(entity, scale)
        except Exception as exc:  # noqa: BLE001
            res.warnings.append(f"{t} {entity.dxf.handle}: {exc}")
            return
        geom = _to_geom(pts, closed)
        if geom is None:
            return
        layer = entity.dxf.layer
        role = classify_layer(layer, convention)
        res.entities.append(CadEntityOut(layer, role, t, geom, closed, entity.dxf.get("handle"), via_block))

    for e in doc.modelspace():
        handle(e)

    for ent in res.entities:
        if ent.role:
            res.roles_found.setdefault(ent.role, [])
            if ent.layer not in res.roles_found[ent.role]:
                res.roles_found[ent.role].append(ent.layer)
    used_layers = {e.layer for e in res.entities}
    res.unmapped_layers = sorted(l for l in used_layers if classify_layer(l, convention) is None)
    return res


def convert_dwg(path: Path) -> tuple[Path | None, str]:
    """Convert DWG -> DXF with ODA File Converter if configured. Returns (dxf_path, message)."""
    exe = settings.oda_converter or shutil.which("ODAFileConverter") or ""
    if not exe:
        return None, "ODA File Converter not configured (BBP_ODA_CONVERTER). DWG stored, not measured."
    out_dir = Path(tempfile.mkdtemp(prefix="dwg2dxf_"))
    in_dir = path.parent
    cmd = [exe, str(in_dir), str(out_dir), "ACAD2018", "DXF", "0", "1", path.name]
    try:
        subprocess.run(cmd, check=True, timeout=180, capture_output=True)
    except Exception as exc:  # noqa: BLE001
        return None, f"DWG conversion failed: {exc}"
    out = out_dir / (path.stem + ".dxf")
    return (out if out.exists() else None), ("converted" if out.exists() else "converter produced no output")
