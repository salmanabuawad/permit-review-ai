"""The national cadastre (Survey of Israel, open data on data.gov.il): registered parcel and block boundaries.

Loaded from the published shapefiles by scripts/load_cadastre.py (EPSG:2039, the same grid as XPLAN). A parcel's
boundary here is the registered cadastral parcel — the strongest public geometry the system has for a case; XPLAN plan
cells are used only when a parcel is not in the cadastre. The snapshot date is part of every row's `source`.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

FIELDS = {"gush": ("GUSH_NUM", "GUSH", "GUSHNUM", "BLOCK"), "gush_suffix": ("GUSH_SUFFI", "GUSH_SUFFIX", "SUFFIX"),
          "helka": ("PARCEL", "HELKA", "PARCEL_NUM"), "legal_area": ("LEGAL_AREA", "SHETACH_RA", "AREA_LEGAL"),
          "status": ("STATUS_TEX", "STATUS_TXT", "STATUS"), "locality": ("LOCALITY_N", "LOCALITY_NAME", "YISHUV")}


def pick(attrs: dict, key: str):
    up = {k.upper(): v for k, v in attrs.items()}
    return next((up[f] for f in FIELDS[key] if f in up and up[f] not in (None, "")), None)


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parcel(s: Session, gush, helka) -> dict | None:
    """{'geometry': GeoJSON, 'legal_area', 'status', 'locality', 'source'} of a registered parcel, or None."""
    g, h = _int(gush), _int(helka)
    if g is None or h is None:
        return None
    pg = s.get_bind().dialect.name == "postgresql"
    geo = "COALESCE(ST_AsGeoJSON(geom, 2), geojson)" if pg else "geojson"      # geojson: rows written without PostGIS
    rows = s.execute(text(f"SELECT {geo}, legal_area, status, locality, source FROM cadastre_parcels "
                          "WHERE gush = :g AND helka = :h AND (gush_suffix IS NULL OR gush_suffix = 0)"), {"g": g, "h": h}).all()
    if len(rows) != 1 or not rows[0][0]:
        return None                       # unknown, or ambiguous (several rows): never guess
    r = rows[0]
    return {"geometry": json.loads(r[0]), "legal_area": r[1], "status": r[2], "locality": r[3], "source": r[4]}


def counts(s: Session) -> dict:
    try:
        return {"parcels": s.execute(text("SELECT count(*) FROM cadastre_parcels")).scalar(),
                "blocks": s.execute(text("SELECT count(*) FROM cadastre_blocks")).scalar()}
    except Exception:  # noqa: BLE001
        return {"parcels": 0, "blocks": 0}
