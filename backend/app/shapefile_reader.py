"""A minimal, dependency-free ESRI shapefile reader (polygons + dBASE attributes), streaming from a zip or a folder.

Enough for the Survey of Israel cadastre (parcels / blocks): shape types 5 / 15 / 25 (Polygon, PolygonZ, PolygonM);
rings follow the shapefile rule — outer rings clockwise, holes counter-clockwise. Records with a null shape are
yielded with geometry None. No external GIS library is needed on the server.
"""
from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path
from typing import Iterator

from shapely.geometry import LinearRing, MultiPolygon, Polygon

POLYGON_TYPES = {5, 15, 25}


def _open(src: Path, stem: str | None = None) -> tuple[io.BufferedIOBase, io.BufferedIOBase, str, str | None]:
    """(shp stream, dbf stream, encoding, prj text) from a .zip or a .shp path."""
    if src.suffix.lower() == ".zip":
        z = zipfile.ZipFile(src)
        names = {n.lower(): n for n in z.namelist()}
        shp = next(n for n in names if n.endswith(".shp") and (stem is None or Path(n).stem == stem.lower()))
        base = shp[:-4]
        cpg = names.get(base + ".cpg")
        enc = z.read(cpg).decode("ascii", "ignore").strip() if cpg else "cp1255"
        prj = names.get(base + ".prj")
        return (z.open(names[shp]), z.open(names[base + ".dbf"]), _enc(enc), z.read(prj).decode("ascii", "ignore") if prj else None)
    base = src.with_suffix("")
    cpg = base.with_suffix(".cpg")
    prj = base.with_suffix(".prj")
    return (open(src, "rb"), open(base.with_suffix(".dbf"), "rb"),
            _enc(cpg.read_text().strip() if cpg.exists() else "cp1255"), prj.read_text() if prj.exists() else None)


def _enc(name: str) -> str:
    n = name.lower().replace("-", "")
    return {"utf8": "utf-8", "65001": "utf-8", "1255": "cp1255", "ansi1255": "cp1255", "windows1255": "cp1255"}.get(n, name or "cp1255")


def _read(f, n: int) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise EOFError
    return b


def dbf_fields(f) -> tuple[int, int, list[tuple[str, str, int, int]]]:
    head = _read(f, 32)
    count, header_len, record_len = struct.unpack("<IHH", head[4:12])
    fields = []
    while True:
        d = _read(f, 1)
        if d == b"\r":
            break
        d += _read(f, 31)
        name = d[:11].split(b"\0", 1)[0].decode("ascii", "ignore")
        fields.append((name, chr(d[11]), d[16], d[17]))
    rest = header_len - 32 - 32 * len(fields) - 1
    if rest > 0:
        _read(f, rest)
    return count, record_len, fields


def _value(raw: bytes, kind: str, dec: int, enc: str):
    s = raw.decode(enc, "replace").strip().strip("\0")
    if kind in ("N", "F"):
        if not s or s.startswith("*"):
            return None
        try:
            return int(s) if dec == 0 and "." not in s else float(s)
        except ValueError:
            return None
    if kind == "L":
        return s[:1].upper() in ("T", "Y") if s else None
    return s or None


def polygon_from_parts(parts: list[int], points: list[tuple[float, float]]):
    rings = [points[a:b] for a, b in zip(parts, parts[1:] + [len(points)])]
    outers, holes = [], []
    for r in rings:
        if len(r) < 4:
            continue
        lr = LinearRing(r)
        (holes if lr.is_ccw else outers).append(lr)
    if not outers and holes:                     # some writers get the orientation wrong: treat all as outers
        outers, holes = holes, []
    polys = []
    for o in outers:
        po = Polygon(o)
        mine = [h for h in holes if po.contains(Polygon(h).representative_point())]
        polys.append(Polygon(o, mine))
    if not polys:
        return None
    g = MultiPolygon(polys)
    return g if g.is_valid else g.buffer(0)


def records(src: Path, stem: str | None = None) -> Iterator[tuple[dict, object]]:
    """(attributes, shapely geometry or None) for every record."""
    shp, dbf, enc, _ = _open(Path(src), stem)
    with shp, dbf:
        _read(shp, 100)
        count, record_len, fields = dbf_fields(dbf)
        for _ in range(count):
            rec = _read(dbf, record_len)
            attrs, pos = {}, 1
            for name, kind, size, dec in fields:
                attrs[name] = _value(rec[pos:pos + size], kind, dec, enc)
                pos += size
            try:
                _, words = struct.unpack(">ii", _read(shp, 8))
            except EOFError:
                return
            content = _read(shp, words * 2)
            stype = struct.unpack("<i", content[:4])[0]
            if stype not in POLYGON_TYPES:
                yield attrs, None
                continue
            nparts, npoints = struct.unpack("<ii", content[36:44])
            parts = list(struct.unpack(f"<{nparts}i", content[44:44 + 4 * nparts]))
            off = 44 + 4 * nparts
            flat = struct.unpack(f"<{2 * npoints}d", content[off:off + 16 * npoints])
            yield attrs, polygon_from_parts(parts, list(zip(flat[0::2], flat[1::2])))


def describe(src: Path, stem: str | None = None) -> dict:
    shp, dbf, enc, prj = _open(Path(src), stem)
    with shp, dbf:
        count, _, fields = dbf_fields(dbf)
    return {"records": count, "encoding": enc, "fields": [(n, k, s, d) for n, k, s, d in fields], "prj": (prj or "")[:300]}
