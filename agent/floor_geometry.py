"""Source C of the three-way area check: floor areas reconstructed from the architectural floor plans' walls.

Deterministic, no model, no declared value. From a DWFX plan sheet:
  * paths are read from the sheet's XPS (FixedPage) with their fill and DWF object number; the object number places
    each path in its viewport, and each viewport's <Viewport Transform> gives logical units per model unit — the
    drawing scale (1:100, 1:50 ...) comes from the file, never from area totals; the model unit (cm) is the one that
    makes the plans building-sized;
  * cut walls are taken by the Israeli permit-drawing colour convention: saturated red (new construction) and blue
    (concrete); hatching, furniture and annotation are other colours;
  * wall pieces are grouped into drawings; a drawing with soil hatching (dense grey fill) right under it is a section
    or elevation, not a plan;
  * the floor outline: openings (doors, windows, glass fronts) are bridged by a morphological closing with a square
    element; the bridge is the smallest that gives one closed outline, and the outline is accepted only if its area
    does not change at the next bridge size (a recess wider than the bridge would). The area inside the outer face of
    the walls is the floor's gross area; the result records the bridge used and the area at the next size, as the
    measurement's sensitivity.

Usage: python floor_geometry.py <plan.dwfx>      prints JSON
"""
from __future__ import annotations

import bisect
import colorsys
import json
import re
import sys
import zipfile
from pathlib import Path

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

ALGORITHM = "floor_geometry/1"
NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
TOK = re.compile(rf"[MmLlHhVvZzAaCcQqSs]|{NUM}")
NARGS = {"m": 2, "l": 2, "h": 1, "v": 1, "a": 7, "c": 6, "q": 4, "s": 4}
BRIDGES_M = (0.6, 0.9, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5)   # opening widths tried, m
STABLE_M2 = 0.5                                       # outline accepted when the next bridge changes it by less
SOIL_FILL = "#989898"                                 # soil / ground hatching under sections and elevations
MIN_PLAN_M2 = 20.0                                    # a floor plan of a building, not a detail
MIN_WALL_SHARE = 0.05                                 # cut walls are at least this share of a floor's gross area
SAME_FLOOR = (0.25, 0.01)                             # copies of one floor: size within 0.25 m, area within 1%


def subpaths(data: str) -> list[list[tuple[float, float]]]:
    """XPS path mini-language -> closed point lists (curves and arcs by their end points)."""
    toks = TOK.findall(re.sub(r"^\s*F[01]\s*", "", data))
    out, cur = [], []
    x = y = sx = sy = 0.0
    cmd, i = "M", 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd, i = t, i + 1
            if cmd in "Zz":
                if len(cur) > 2:
                    out.append(cur)
                cur, x, y = [], sx, sy
            continue
        n = NARGS.get(cmd.lower(), 2)
        a = [float(v) for v in toks[i:i + n]]
        i += n
        if len(a) < n:
            break
        rel, c = cmd.islower(), cmd.lower()
        if c == "m":
            if len(cur) > 2:
                out.append(cur)
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            sx, sy, cur = x, y, [(x, y)]
            cmd = "l" if rel else "L"                    # coordinates after a moveto are linetos
        elif c == "l":
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            cur.append((x, y))
        elif c == "h":
            x = x + a[0] if rel else a[0]
            cur.append((x, y))
        elif c == "v":
            y = y + a[0] if rel else a[0]
            cur.append((x, y))
        else:
            x, y = (x + a[-2], y + a[-1]) if rel else (a[-2], a[-1])
            cur.append((x, y))
    if len(cur) > 2:
        out.append(cur)
    return out


def wall_colour(hex_: str) -> str | None:
    """'red' (new construction) | 'blue' (concrete) | None — the cut-wall colours of Israeli permit drawings."""
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.6 or v < 0.5:
        return None
    return "red" if (h <= 0.04 or h >= 0.96) else "blue" if 0.58 <= h <= 0.68 else None


def _slab_cut(blue, x0: float, x1: float, y0: float, y1: float, k: float) -> bool:
    """A section cuts the floor / roof slabs: a thin concrete band across most of the drawing's width. A plan's
    concrete is columns and the protected room, never such a band."""
    if blue is None or blue.is_empty:
        return False
    step = 10 * k                                         # 10 cm strips
    y = y0
    while y < y1:
        if blue.intersection(box(x0, y, x1, y + step)).area / step >= 0.7 * (x1 - x0):
            return True
        y += step
    return False


def _sheet_parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    fdoc = next(n for n in z.namelist() if n.endswith("FixedDocument.fdoc"))
    pages = [s.lstrip("/") for s in re.findall(r'Source="([^"]+)"', z.read(fdoc).decode("utf-8", "replace"))]
    return [(p, p.rsplit("/", 1)[0]) for p in pages]


def _viewports(z: zipfile.ZipFile, folder: str) -> list[tuple[int, float]]:
    """(first object number, logical units per model unit) for each viewport, in drawing order."""
    out = []
    for n in z.namelist():
        if n.startswith(folder + "/") and n.endswith(".xml") and not n.endswith("descriptor.xml"):
            t = z.read(n).decode("utf-8", "replace")
            for m in re.finditer(r'<RenditionSync refName="[^"]*_(\d+)"><Viewport Transform="([-\d.eE]+),', t):
                out.append((int(m.group(1)), float(m.group(2))))
    return sorted(out)


def _closed_outline(walls, k: float):
    """Smallest bridge giving one stable closed outline: (polygon, bridge_m, area_m2, next_area_m2) or None."""
    prev = None
    for b in BRIDGES_M:
        d = b * 100 * k / 2
        c = walls.buffer(d, join_style=2, cap_style=3).buffer(-d, join_style=2, cap_style=3)
        big = max(getattr(c, "geoms", [c]), key=lambda g: g.area)
        ext = Polygon(big.exterior)
        area = ext.area / k ** 2 / 1e4
        closed = len(big.interiors) > 0 and ext.area > 2 * walls.area
        if prev and prev[3] and closed and abs(area - prev[2]) < STABLE_M2:
            return prev[0], prev[1], prev[2], area
        prev = (ext, b, area, closed)
    return None


def floors(plans: list[dict]) -> list[dict]:
    """The distinct floors: plans that repeat on several sheets (a plan copied into the site or area sheets) are one
    floor; the spread of their areas is a consistency check of the measurement."""
    out: list[dict] = []
    for p in sorted(plans, key=lambda p: -p["gross_m2"]):
        f = next((f for f in out if all(abs(a - b) <= SAME_FLOOR[0] for a, b in zip(sorted(f["size_m"]), sorted(p["size_m"])))
                  and abs(f["gross_m2"] - p["gross_m2"]) <= SAME_FLOOR[1] * f["gross_m2"]), None)
        if f:
            f["copies"].append({"sheet": p["sheet"], "scale": p["scale"], "gross_m2": p["gross_m2"]})
            continue
        out.append({"gross_m2": p["gross_m2"], "size_m": p["size_m"], "bridge_m": p["bridge_m"],
                    "sensitivity_m2": round(abs(p["next_bridge_m2"] - p["gross_m2"]), 2), "walls_m2": p["walls_m2"],
                    "sheet": p["sheet"], "scale": p["scale"],
                    "copies": [{"sheet": p["sheet"], "scale": p["scale"], "gross_m2": p["gross_m2"]}]})
    for f in out:
        g = [c["gross_m2"] for c in f["copies"]]
        f["copies_spread_m2"] = round(max(g) - min(g), 2)
    return out


def measure(src: Path) -> dict:
    z = zipfile.ZipFile(src)
    plans = []
    for sheet, (page, folder) in enumerate(_sheet_parts(z), 1):
        vps = _viewports(z, folder)
        if not vps:
            continue
        starts = [v[0] for v in vps]
        text = z.read(page).decode("utf-8", "replace")
        walls_by_vp: dict[int, list] = {}
        blue_by_vp: dict[int, list] = {}
        soil = []
        for m in re.finditer(r'<Path Name="[^"]*_(\d+)" Fill="(#[0-9A-Fa-f]{6})"[^>]*?Data="([^"]+)"', text):
            ref, fill, data = int(m.group(1)), m.group(2).upper(), m.group(3)
            colour = wall_colour(fill)
            wall, ground = colour is not None, fill == SOIL_FILL
            if not (wall or ground):
                continue
            vp = bisect.bisect_right(starts, ref) - 1
            if vp < 0:
                continue
            for sp in subpaths(data):
                g = Polygon(sp).buffer(0)
                if g.area > 0:
                    (walls_by_vp.setdefault(vp, []) if wall else soil).append(g)
                    if colour == "blue":
                        blue_by_vp.setdefault(vp, []).append(g)
        soil_u = unary_union(soil) if soil else None
        for vp, pieces in walls_by_vp.items():
            k = vps[vp][1]                               # logical units per model unit (cm)
            if round(472.44 / k) > 100:
                continue                                 # floor plans are drawn at 1:100 or larger; 1:125/1:250 are site plans
            blue_all = unary_union(blue_by_vp.get(vp, [])) if blue_by_vp.get(vp) else None
            u = unary_union(pieces)
            groups = u.buffer(400 * k / 2).buffer(-400 * k / 2)       # drawings: pieces within 4 m of each other
            from shapely.strtree import STRtree
            tree = STRtree(pieces)
            for grp in getattr(groups, "geoms", [groups]):
                x0, y0, x1, y1 = grp.bounds
                w_m, h_m = (x1 - x0) / k / 100, (y1 - y0) / k / 100
                if not (3 <= max(w_m, h_m) <= 80):
                    continue
                under = box(x0, y1, x1, y1 + 150 * k)                 # 1.5 m below the drawing (y grows downwards)
                if soil_u is not None and soil_u.intersection(under).area > 0.15 * under.area:
                    continue                                          # section / elevation over soil hatching
                # whole pieces of this drawing (an intersection would clip slivers at the wall joints)
                walls = unary_union([pieces[i] for i in tree.query(grp) if pieces[i].representative_point().within(grp)])
                if _slab_cut(blue_all.intersection(grp) if blue_all is not None else None, x0, x1, y0, y1, k):
                    continue                     # a section, not a plan
                res = _closed_outline(walls, k)
                if not res:
                    continue
                ext, bridge, area, nxt = res
                ex0, ey0, ex1, ey1 = ext.bounds
                if (area < MIN_PLAN_M2 or min(ex1 - ex0, ey1 - ey0) < 300 * k
                        or walls.area / k ** 2 / 1e4 < MIN_WALL_SHARE * area):
                    continue                     # a detail, or an outline of thin lines (lot boundary), not a floor
                ex0, ey0, ex1, ey1 = ext.bounds
                plans.append({"sheet": sheet, "viewport": vp, "scale": f"1:{round(472.44 / k)}",
                              "bbox_logical": [round(v) for v in (ex0, ey0, ex1, ey1)],
                              "size_m": [round((ex1 - ex0) / k / 100, 2), round((ey1 - ey0) / k / 100, 2)],
                              "gross_m2": round(area, 2), "bridge_m": bridge, "next_bridge_m2": round(nxt, 2),
                              "walls_m2": round(walls.area / k ** 2 / 1e4, 2),
                              "outline_cm": [[round(x / k, 1), round(y / k, 1)] for x, y in ext.exterior.coords]})
    plans.sort(key=lambda p: (p["sheet"], p["bbox_logical"][1] // 2000, p["bbox_logical"][0]))
    return {"algorithm": ALGORITHM, "plans": plans, "floors": floors(plans),
            "method_he": "מעטפת הקירות החתוכים (אדום/כחול) בתכניות הקומה; פתחים גושרו בסגירה מורפולוגית; קנ\"מ מטרנספורמציית ה-Viewport"}


if __name__ == "__main__":
    print(json.dumps(measure(Path(sys.argv[1])), ensure_ascii=False))
