"""Planning jurisdiction: which committee is responsible for a parcel — from official boundaries, never from a name.

Data (Planning Administration public map service `gvulot_retzef`, EPSG:2039), loaded by the crawler as versioned datasets:
  planning_area  — "מרחבי תכנון": each local / regional / special planning area with its official code (CodeMT, the
                   prefix of plan numbers, e.g. 633 Hof Ashkelon) and type; district-administered (גלילי) areas have no
                   local committee — the district committee is responsible;
  municipality   — municipal jurisdiction boundaries (Interior Ministry);
  village        — village committee areas inside regional councils (the locality).
A planning area is linked to the national committee register by its own name (exact) or, failing that, by a unique
member municipality; anything else stays unlinked and is shown as such. A parcel's committee is decided only by the
spatial intersection of its registered cadastral boundary (Survey of Israel) with the planning areas:
  RESOLVED   — one planning area covers the parcel (≥ 99.5 % of its area) and is linked to a committee;
  AMBIGUOUS  — more than one planning area intersects the parcel materially: all candidates are returned;
  UNLINKED   — one area, but no committee linked (or a district-administered area);
  UNRESOLVED — parcel not in the cadastre, or no planning area intersects it.
Answers are cached per parcel and dataset versions; a dataset refresh makes the cache miss.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from shapely.geometry import mapping, shape
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import (CommitteeSettlement, GeoDataset, GeoQueryCache, JurisdictionArea, PlanningCommittee)

SERVICE = "https://ags.iplan.gov.il/arcgisiplan/rest/services/PlanningPublic/gvulot_retzef/MapServer"
HOSTS = {"ags.iplan.gov.il"}
LAYERS = {"planning_area": 3, "municipality": 1, "village": 2}
CFG = {"user_agent": "PermitReviewAI/1.0 (planning review; public data)", "max_bytes": 60 * 1024 * 1024, "timeout_s": 180}
COVER = 0.995            # share of the parcel inside one area to call it covered
MATERIAL = 0.005         # share below which a touching area is a boundary artefact, not a candidate
AREA_TYPES_HE = {"מקומי": "ועדה מקומית", "מרחבי": "ועדה מרחבית", "מיוחד": "ועדה מיוחדת", "גלילי": "שטח גלילי — הוועדה המחוזית"}
STATUS_HE = {"RESOLVED": "הוועדה זוהתה לפי גבול מרחב התכנון", "AMBIGUOUS": "החלקה חוצה כמה מרחבי תכנון — נדרשת בחירה",
             "UNLINKED": "מרחב התכנון זוהה אך אינו מקושר לוועדה ברשם", "UNRESOLVED": "לא ניתן לזהות את מרחב התכנון",
             "VERIFIED": "החלקה נמצאת במרחב התכנון של הוועדה שנבחרה", "MISMATCH": "החלקה אינה במרחב התכנון של הוועדה שנבחרה",
             "MANUAL_UNRESOLVED": "הוועדה נבחרה ידנית — התחום לא אומת"}


def norm(s) -> str:
    s = re.sub(r"[\"״׳'\s\-–־.,()]", "", str(s or ""))
    for pre in ("מועצהאזורית", "מועצהמקומית", "עיריית", "מא", "ממ", "עירייה"):
        if s.startswith(pre) and len(s) > len(pre) + 1:
            s = s[len(pre):]
    return s


def _ms_date(v):
    try:
        return dt.datetime.fromtimestamp(int(v) / 1000, dt.timezone.utc).date() if v not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------- loading (crawler)

def fetch_layer(kind: str, fetcher=None, sleep=None, batch: int = 10) -> list[dict]:
    """All features of a layer with geometry in EPSG:2039 (small batches; one request per delay)."""
    import time
    from urllib.parse import urlencode

    from .plan_discovery import esri_to_geojson
    from .source_monitor import fetch as F
    fetcher, sleep = fetcher or F.fetch, sleep or time.sleep
    lyr = LAYERS[kind]

    def q(params):
        r = fetcher(f"{SERVICE}/{lyr}/query?" + urlencode({**params, "f": "json"}), CFG, HOSTS)
        if r.status != "ok":
            raise ValueError(f"{kind}: {r.status} {r.message or r.http_status}")
        d = json.loads(r.body)
        if "error" in d:
            raise ValueError(f"{kind}: {d['error']}")
        return d
    ids = sorted(q({"where": "1=1", "returnIdsOnly": "true"}).get("objectIds") or [])
    out = []
    def get(chunk):
        return q({"objectIds": ",".join(map(str, chunk)), "outFields": "*", "returnGeometry": "true", "outSR": 2039})
    for i in range(0, len(ids), batch):
        sleep(1.0)
        try:
            d = get(ids[i:i + batch])
        except ValueError:                                   # large polygons: one feature per request, one retry each
            d = {"features": []}
            for one in ids[i:i + batch]:
                for attempt in (1, 2):
                    sleep(1.0 * attempt)
                    try:
                        d["features"] += get([one]).get("features") or []
                        break
                    except ValueError:
                        if attempt == 2:
                            raise
        for f in d.get("features") or []:
            g = f.get("geometry")
            out.append({"attrs": f.get("attributes") or {}, "geometry": esri_to_geojson(g) if g else None})
    return out


def _row(kind: str, a: dict) -> dict:
    if kind == "planning_area":
        return {"code": str(a.get("CodeMT") or "").strip() or None, "name_he": (a.get("MT_Heb") or "").strip() or None,
                "area_type": (a.get("Sug_MT") or "").strip() or None, "district": a.get("Machoz"),
                "parent_name": (a.get("Muni_In_MT") or "").strip() or None, "sign_date": _ms_date(a.get("SIGN_DATE"))}
    if kind == "municipality":
        return {"code": str(a.get("CR_PNIM") or "").strip() or None, "name_he": (a.get("Muni_Heb") or "").strip() or None,
                "area_type": a.get("Sug_Muni"), "district": a.get("Machoz"), "parent_name": None, "sign_date": _ms_date(a.get("Sign_Date"))}
    return {"code": str(a.get("CV_PNIM") or "").strip() or None, "name_he": (a.get("Vaad_Heb") or "").strip() or None,
            "area_type": a.get("Sug_Muni"), "district": a.get("Machoz"), "parent_name": (a.get("Muni_Heb") or "").strip() or None,
            "sign_date": _ms_date(a.get("Sign_Date"))}


def load(s: Session, kind: str, features: list[dict]) -> dict:
    """Store a layer as a new dataset version; the previous active version of that layer is superseded (kept)."""
    body = json.dumps([[f["attrs"], f["geometry"]] for f in features], sort_keys=True, ensure_ascii=False, default=str)
    version = hashlib.sha256(body.encode()).hexdigest()[:16]
    name = f"iplan.gvulot_retzef.{kind}"
    cur = s.scalars(select(GeoDataset).where(GeoDataset.name == name, GeoDataset.active.is_(True))).first()
    if cur and cur.version == version:
        return {"dataset": cur.id, "version": version, "changed": False, "features": cur.features}
    now = dt.datetime.now(dt.timezone.utc)
    ds = GeoDataset(name=name, source_url=f"{SERVICE}/{LAYERS[kind]}", version=version, features=len(features), fetched_at=now,
                    active=True, meta={"layer": LAYERS[kind], "kind": kind})
    s.add(ds)
    s.flush()
    pg = s.get_bind().dialect.name == "postgresql"
    for f in features:
        if not f["geometry"]:
            continue
        a = JurisdictionArea(dataset_id=ds.id, kind=kind, attrs={k: v for k, v in f["attrs"].items() if not k.lower().startswith("shape")},
                             geojson=None if pg else json.dumps(f["geometry"]), **_row(kind, f["attrs"]))
        s.add(a)
        s.flush()
        if pg:
            s.execute(text("UPDATE jurisdiction_areas SET geom = ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:g), 2039))) "
                           "WHERE id = :i"), {"g": json.dumps(f["geometry"]), "i": a.id})
    if cur:
        cur.active, cur.superseded_at = False, now
    s.flush()
    if kind == "planning_area":
        link_committees(s, ds.id)
    s.execute(text("DELETE FROM geo_query_cache"))
    s.commit()
    return {"dataset": ds.id, "version": version, "changed": True, "features": len(features)}


# Planning-area name (Planning Administration) → committee name (national register), where the two official lists spell
# the same committee differently. Curated and reviewable; checked by hand on 2026-11-27 against both lists.
ALIASES = {"שהם": "שוהם", "הגליל התחתון": "הגליל תחתון", "הערבה התיכונה": "ערבה תיכונה", "יהוד- נווה אפרים": "יהוד",
           "מודיעין": "מודיעין-מכבים-רעות"}


def link_committees(s: Session, dataset_id: int) -> dict:
    """Planning area → committee register: exact name, else a unique committee whose settlements include the area's
    municipality. District-administered areas get no committee. Codes are written back to the committee."""
    committees = list(s.scalars(select(PlanningCommittee)))
    by_name: dict[str, list] = {}
    for c in committees:
        by_name.setdefault(norm(c.name_he), []).append(c)
    by_member: dict[str, set] = {}
    for st in s.scalars(select(CommitteeSettlement)):
        by_member.setdefault(norm(st.name_he), set()).add(st.committee_id)
    out = {"name_exact": 0, "alias_curated": 0, "member_municipality": 0, "district_administered": 0, "unlinked": 0}
    codes: dict[str, set] = {}
    for a in s.scalars(select(JurisdictionArea).where(JurisdictionArea.dataset_id == dataset_id, JurisdictionArea.kind == "planning_area")):
        a.committee_id, a.link_method = None, None
        if a.area_type == "גלילי":
            a.link_method = "district_administered"
        elif len(by_name.get(norm(a.name_he), [])) == 1:
            a.committee_id, a.link_method = by_name[norm(a.name_he)][0].id, "name_exact"
        elif (a.name_he or "").strip() in ALIASES and len(by_name.get(norm(ALIASES[a.name_he.strip()]), [])) == 1:
            a.committee_id, a.link_method = by_name[norm(ALIASES[a.name_he.strip()])][0].id, "alias_curated"
        else:
            members = [m for m in re.split(r"[,;/]", a.parent_name or "") if m.strip()]
            cands = set.union(*[by_member.get(norm(m), set()) for m in members]) if members else set()
            if len(cands) == 1:
                a.committee_id, a.link_method = next(iter(cands)), "member_municipality"
            else:
                a.link_method = "unlinked"
        out[a.link_method] += 1
        if a.committee_id and a.code:
            codes.setdefault(a.committee_id, set()).add(a.code)
    for c in committees:
        c.planning_area_codes = sorted(codes.get(c.id, set())) or None
    s.flush()
    return out


def run_refresh(session_factory, fetcher=None, sleep=None) -> dict:
    out = {}
    for kind in ("planning_area", "municipality", "village"):
        feats = fetch_layer(kind, fetcher, sleep)
        with session_factory() as s:
            out[kind] = load(s, kind, feats)
    return out


# ---------------------------------------------------------------- queries

def versions(s: Session) -> str:
    rows = s.execute(select(GeoDataset.name, GeoDataset.version).where(GeoDataset.active.is_(True)).order_by(GeoDataset.name)).all()
    return ";".join(f"{n.rsplit('.', 1)[-1]}={v}" for n, v in rows)


def _intersecting(s: Session, kind: str, geo: dict) -> list[tuple[JurisdictionArea, float]]:
    """(area, share of the parcel inside it) for active areas of `kind` that intersect the parcel."""
    pg = s.get_bind().dialect.name == "postgresql"
    active = select(GeoDataset.id).where(GeoDataset.active.is_(True), GeoDataset.name == f"iplan.gvulot_retzef.{kind}")
    if pg:
        rows = s.execute(text(
            "WITH p AS (SELECT ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:g), 2039)) AS g) "
            "SELECT a.id, ST_Area(ST_Intersection(a.geom, p.g)) / NULLIF(ST_Area(p.g), 0) FROM jurisdiction_areas a, p "
            "WHERE a.kind = :k AND a.dataset_id IN (SELECT id FROM geo_datasets WHERE active AND name = :n) AND a.geom && p.g "
            "AND ST_Intersects(a.geom, p.g)"), {"g": json.dumps(geo), "k": kind, "n": f"iplan.gvulot_retzef.{kind}"}).all()
        got = {r[0]: float(r[1] or 0) for r in rows}
        areas = {a.id: a for a in s.scalars(select(JurisdictionArea).where(JurisdictionArea.id.in_(list(got))))} if got else {}
        return sorted(((areas[i], sh) for i, sh in got.items()), key=lambda x: -x[1])
    p = shape(geo)
    out = []
    for a in s.scalars(select(JurisdictionArea).where(JurisdictionArea.kind == kind, JurisdictionArea.dataset_id.in_(active))):
        g = shape(json.loads(a.geojson))
        if g.intersects(p):
            out.append((a, g.intersection(p).area / p.area))
    return sorted(out, key=lambda x: -x[1])


def _area_dict(s: Session, a: JurisdictionArea, share: float) -> dict:
    c = s.get(PlanningCommittee, a.committee_id) if a.committee_id else None
    return {"area_id": a.id, "code": a.code, "name_he": a.name_he, "area_type": a.area_type,
            "area_type_he": AREA_TYPES_HE.get(a.area_type or "", a.area_type), "district": a.district, "share": round(share, 4),
            "committee_id": a.committee_id, "committee_name": c.name_he if c else None, "link_method": a.link_method,
            "sign_date": a.sign_date and a.sign_date.isoformat()}


def discover(s: Session, gush, helka, use_cache: bool = True) -> dict:
    """Path B: the committee responsible for block / parcel, from the cadastre and the planning-area boundaries."""
    from . import cadastre
    g, h = cadastre._int(gush), cadastre._int(helka)
    if g is None or h is None or g <= 0 or h <= 0:
        return {"status": "UNRESOLVED", "status_he": "מספר גוש / חלקה לא תקין", "reason": "invalid_identifier", "candidates": []}
    ver = versions(s)
    key = f"jurisdiction:{g}:{h}"
    if use_cache:
        hit = s.get(GeoQueryCache, key)
        if hit and hit.versions == ver:
            return {**hit.result, "cached": True}
    parcel = cadastre.parcel(s, g, h)
    if parcel is None:
        res = {"status": "UNRESOLVED", "status_he": "החלקה לא נמצאה בקדסטר (או שיש לה יותר מרשומה אחת)", "reason": "parcel_not_found",
               "candidates": [], "gush": str(g), "helka": str(h), "datasets": ver}
    else:
        geo = parcel.pop("geometry")
        cands = [(a, sh) for a, sh in _intersecting(s, "planning_area", geo) if sh >= MATERIAL]
        munis = [(a, sh) for a, sh in _intersecting(s, "municipality", geo) if sh >= MATERIAL]
        vill = [(a, sh) for a, sh in _intersecting(s, "village", geo) if sh >= MATERIAL]
        if not cands:
            status, reason = "UNRESOLVED", "no_planning_area"
        elif len(cands) > 1 or cands[0][1] < COVER:
            status, reason = "AMBIGUOUS", "multiple_or_partial"
        elif not cands[0][0].committee_id:
            status, reason = "UNLINKED", cands[0][0].link_method
        else:
            status, reason = "RESOLVED", None
        res = {"status": status, "status_he": STATUS_HE[status], "reason": reason, "gush": str(g), "helka": str(h),
               "parcel": {**parcel, "area_m2": round(shape(geo).area, 1)},
               "candidates": [_area_dict(s, a, sh) for a, sh in cands],
               "municipalities": [{"name_he": a.name_he, "code": a.code, "share": round(sh, 4)} for a, sh in munis],
               "localities": [{"name_he": a.name_he, "council": a.parent_name, "share": round(sh, 4)} for a, sh in vill]
               or ([{"name_he": parcel.get("locality"), "council": None, "share": None, "source": "cadastre"}] if parcel.get("locality") else []),
               "committee_id": cands[0][0].committee_id if status == "RESOLVED" else None, "datasets": ver,
               "method": "ST_Intersects(cadastral parcel, planning areas) in EPSG:2039"}
    s.merge(GeoQueryCache(key=key, versions=ver, result=res, created_at=dt.datetime.now(dt.timezone.utc)))
    s.commit()
    return {**res, "cached": False}


def verify(s: Session, committee_id: str, gush, helka) -> dict:
    """Path A: is the parcel inside the selected committee's planning area(s)?"""
    d = discover(s, gush, helka)
    c = s.get(PlanningCommittee, committee_id)
    if c is None:
        return {**d, "status": "UNRESOLVED", "status_he": "ועדה לא מוכרת", "selected_committee_id": committee_id}
    mine = [x for x in d.get("candidates", []) if x["committee_id"] == committee_id]
    share = sum(x["share"] for x in mine)
    if d["status"] == "UNRESOLVED":
        status = "UNRESOLVED"
    elif mine and share >= COVER:
        status = "VERIFIED"
    elif mine:
        status = "AMBIGUOUS"
    elif any(x["committee_id"] for x in d.get("candidates", [])):
        status = "MISMATCH"
    else:
        status = "UNRESOLVED"
    return {**d, "status": status, "status_he": STATUS_HE.get(status, d.get("status_he")), "selected_committee_id": committee_id,
            "selected_committee_name": c.name_he, "selected_share": round(share, 4),
            "committee_id": committee_id if status == "VERIFIED" else d.get("committee_id")}


def counts(s: Session) -> dict:
    rows = s.execute(select(GeoDataset.name, GeoDataset.version, GeoDataset.features, GeoDataset.fetched_at)
                     .where(GeoDataset.active.is_(True))).all()
    links = dict(s.execute(select(JurisdictionArea.link_method, text("count(*)")).join(GeoDataset, GeoDataset.id == JurisdictionArea.dataset_id)
                           .where(GeoDataset.active.is_(True), JurisdictionArea.kind == "planning_area")
                           .group_by(JurisdictionArea.link_method)).all())
    return {"datasets": [{"name": n, "version": v, "features": f, "fetched_at": t.isoformat()} for n, v, f, t in rows], "links": links}


__all__ = ["discover", "verify", "load", "link_committees", "run_refresh", "fetch_layer", "counts", "STATUS_HE", "mapping"]
