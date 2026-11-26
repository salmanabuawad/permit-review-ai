"""Unified local runner (V9). One entry point over the existing engines — no duplicate engines.

    python scripts/unified.py test                         # the full test suite
    python scripts/unified.py spatial plan.dwfx [out.json] # sources B (area diagrams) and C (floor plans), deterministic
    python scripts/unified.py dwf in.dwf [out.json] [--decode]   # legacy DWF inventory; BLOCKED without a decoder
    python scripts/unified.py bim model.(dwfx|ifc|rvt) [out.json]  # source D: BIM metadata as corroboration only
    python scripts/unified.py review <case_id>             # run the checks on a case in the configured database
    python scripts/unified.py blind validation/cases/<id>  # blind evaluation (freeze, then reveal)

Every output carries the input SHA-256 and the algorithm version. Nothing is sent outside this machine: geometry is
deterministic, and `review` uses the case's configured gateway (local model / relay only).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "backend")]


def _out(obj: dict, dest: str | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=1, default=str)
    Path(dest).write_text(text, encoding="utf-8") if dest else print(text)


def cmd_test(args):
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *args], cwd=ROOT / "backend")


def cmd_spatial(args):
    import area_geometry, floor_geometry
    src = Path(args[0])
    _out({"file": src.name, "file_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
          "area_geometry": area_geometry.measure(src), "floor_geometry": floor_geometry.measure(src),
          "note": "deterministic geometry from the drawing's own transforms; no area-table calibration"},
         args[1] if len(args) > 1 else None)


def cmd_dwf(args):
    import dwf_legacy
    pos = [a for a in args if not a.startswith("--")]
    _out(dwf_legacy.process(Path(pos[0]), decode="--decode" in args), pos[1] if len(pos) > 1 else None)


BIM_MARKERS = re.compile(rb"Revit|IfcProject|IFC2X3|IFC4|Phase Created|Phase Demolished|ObjectDefinition", re.I)


def bim_inspect(src: Path) -> dict:
    """Source D. A BIM model's phases say what the model claims (existing / new / demolished); they do not prove
    construction on site, and they never decide a check alone. Without a BIM model this is NOT_AVAILABLE."""
    data = src.read_bytes()
    out = {"algorithm": "bim_inspect/1", "file": src.name, "file_sha256": hashlib.sha256(data).hexdigest(),
           "corroboration_only": True}
    if src.suffix.lower() == ".ifc":
        phases = sorted(set(re.findall(rb"IFCPROPERTYSINGLEVALUE\('Phase[^']*',\$,IFCLABEL\('([^']*)'", data)))
        return out | {"status": "IFC_FOUND", "phases": [p.decode("utf-8", "replace") for p in phases],
                      "note": "phases are model data, not evidence of construction"}
    if src.suffix.lower() in (".dwfx", ".dwf"):
        try:
            with zipfile.ZipFile(src) as z:
                hits, embedded = set(), []
                for n in z.namelist():
                    b = z.read(n)
                    hits |= {m.group(0).decode() for m in BIM_MARKERS.finditer(b[:2_000_000])}
                    embedded += re.findall(rb'<Embed MIME="([^"]+)"[^>]*Filename="([^"]+)"', b[:200_000])
        except zipfile.BadZipFile:
            return out | {"status": "NOT_A_PACKAGE"}
        emb = [{"mime": m.decode(), "file": f.decode("utf-8", "replace")} for m, f in embedded]
        if any(h.lower() in ("revit", "phase created", "phase demolished", "objectdefinition") for h in hits):
            return out | {"status": "BIM_METADATA_FOUND", "markers": sorted(hits), "embedded": emb}
        return out | {"status": "NOT_AVAILABLE", "embedded": emb,
                      "note": "a 2D plot (ePlot) of a DWG — no BIM objects or phases; source D not available"}
    return out | {"status": "UNSUPPORTED_FORMAT"}


def cmd_bim(args):
    _out(bim_inspect(Path(args[0])), args[1] if len(args) > 1 else None)


def cmd_review(args):
    from app import services
    from app.db import SessionLocal
    from app.models import PermitCase
    with SessionLocal() as s:
        case = s.get(PermitCase, args[0]) or s.query(PermitCase).filter_by(case_number=args[0]).one()
        run = services.run_checks(s, case, "unified-cli")
        s.commit()
        rev = run.summary["review"]
        _out({"case": case.case_number, "run": run.id, "version": run.version, "decision": rev["decision"],
              "counts": rev["counts"], "open_required_checks": rev["coverage"]["open"],
              "metrics": run.summary.get("metrics")}, None)


def cmd_blind(args):
    return subprocess.call([sys.executable, str(ROOT / "scripts" / "evaluate_blind.py"), *args])


COMMANDS = {"test": cmd_test, "spatial": cmd_spatial, "dwf": cmd_dwf, "bim": cmd_bim, "review": cmd_review,
            "blind": cmd_blind}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]) or 0)
