"""Deterministic area measurement from the area-calculation diagrams in a DWFX plan (source B of the three-way area
check: A = declared, B = the submitted area diagrams measured here, C = reconstructed from the floor plans).

No model and no declared value is used. All numbers come from the vector geometry and the package's own transforms:
  * scale: each ePlot section stores the model-to-plot transform (<Units Transform="sx,..."/>) and its FixedPage
    canvas scale (RenderTransform); together they give plot points per model unit. The model unit (cm / mm / m) is
    chosen as the only one that gives building-sized diagrams (3-80 m) — checked, never fitted to a declared total.
  * polygons: the coloured fills of the diagrams (exported as triangles / rectangles), unioned per colour with Shapely.
  * diagrams: connected groups of fills; the table strips beside them (filled rectangles) are told apart and dropped.
  * classification: by the colour legend of the area-calculation tool that drew the sheet (LEGENDS) — a convention
    of that tool, recorded with the result. Protected-room floor pieces are split by the 9 m² net service allowance.

Checks recorded per diagram: overlapping categories (double counting), and units that repeat (mirrored copies).
Runs on the AI PC (bbp_ai_agent.py, with the drawing reader) — DWFX is never processed on the app server.
Usage: python area_geometry.py <plan.dwfx>      prints JSON
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

import pymupdf
from shapely.geometry import Polygon
from shapely.ops import unary_union

ALGORITHM = "area_geometry/1"
# colour legend of the "AreaCalculation" tool (sheet resource title ...\AreaCalculation\Out\...): fill -> category
LEGENDS = {
    "AreaCalculation": {
        "#FEAE01": "primary",                 # שטח עיקרי
        "#C4D6D7": "protected_room_floor",    # רצפת ממ"ד
        "#A8B1B6": "protected_room_walls",    # קירות ממ"ד
        "#91E6C2": "covered_service",         # סככות / שטחים מקורים (שירות)
        "#CB9AEB": "open_uncounted",          # משטחים לא מקורים ופתוחים (לא נספרים)
        "#FFFFFF": "deduction",               # הורדות / חללים
    },
}
SERVICE_PROTECTED_NET_M2 = 9.0   # protected-room floor counted as service up to 9 m² net (HA-917226302E p.4); rest primary
UNIT_M = {"mm": 0.001, "cm": 0.01, "m": 1.0}
MIN_POLY_M2 = 0.005              # slivers below this are drawing noise


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(c * 255):02X}" for c in rgb)


def _sections(z: zipfile.ZipFile) -> list[dict]:
    """The package's sheets in page order, with their transforms and the tool that made them."""
    fdoc = next(n for n in z.namelist() if n.endswith("FixedDocument.fdoc"))
    pages = [s.lstrip("/") for s in re.findall(r'Source="([^"]+)"', z.read(fdoc).decode("utf-8", "replace"))]
    out = []
    for i, page in enumerate(pages, 1):
        folder = page.rsplit("/", 1)[0]
        desc = z.read(folder + "/descriptor.xml").decode("utf-8", "replace") if folder + "/descriptor.xml" in z.namelist() else ""
        fpage = z.read(page).decode("utf-8", "replace")[:4000]
        render = re.search(r'<Canvas[^>]*RenderTransform="([-\d.eE]+),', fpage)
        units = None
        for n in z.namelist():
            if n.startswith(folder + "/") and n.endswith(".xml") and not n.endswith("descriptor.xml"):
                m = re.search(r'<Units[^>]*Transform="([-\d.eE]+),[^,]*,[^,]*,[^,]*,[^,]*,([-\d.eE]+)', z.read(n).decode("utf-8", "replace"))
                if m:
                    units = (float(m.group(1)), float(m.group(2)))
                    break
        title = " ".join(re.findall(r'GraphicResource[^>]*title="([^"]*)"', desc))
        tool = next((t for t in LEGENDS if t in title), None)
        out.append({"sheet": i, "tool": tool, "render": float(render.group(1)) if render else None, "units": units,
                    "dwg": (re.search(r'name="File Name" value="([^"]*)"', desc) or [None, None])[1]})
    return out


def _polygon(d) -> Polygon | None:
    pts = []
    for it in d["items"]:
        if it[0] == "l":
            pts += [it[1], it[2]]
        elif it[0] == "re":
            r = it[1]
            pts += [r.tl, r.tr, r.br, r.bl]
        elif it[0] == "qu":
            q = it[1]
            pts += [q.ul, q.ur, q.lr, q.ll]
        elif it[0] == "c":
            pts += [it[1], it[4]]
    if len(pts) < 3:
        return None
    p = Polygon([(x.x, x.y) for x in pts]).buffer(0)
    return p if p.area > 0 else None


def _is_strip(geom, members) -> bool:
    """A table row of the area table: one filled rectangle, much wider than tall (diagrams are not rectangles)."""
    x0, y0, x1, y1 = geom.bounds
    w, h = x1 - x0, y1 - y0
    return geom.area >= 0.97 * w * h and h < 0.35 * w


def measure_sheet(page, sec: dict) -> dict | None:
    legend = LEGENDS.get(sec["tool"] or "")
    if not legend or not sec["units"] or not sec["render"]:
        return None
    pt_per_unit = sec["units"][0] * sec["render"] * 72 / 96      # model unit -> plot points (XPS: 1/96 in)
    fills = []
    for d in page.get_drawings():
        if d.get("fill") is None:
            continue
        col = _hex(d["fill"])
        if col not in legend:
            continue
        g = _polygon(d)
        if g is not None:
            fills.append((col, g))
    if not fills:
        return None
    comps = list(getattr(unary_union([g for _, g in fills]), "geoms", None) or [unary_union([g for _, g in fills])])
    # model unit: the one that makes the largest diagram building-sized
    big = max(comps, key=lambda c: c.area)
    unit = next((u for u, f in UNIT_M.items()
                 if 3 <= max(big.bounds[2] - big.bounds[0], big.bounds[3] - big.bounds[1]) / pt_per_unit * f <= 80), None)
    if unit is None:
        return {"sheet": sec["sheet"], "error": "לא נמצאה יחידת מודל שנותנת תרשים בגודל מבנה"}
    m_per_pt = UNIT_M[unit] / pt_per_unit
    k = m_per_pt ** 2
    diagrams, strips = [], 0
    for c in sorted(comps, key=lambda c: (round(c.bounds[1] / 2000), c.bounds[0])):
        members = [(col, g) for col, g in fills if g.representative_point().within(c.buffer(0.01))]
        if _is_strip(c, members):
            strips += 1
            continue
        by_cat: dict[str, list] = {}
        for col, g in members:
            by_cat.setdefault(legend[col], []).append(g)
        cats = {cat: unary_union(gs) for cat, gs in by_cat.items()}
        area = {cat: round(g.area * k, 3) for cat, g in cats.items()}
        double = {cat: round((sum(x.area for x in gs) - cats[cat].area) * k, 3) for cat, gs in by_cat.items()}
        overlaps = []
        names = sorted(cats)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                inter = cats[a].intersection(cats[b]).area * k
                if inter > MIN_POLY_M2:
                    overlaps.append({"a": a, "b": b, "m2": round(inter, 3)})
        prf = sorted((round(g.area * k, 3) for g in by_cat.get("protected_room_floor", [])), reverse=True)
        x0, y0, x1, y1 = c.bounds
        diagrams.append({
            "sheet": sec["sheet"], "bbox_pt": [round(v, 1) for v in (x0, y0, x1, y1)],
            "size_m": [round((x1 - x0) * m_per_pt, 2), round((y1 - y0) * m_per_pt, 2)],
            "area_m2": area, "protected_room_pieces_m2": prf,
            "double_counted_m2": {c_: v for c_, v in double.items() if v > MIN_POLY_M2}, "overlaps": overlaps,
            "polygons": sum(len(v) for v in by_cat.values()),
        })
    # repeated units: two diagrams with the same size and the same areas per category (a copy or a mirror image)
    for i, a in enumerate(diagrams):
        for j, b in enumerate(diagrams[:i]):
            if (abs(a["size_m"][0] - b["size_m"][0]) < 0.02 and abs(a["size_m"][1] - b["size_m"][1]) < 0.02
                    and a["area_m2"].keys() == b["area_m2"].keys()
                    and all(abs(a["area_m2"][x] - b["area_m2"][x]) < 0.02 for x in a["area_m2"])):
                a["same_as"] = j + 1
    return {"sheet": sec["sheet"], "tool": sec["tool"], "dwg": sec["dwg"], "model_unit": unit,
            "pt_per_model_unit": round(pt_per_unit, 6), "m_per_pt": m_per_pt,
            "scale_method": "Units Transform × FixedPage RenderTransform מתוך חבילת ה-DWFX; יחידת המודל נבחרה לפי סבירות מידות",
            "diagrams": diagrams, "table_strips": strips}


def classify(diagrams: list[dict]) -> dict:
    """Regulatory totals from the measured categories. Protected-room floor: each piece up to the 9 m² net service
    allowance is service, the rest primary (the drawing splits the room into such pieces)."""
    t = {"primary": 0.0, "service": 0.0, "uncounted": 0.0, "protected_room_floor": 0.0, "protected_room_walls": 0.0,
         "covered_service": 0.0, "primary_from_protected_room": 0.0}
    for d in diagrams:
        a = d["area_m2"]
        t["primary"] += a.get("primary", 0.0)
        t["covered_service"] += a.get("covered_service", 0.0)
        t["protected_room_walls"] += a.get("protected_room_walls", 0.0)
        t["uncounted"] += a.get("open_uncounted", 0.0)
        prf = a.get("protected_room_floor", 0.0)
        t["protected_room_floor"] += prf
        excess = max(0.0, prf - SERVICE_PROTECTED_NET_M2)
        t["primary_from_protected_room"] += excess
    t["primary"] += t["primary_from_protected_room"]
    t["service"] = t["protected_room_floor"] - t["primary_from_protected_room"] + t["protected_room_walls"] + t["covered_service"]
    t["total"] = t["primary"] + t["service"]
    return {k: round(v, 3) for k, v in t.items()}


def measure(src: Path) -> dict:
    data = src.read_bytes()
    z = zipfile.ZipFile(src)
    doc = pymupdf.open(str(src), filetype="xps")
    sheets = []
    for sec in _sections(z):
        if sec["tool"] and sec["sheet"] <= len(doc):
            r = measure_sheet(doc[sec["sheet"] - 1], sec)
            if r:
                sheets.append(r)
    diagrams = [d for s in sheets for d in s.get("diagrams", [])]
    return {"algorithm": ALGORITHM, "file_sha256": hashlib.sha256(data).hexdigest(), "sheets": sheets,
            "diagram_count": len(diagrams), "totals": classify(diagrams) if diagrams else None,
            "classification_note_he": f"רצפת ממ\"ד: עד {SERVICE_PROTECTED_NET_M2:g} מ\"ר נטו לכל ממ\"ד כשטח שירות, היתרה עיקרי"}


if __name__ == "__main__":
    print(json.dumps(measure(Path(sys.argv[1])), ensure_ascii=False))
