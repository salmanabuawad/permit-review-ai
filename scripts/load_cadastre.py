"""Load the Survey of Israel cadastre shapefiles (data.gov.il: "חלקות shape" parcel_all.zip, "גושים shape"
sub_gush_all.zip) into cadastre_parcels / cadastre_blocks. Replaces the table's rows from the same source tag only.

Usage (on the server, as user permit):
    python scripts/load_cadastre.py parcels <parcel_all.zip> --source "mapi parcel_all 2026-08-16"
    python scripts/load_cadastre.py blocks  <sub_gush_all.zip> --source "mapi sub_gush_all 2026-08-16"
    python scripts/load_cadastre.py describe <zip>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from shapely import wkb  # noqa: E402
from shapely.geometry import mapping  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import cadastre as C  # noqa: E402
from app import shapefile_reader as R  # noqa: E402
from app.db import SessionLocal  # noqa: E402

BATCH = 5000


def load(kind: str, src: Path, source: str) -> None:
    table = "cadastre_parcels" if kind == "parcels" else "cadastre_blocks"
    t0, n, skipped = time.time(), 0, 0
    with SessionLocal() as s:
        pg = s.get_bind().dialect.name == "postgresql"
        s.execute(text(f"DELETE FROM {table} WHERE source = :s"), {"s": source})
        cols = ["gush", "gush_suffix", "legal_area", "status", "locality", "attrs", "source"] + (["helka"] if kind == "parcels" else [])
        geo_sql = "ST_Multi(ST_GeomFromWKB(decode(:wkb, 'hex'), 2039))" if pg else ":geojson"
        geo_col = "geom" if pg else "geojson"
        sql = text(f"INSERT INTO {table} ({', '.join(cols)}, {geo_col}) VALUES ({', '.join(':' + c for c in cols)}, {geo_sql})")
        batch = []
        for attrs, geom in R.records(src):
            gush = C._int(C.pick(attrs, "gush"))
            helka = C._int(C.pick(attrs, "helka")) if kind == "parcels" else 0
            if gush is None or helka is None or geom is None or geom.is_empty:
                skipped += 1
                continue
            row = {"gush": gush, "gush_suffix": C._int(C.pick(attrs, "gush_suffix")), "legal_area": C.pick(attrs, "legal_area"),
                   "status": (str(C.pick(attrs, "status")) if C.pick(attrs, "status") is not None else None),
                   "locality": C.pick(attrs, "locality"), "attrs": json.dumps(attrs, ensure_ascii=False, default=str), "source": source}
            if kind == "parcels":
                row["helka"] = helka
            if pg:
                row["wkb"] = wkb.dumps(geom, hex=True)
            else:
                row["geojson"] = json.dumps(mapping(geom))
            batch.append(row)
            if len(batch) >= BATCH:
                s.execute(sql, batch)
                s.commit()
                n += len(batch)
                batch = []
                print(f"{n} rows, {time.time() - t0:.0f}s", flush=True)
        if batch:
            s.execute(sql, batch)
            n += len(batch)
        s.commit()
        if pg:
            s.execute(text(f"ANALYZE {table}"))
            s.commit()
    print(f"loaded {n} {kind} ({skipped} skipped) from {src.name} in {time.time() - t0:.0f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=("parcels", "blocks", "describe"))
    ap.add_argument("src", type=Path)
    ap.add_argument("--source", default=None)
    a = ap.parse_args()
    if a.kind == "describe":
        print(json.dumps(R.describe(a.src), ensure_ascii=False, indent=1))
        for i, (attrs, g) in enumerate(R.records(a.src)):
            print(attrs, g and g.bounds)
            if i >= 2:
                break
        return
    load(a.kind, a.src, a.source or f"mapi {a.src.stem}")


if __name__ == "__main__":
    main()
