"""ElevationEngine (geometric part): heights measured from the section drawings of a DWFX plan.

Deterministic, no model, no label reading. In each section (a drawing whose concrete — blue fill — forms horizontal
slab bands across its width):
  * slab levels: 2 cm strips where concrete covers at least half of the drawing's width, merged into slabs 0.10-0.60 m
    thick; the top face of each slab is a structural floor level;
  * top of building: the highest drawn geometry (any path, filled or stroked) over the inner 80 % of the section's
    width — roof, parapet or ridge as drawn;
  * scale: the viewport's own transform (floor_geometry._viewports) — never a declared or labelled value.
All heights are relative to the top of the LOWEST slab of that section (structural ground-floor level). This is not the
legal "determining entrance" (כניסה קובעת) and not architectural ±0.00 (finished floor): the relation between them needs
the site plan / survey and is reported as unresolved, with the finish-layer allowance in the uncertainty.

Evidence type of every value: GEOMETRIC_MEASUREMENT. Uncertainty: strip step (0.02 m) + line weight at the sheet scale
+ 0.10 m for the unknown finish above the structural slab when compared with ±0.00 labels.
Usage: python elevation_geometry.py <plan.dwfx>      prints JSON
"""
from __future__ import annotations

import bisect
import json
import re
import sys
import zipfile
from pathlib import Path

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

import floor_geometry as F

ALGORITHM = "elevation_geometry/1"
STEP_CM = 2.0
SLAB_M = (0.10, 0.60)
FINISH_ALLOWANCE_M = 0.10


def _sections_on_sheet(z: zipfile.ZipFile, page: str, folder: str, sheet: int) -> list[dict]:
    vps = F._viewports(z, folder)
    if not vps:
        return []
    starts = [v[0] for v in vps]
    text = z.read(page).decode("utf-8", "replace")
    walls, blue, boxes = {}, {}, {}
    for m in re.finditer(r'<Path Name="[^"]*_(\d+)"([^>]*?)Data="([^"]+)"', text):
        ref, attrs, data = int(m.group(1)), m.group(2), m.group(3)
        vp = bisect.bisect_right(starts, ref) - 1
        if vp < 0:
            continue
        fm = re.search(r'Fill="(#[0-9A-Fa-f]{6})"', attrs)
        fill = fm.group(1).upper() if fm else None
        col = F.wall_colour(fill) if fill else None
        if col:
            for sp in F.subpaths(data):
                g = Polygon(sp).buffer(0)
                if g.area > 0:
                    walls.setdefault(vp, []).append(g)
                    if col == "blue":
                        blue.setdefault(vp, []).append(g)
        pts = [float(v) for v in re.findall(F.NUM, re.sub(r"[A-Za-z]", " ", data))]
        if len(pts) >= 2:
            boxes.setdefault(vp, []).append((min(pts[0::2]), min(pts[1::2]), max(pts[0::2]), max(pts[1::2])))
    out, seen = [], set()
    for vp, pieces in walls.items():
        k = vps[vp][1]                                   # logical units per cm
        scale = round(472.44 / k)
        if scale > 100:
            continue
        u = unary_union(pieces)
        groups = u.buffer(400 * k / 2).buffer(-400 * k / 2)
        b = unary_union(blue.get(vp, [])) if blue.get(vp) else None
        for grp in getattr(groups, "geoms", [groups]):
            x0, y0, x1, y1 = grp.bounds
            w, h = (x1 - x0) / k / 100, (y1 - y0) / k / 100
            if w < 3 or not 2 <= h <= 20 or b is None:
                continue
            bb = b.intersection(grp)
            if not F._slab_cut(bb, x0, x1, y0, y1, k):
                continue
            step, rows, y = STEP_CM * k, [], y0
            while y < y1:
                if bb.intersection(box(x0, y, x1, y + step)).area / step >= 0.5 * (x1 - x0):
                    rows.append(y)
                y += step
            slabs = []
            for r in rows:
                if slabs and r - slabs[-1][1] <= step * 1.01:
                    slabs[-1][1] = r
                else:
                    slabs.append([r, r])
            slabs = [s for s in slabs if SLAB_M[0] <= (s[1] - s[0] + step) / k / 100 <= SLAB_M[1]]
            if len(slabs) < 2:
                continue
            ref = slabs[-1][0]                           # y grows downwards: the lowest slab is the last
            cx0, cx1 = x0 + 0.1 * (x1 - x0), x1 - 0.1 * (x1 - x0)
            tops = [t[1] for t in boxes.get(vp, []) if t[0] >= cx0 and t[2] <= cx1 and ref - 1200 * k <= t[1] <= ref]
            top = min(tops + [y0])
            levels = sorted(round((ref - s[0]) / k / 100, 2) for s in slabs)
            key = (sheet, scale, round(w, 1), tuple(levels))
            if key in seen:
                continue
            seen.add(key)
            line = 1.0 / k / 100 * 2                     # ~2 logical units of line weight, in metres
            out.append({"sheet": sheet, "viewport": vp, "scale": f"1:{scale}", "width_m": round(w, 2),
                        "slab_levels_m": levels, "slab_thickness_m": [round((s[1] - s[0] + step) / k / 100, 2) for s in slabs],
                        "floor_to_floor_m": [round(b2 - a2, 2) for a2, b2 in zip(levels, levels[1:])],
                        "top_above_lowest_slab_m": round((ref - top) / k / 100, 2),
                        "bbox_logical": [round(v) for v in (x0, y0, x1, y1)],
                        "uncertainty_m": round(STEP_CM / 100 + line, 3)})
    return out


def measure(src: Path) -> dict:
    z = zipfile.ZipFile(src)
    secs = []
    for sheet, (page, folder) in enumerate(F._sheet_parts(z), 1):
        secs += _sections_on_sheet(z, page, folder, sheet)
    main = [s for s in secs if s["scale"] == "1:100"] or secs
    top = max((s["top_above_lowest_slab_m"] for s in main), default=None)
    ff = sorted({x for s in main for x in s["floor_to_floor_m"]})
    floors = max((len(s["slab_levels_m"]) for s in main), default=0)
    return {"algorithm": ALGORITHM, "evidence_type": "GEOMETRIC_MEASUREMENT", "sections": secs,
            "summary": {"sections_measured": len(main), "max_top_above_lowest_slab_m": top,
                        "floor_to_floor_m": ff, "slab_levels_max": floors,
                        "uncertainty_m": max((s["uncertainty_m"] for s in main), default=None),
                        "finish_allowance_m": FINISH_ALLOWANCE_M,
                        "reference": "top of the lowest structural slab in each section — not the determining entrance"},
            "method_he": "חתכים: פלטות בטון (מילוי כחול) כרצועות אופקיות; גובה עליון — הגיאומטריה הגבוהה ביותר מעל החתך; "
                         "קנ\"מ מטרנספורמציית ה-Viewport; ללא קריאת מספרים"}


if __name__ == "__main__":
    print(json.dumps(measure(Path(sys.argv[1])), ensure_ascii=False))
