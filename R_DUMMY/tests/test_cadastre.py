"""National cadastre: shapefile reader (no GIS library), loader, parcel lookup, and discovery on the registered parcel."""
import io
import json
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app import cadastre, shapefile_reader as R
from app.db import SessionLocal
from app.main import app
from app.seed import seed

ROOT = Path(__file__).resolve().parents[2]


def write_shp(path: Path, rows: list[tuple[dict, list[list[tuple[float, float]]]]], fields=(("GUSH_NUM", 8), ("PARCEL", 6), ("STATUS_TEX", 20))):
    """A tiny Polygon shapefile + dBASE writer for the test (rings given in shapefile orientation)."""
    recs = b""
    for i, (_, rings) in enumerate(rows, 1):
        pts = [p for r in rings for p in r]
        parts, k = [], 0
        for r in rings:
            parts.append(k)
            k += len(r)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        body = struct.pack("<i4d2i", 5, min(xs), min(ys), max(xs), max(ys), len(rings), len(pts))
        body += struct.pack(f"<{len(parts)}i", *parts) + struct.pack(f"<{2 * len(pts)}d", *[c for p in pts for c in p])
        recs += struct.pack(">2i", i, len(body) // 2) + body
    head = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, (100 + len(recs)) // 2) + struct.pack("<2i4d4d", 1000, 5, 0, 0, 1, 1, 0, 0, 0, 0)
    path.with_suffix(".shp").write_bytes(head + recs)
    reclen = 1 + sum(w for _, w in fields)
    dbf = struct.pack("<4BIHH20x", 3, 126, 11, 27, len(rows), 32 + 32 * len(fields) + 1, reclen)
    for name, w in fields:
        dbf += name.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([w, 0]) + b"\0" * 14
    dbf += b"\r"
    for attrs, _ in rows:
        dbf += b" " + b"".join(str(attrs.get(n, "")).encode("cp1255").ljust(w)[:w] for n, w in fields)
    path.with_suffix(".dbf").write_bytes(dbf + b"\x1a")
    path.with_suffix(".cpg").write_text("1255")


SQUARE = [(154000, 613000), (154000, 613100), (154100, 613100), (154100, 613000), (154000, 613000)]   # clockwise
HOLE = [(154010, 613010), (154020, 613010), (154020, 613020), (154010, 613020), (154010, 613010)]       # counter-clockwise


def test_reader_holes_and_attributes(tmp_path):
    write_shp(tmp_path / "p", [({"GUSH_NUM": 2832, "PARCEL": 27, "STATUS_TEX": "מוסדר"}, [SQUARE, HOLE]),
                               ({"GUSH_NUM": 2832, "PARCEL": 28, "STATUS_TEX": "מוסדר"}, [SQUARE])])
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as f:
        for ext in (".shp", ".dbf", ".cpg"):
            f.write(tmp_path / ("p" + ext), "p" + ext)
    rows = list(R.records(z))
    assert len(rows) == 2 and rows[0][0]["STATUS_TEX"] == "מוסדר" and rows[0][0]["PARCEL"] == "27"
    assert rows[0][1].area == 100 * 100 - 10 * 10 and rows[1][1].area == 10000
    assert R.describe(z)["records"] == 2


def test_load_lookup_and_discovery(tmp_path, monkeypatch):
    seed(reset=True, samples=False)
    write_shp(tmp_path / "parcel_all", [({"GUSH_NUM": 2832, "PARCEL": 27, "STATUS_TEX": "מוסדר"}, [SQUARE])])
    sys.path.insert(0, str(ROOT / "scripts"))
    import load_cadastre
    load_cadastre.load("parcels", tmp_path / "parcel_all.shp", "test 2026-08-16")
    load_cadastre.load("parcels", tmp_path / "parcel_all.shp", "test 2026-08-16")        # reload replaces, no duplicates
    with SessionLocal() as s:
        r = cadastre.parcel(s, "2832", "27")
        assert r["status"] == "מוסדר" and r["geometry"]["type"] == "MultiPolygon" and cadastre.counts(s)["parcels"] == 1
        assert cadastre.parcel(s, "2832", "99") is None
    with TestClient(app) as c:
        h = {"X-User": "u-ha-reviewer"}
        assert c.get("/api/cadastre/parcel?gush=2832&helka=27", headers=h).json()["source"] == "test 2026-08-16"
        assert c.get("/api/cadastre/parcel?gush=2832&helka=99", headers=h).status_code == 404
    from app import plan_discovery as PD
    from app.models import PermitCase
    from tests.test_plan_discovery import fake_xplan
    with SessionLocal() as s:
        case = PermitCase(tenant_id="hof-ashkelon", case_number="cad-1", title="t", permit_type="new", gush="2832", helka="27",
                          declared={}, applicable_plans=["633-0723718"])
        s.add(case)
        s.commit()
        v = PD.refresh(s, case, fake_xplan())
        assert v["geometry_source"]["kind"] == "PARCEL_CADASTRE" and v["status"] == "CANDIDATES_FOUND"
