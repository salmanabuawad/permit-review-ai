"""Read a DWFX plan with the local image model: which views it has, the building height, and a few drawn items.
Runs on the AI PC, called by bbp_ai_agent.py — never on the app server.

The plan's labels are drawn as lines (SHX fonts), so there is no text to search; the sheets have to be looked at.
Two passes, both rendered from the vector DWFX (sharp at any zoom — a converted raster PDF is not):
1. overview tiles of every sheet -> the views on each (floor plan, section, elevation, roof, site plan) and whether
   parking, solar panels or a storage shed are drawn;
2. close-ups of the tiles with sections / elevations -> the level labels; the building height is the highest ridge
   level, accepted only when the ±0.00 label is in the same close-up or two close-ups give the same value.

A small model invents plausible numbers when an image is unreadable, so nothing is accepted on one blurry look.
Usage: python drawing_reader.py <plan.dwfx> [model] [llm_url]     prints JSON; needs PyMuPDF.
"""
from __future__ import annotations

import base64
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path

import pymupdf

MODEL = "ministral-3-8b-vision"
LLM = "http://127.0.0.1:8081/v1/chat/completions"
TILE_PX = 1024               # overview tile, long side
CLOSE_PX = 2000              # close-up, long side
MAX_TILES = 12               # per sheet (about)
MIN_TILE_PT = 1600           # a tile is never smaller than this: small sheets are looked at whole or in quarters
HEIGHT_RANGE = (2.0, 20.0)   # plausible building heights, m

VIEWS_Q = (
    "This image is one part of an architectural permit drawing sheet (Israel; Hebrew labels). Answer ONLY JSON: "
    '{"views": [view types clearly drawn in this image, from: "floor_plan", "section", "elevation", "roof_plan", '
    '"site_plan", "development_plan", "survey", "table", "detail"], "parking_spaces_marked": true|false, '
    '"solar_panels": "roof"|"ground"|"none", "storage_shed": true|false}. Use [] if the image is empty.')
LEVELS_Q = (
    "Zoomed part of an architectural section or elevation drawing. Read the LEVEL annotations (numbers like +3.20, "
    "+6.40, 0.00, each above a short line with a small triangle). Answer ONLY JSON: {\"levels\": [every level number you "
    "can read exactly], \"ridge_level\": number or null (the level written at the top of the roof), "
    "\"zero_level_absolute\": number or null (the absolute value in \"+0.00=NN.NN\"), \"roof_type\": "
    "\"tiled\"|\"flat\"|null}. Copy digits exactly; leave out anything not clearly readable.")


def log(msg: str) -> None:
    print(f"[drawing_reader {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def ask(png: bytes, question: str, model: str, url: str) -> dict:
    body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": question},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    text = json.loads(urllib.request.urlopen(req, timeout=600).read())["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def num(v) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(v)) if v is not None else None
    return float(m.group(0)) if m else None


def tiles(rect: pymupdf.Rect) -> list[pymupdf.Rect]:
    side = max(MIN_TILE_PT, math.sqrt(rect.width * rect.height / MAX_TILES))   # an even grid of squares ...
    if min(rect.width, rect.height) < side * 1.5:                 # ... but a long strip is cut along its length
        side = min(rect.width, rect.height)
    cols, rows = max(1, math.ceil(rect.width / side)), max(1, math.ceil(rect.height / side))
    w, h = rect.width / cols, rect.height / rows
    return [pymupdf.Rect(c * w, r * h, (c + 1) * w, (r + 1) * h) for r in range(rows) for c in range(cols)]


def blank(page, clip: pymupdf.Rect) -> bool:
    """True when a tiny render of the area is (nearly) all white: nothing drawn there."""
    z = 96 / max(clip.width, clip.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=clip, alpha=False, colorspace=pymupdf.csGRAY)
    dark = sum(1 for b in pix.samples if b < 235)
    return dark < max(8, len(pix.samples) // 400)


def render(page, clip: pymupdf.Rect, px: int) -> bytes:
    z = px / max(clip.width, clip.height)
    return page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=clip, alpha=False).tobytes("png")


def read(src: Path, model: str = MODEL, url: str = LLM) -> dict:
    t0 = time.time()
    doc = pymupdf.open(str(src), filetype="xps")
    out = {"model": model, "sheets": [], "views": {}, "parking": [], "solar": {}, "shed": [], "height": None,
           "levels_read": [], "calls": 0}
    elev_tiles = []
    for sno, page in enumerate(doc, 1):
        sheet = {"sheet": sno, "tiles": []}
        for i, clip in enumerate(tiles(page.rect)):
            if blank(page, clip):
                continue                                   # empty part of the sheet
            a = ask(render(page, clip, TILE_PX), VIEWS_Q, model, url)
            out["calls"] += 1
            log(f"sheet {sno} tile {i + 1}: {a}")
            views = [v for v in (a.get("views") or []) if isinstance(v, str)]
            sheet["tiles"].append({"tile": i + 1, "clip": [round(x, 1) for x in clip], "views": views,
                                   "parking": a.get("parking_spaces_marked"), "solar": a.get("solar_panels"),
                                   "shed": a.get("storage_shed")})
            for v in views:
                out["views"].setdefault(v, []).append({"sheet": sno, "tile": i + 1})
            if a.get("parking_spaces_marked") is True:
                out["parking"].append({"sheet": sno, "tile": i + 1})
            if a.get("solar_panels") in ("roof", "ground"):
                out["solar"].setdefault(a["solar_panels"], []).append({"sheet": sno, "tile": i + 1})
            if a.get("storage_shed") is True:
                out["shed"].append({"sheet": sno, "tile": i + 1})
            if {"section", "elevation"} & set(views):
                elev_tiles.append((sno, i + 1, clip))
        out["sheets"].append(sheet)

    # pass 2: close-ups of section / elevation tiles, 2 x 2 per tile
    ridges: list[dict] = []
    for sno, tno, clip in elev_tiles:
        page = doc[sno - 1]
        w, h = clip.width / 2, clip.height / 2
        for r in range(2):
            for c in range(2):
                sub = pymupdf.Rect(clip.x0 + c * w, clip.y0 + r * h, clip.x0 + (c + 1) * w, clip.y0 + (r + 1) * h)
                if blank(page, sub):
                    continue
                a = ask(render(page, sub, CLOSE_PX), LEVELS_Q, model, url)
                out["calls"] += 1
                log(f"sheet {sno} tile {tno}.{r * 2 + c + 1} levels: {a}")
                ridge, zero = num(a.get("ridge_level")), num(a.get("zero_level_absolute"))
                levels = [x for x in (num(v) for v in (a.get("levels") or [])) if x is not None]
                rec = {"sheet": sno, "tile": tno, "sub": r * 2 + c + 1, "ridge": ridge, "zero_abs": zero,
                       "roof": a.get("roof_type"), "levels": levels[:30]}
                out["levels_read"].append(rec)
                if ridge is not None and HEIGHT_RANGE[0] <= ridge <= HEIGHT_RANGE[1] and ridge in levels + [ridge]:
                    ridges.append(rec)
    # accept a ridge read with its ±0.00 label in the same close-up, or the same value from two close-ups
    seen: dict[float, list] = {}
    for rec in ridges:
        seen.setdefault(round(rec["ridge"], 2), []).append(rec)
    accepted = {v: recs for v, recs in seen.items() if len(recs) >= 2 or any(x["zero_abs"] for x in recs)}
    if accepted:
        top = max(accepted)
        roofs = [x["roof"] for recs in accepted.values() for x in recs if x["roof"]]
        out["height"] = {"value_m": top, "readings": accepted[top], "all_accepted": sorted(accepted),
                         "roof_type": max(set(roofs), key=roofs.count) if roofs else None,
                         "zero_abs": next((x["zero_abs"] for x in accepted[top] if x["zero_abs"]), None)}
    out["seconds"] = round(time.time() - t0, 1)
    return out


if __name__ == "__main__":
    print(json.dumps(read(Path(sys.argv[1]), *(sys.argv[2:4])), ensure_ascii=False))
