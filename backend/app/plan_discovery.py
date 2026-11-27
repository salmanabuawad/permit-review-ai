"""XPLAN plan discovery (Planning Administration public map service) — a job of the restricted crawler process.

What it answers, for one case, from the official XPLAN MapServer (EPSG:2039):
  * declared plans: does each plan the applicant declared exist in XPLAN, with which status, publication date
    (רשומות), subtype, committee and Mavat link;
  * the geometry the query uses: the case's verified parcel geometry (a verified regulatory entry) if there is one;
    otherwise the declared plan's land-use cell (תא שטח) polygon read from XPLAN — a plan cell, not a registered
    parcel boundary, and labelled so;
  * plans whose blue line intersects that geometry, each COVERS (contains it, to within the tolerance) or PARTIAL;
  * land-use cells (ייעודי קרקע) of any plan that intersect it.
Every plan found is a candidate for the professional, never legal activation: XPLAN shows online plans only, and older
or paper plans may be missing (coverage_complete is always False).

Only the geometry and plan numbers leave the server — no application files, names or identifiers. The app process
queues the job (POST /discover-plans); the crawler, whose egress the firewall restricts to public addresses, runs it.
Network use also needs BBP_XPLAN_ENABLED=true in the server configuration.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from urllib.parse import urlencode, urlsplit

from shapely.geometry import LinearRing, MultiPolygon, Polygon, mapping
from sqlalchemy import select

from .models import ParcelPlanDiscovery, PermitCase, Property
from .regulatory import digest, norm, polygon, property_context
from .source_monitor import fetch as F

BASE = "https://ags.iplan.gov.il/arcgisiplan/rest/services/PlanningPublic/Xplan/MapServer"
HOSTS = {"ags.iplan.gov.il"}
CFG = {"user_agent": "PermitReviewAI/1.0 (planning review; public data)", "max_bytes": 8 * 1024 * 1024, "timeout_s": 25}
TOLERANCE_M = 0.5          # COVERS = the plan contains the geometry shrunk by this much (edges shared with the plan)
MAX_URL_GEOMETRY = 60000   # characters of geometry JSON in a (POST) query; simplified (and recorded) beyond that
RETRY_S = 3
MAX_PAGES = 10
PAGE = 500
PLAN_FIELDS = "pl_number,pl_name,station_desc,internet_short_status,pl_date_8,entity_subtype_desc,pl_url,ja_concat,plan_county_name"
CELL_FIELDS = "pl_number,num,mavat_name,station_desc,legal_area"

STATUS_HE = {"NOT_DISCOVERED": "טרם בוצע איתור", "QUEUED": "ממתין לסורק", "RUNNING": "הסורק מאתר", "DISABLED": "איתור ב־XPLAN כבוי",
             "MISSING_GEOMETRY": "אין גבול מגרש מאומת ואין תא שטח בתכנית המוצהרת", "UNAVAILABLE": "שירות XPLAN לא זמין",
             "PARTIAL": "איתור חלקי", "CANDIDATES_FOUND": "נמצאו תכניות מועמדות", "FAILED": "האיתור נכשל"}


class XplanError(ValueError):
    pass


def enabled() -> bool:
    return os.getenv("BBP_XPLAN_ENABLED", "false").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------- service access

def query(path: str, params: dict, fetcher) -> dict:
    """GET for short queries; POST when a geometry is sent (the service rejects long query strings with 404)."""
    params = {**params, "f": "json"}
    for attempt in (1, 2):
        if "geometry" in params:
            r = fetcher(BASE + path, CFG, HOSTS, form=params)
        else:
            r = fetcher(BASE + path + "?" + urlencode(params), CFG, HOSTS)
        if r.status != "unreachable" or attempt == 2:
            break
        time.sleep(RETRY_S)                                   # one retry: the service is sometimes slow to answer
    if r.status != "ok":
        raise XplanError(f"XPLAN {r.status}: {r.message or r.http_status}")
    try:
        d = json.loads(r.body)
    except ValueError as e:
        raise XplanError("XPLAN returned non-JSON") from e
    if not isinstance(d, dict) or "error" in d:
        raise XplanError(f"XPLAN API error: {str((d or {}).get('error'))[:200]}" if isinstance(d, dict) else "XPLAN API error")
    return d


def layers(fetcher) -> dict:
    """The blue-line and land-use layer ids, recognised by their fields — never by position or by guessing."""
    root = query("", {}, fetcher)
    found: dict[str, int] = {}
    for lyr in root.get("layers") or []:
        if not isinstance(lyr.get("id"), int) or lyr.get("subLayerIds") or lyr.get("geometryType") not in (None, "esriGeometryPolygon"):
            continue
        meta = query(f"/{lyr['id']}", {}, fetcher)
        if meta.get("geometryType") != "esriGeometryPolygon":
            continue
        names = {(f.get("name") or "").lower() for f in meta.get("fields") or []}
        if {"pl_number", "station_desc", "pl_url"} <= names and "blue" not in found:
            found["blue"] = lyr["id"]
        elif {"pl_number", "num", "mavat_name"} <= names and "landuse" not in found:
            found["landuse"] = lyr["id"]
    if "blue" not in found:
        raise XplanError("XPLAN schema changed: no plan blue-line layer with pl_number / station_desc / pl_url")
    return found


def paged(path: str, params: dict, fetcher) -> tuple[list[dict], bool]:
    """All features (bounded); second value False when the page limit cut the answer."""
    out, offset = [], 0
    for _ in range(MAX_PAGES):
        d = query(path, {**params, "resultOffset": offset, "resultRecordCount": PAGE}, fetcher)
        feats = d.get("features")
        if not isinstance(feats, list):
            raise XplanError("XPLAN answer has no features")
        out += feats
        if not d.get("exceededTransferLimit"):
            return out, True
        if not feats:
            raise XplanError("XPLAN empty page with exceededTransferLimit")
        offset += len(feats)
    return out, False


# ---------------------------------------------------------------- geometry

def esri_to_geojson(g: dict) -> dict:
    """Esri polygon rings (outer clockwise, holes counter-clockwise) to a GeoJSON (Multi)Polygon."""
    outers, holes = [], []
    for ring in (g or {}).get("rings") or []:
        if len(ring) < 4:
            continue
        lr = LinearRing([tuple(p[:2]) for p in ring])
        (holes if lr.is_ccw else outers).append(lr)
    polys = []
    for o in outers:
        po = Polygon(o)
        polys.append(Polygon(o, [h for h in holes if po.contains(Polygon(h).representative_point())]))
    if not polys:
        raise XplanError("XPLAN feature has no polygon rings")
    geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    if not geom.is_valid:
        geom = geom.buffer(0)
    return mapping(geom)


def esri_polygon(geom) -> tuple[str, float]:
    """A shapely geometry as an Esri polygon JSON short enough for a GET query; returns (json, simplified_m)."""
    tol = 0.0
    while True:
        g = geom.simplify(tol, preserve_topology=True) if tol else geom
        polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        rings = []
        for p in polys:
            rings.append([[round(x, 2), round(y, 2)] for x, y in reversed(p.exterior.coords)])        # outer clockwise
            rings += [[[round(x, 2), round(y, 2)] for x, y in i.coords] for i in p.interiors]
        s = json.dumps({"rings": rings, "spatialReference": {"wkid": 2039}}, separators=(",", ":"))
        if len(s) <= MAX_URL_GEOMETRY or tol >= 8:
            return s, tol
        tol = 0.5 if not tol else tol * 2


def _ms_date(v) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(v) / 1000, dt.timezone.utc).date().isoformat() if v not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None


def _mavat(url) -> str | None:
    u = str(url or "")
    return u if urlsplit(u).scheme == "https" and urlsplit(u).hostname == "mavat.iplan.gov.il" else None


def _plan(a: dict) -> dict:
    return {"plan": str(a.get("pl_number") or "").strip(), "name": a.get("pl_name"), "status": a.get("station_desc"),
            "stage": a.get("internet_short_status"), "published": _ms_date(a.get("pl_date_8")),
            "subtype": a.get("entity_subtype_desc"), "committee": a.get("ja_concat"), "locality": a.get("plan_county_name"),
            "url": _mavat(a.get("pl_url"))}


# ---------------------------------------------------------------- queries

def lookup_plans(numbers: list[str], lyr: dict, fetcher) -> list[dict]:
    """Each declared plan as XPLAN knows it (found False when XPLAN has no online plan with that number)."""
    out = []
    for n in numbers[:20]:
        n = str(n).strip()
        if not n or len(n) > 60 or "'" in n:
            out.append({"plan": n, "found": False, "note": "מספר תכנית לא תקין"})
            continue
        feats, _ = paged(f"/{lyr['blue']}/query", {"where": f"pl_number='{n}'", "outFields": PLAN_FIELDS, "returnGeometry": "false"}, fetcher)
        rows = [_plan(f.get("attributes") or {}) for f in feats]
        out.append({**rows[0], "found": True, "editions": len(rows)} if rows else {"plan": n, "found": False})
    return out


def plan_cell(plan: str, cell: str, lyr: dict, fetcher) -> dict | None:
    """The polygon and designation of cell `cell` in plan `plan` (approved edition when several), or None."""
    if "landuse" not in lyr or "'" in plan:
        return None
    feats, _ = paged(f"/{lyr['landuse']}/query", {"where": f"pl_number='{plan}'", "outFields": CELL_FIELDS,
                                                   "returnGeometry": "true", "outSR": 2039}, fetcher)
    hits = [f for f in feats if norm((f.get("attributes") or {}).get("num")) == norm(cell)]
    approved = [f for f in hits if (f.get("attributes") or {}).get("station_desc") == "אישור"]
    hits = approved or hits
    if len(hits) != 1:
        return None
    a = hits[0]["attributes"]
    return {"geometry": esri_to_geojson(hits[0].get("geometry")), "plan": plan, "cell": str(a.get("num")),
            "designation": a.get("mavat_name"), "status": a.get("station_desc"), "legal_area": a.get("legal_area")}


def discover(geo: dict, fetcher=None, lyr: dict | None = None) -> dict:
    """Plans whose blue line intersects `geo` (COVERS / PARTIAL) and land-use cells that intersect it."""
    fetcher = fetcher or F.fetch
    try:
        lyr = lyr or layers(fetcher)
    except Exception as e:  # noqa: BLE001 — reported, not raised
        return {"status": "UNAVAILABLE", "plans": [], "land_use": [], "errors": [str(e)[:300]], "coverage_complete": False}
    g = polygon(geo)
    inner = g.buffer(-TOLERANCE_M) if g.buffer(-TOLERANCE_M).area > 0 else g
    gq, simp = esri_polygon(g)
    iq, _ = esri_polygon(inner)
    base = {"geometryType": "esriGeometryPolygon", "inSR": 2039, "returnGeometry": "false"}
    errors: list[str] = []
    plans: dict[str, dict] = {}
    try:
        feats, complete = paged(f"/{lyr['blue']}/query", {**base, "geometry": gq, "spatialRel": "esriSpatialRelIntersects",
                                                          "outFields": PLAN_FIELDS}, fetcher)
        if not complete:
            errors.append("plans: page limit")
        for f in feats:
            p = _plan(f.get("attributes") or {})
            if p["plan"] and len(p["plan"]) <= 120:
                plans.setdefault(norm(p["plan"]), {**p, "relation": "PARTIAL", "source": f"{BASE}/{lyr['blue']}"})
        # esriSpatialRelWithin = the query geometry lies within the plan (verified live 2026-11-27: Contains returned
        # nothing for a cell inside its own plan; Within returned that plan)
        covers, _ = paged(f"/{lyr['blue']}/query", {**base, "geometry": iq, "spatialRel": "esriSpatialRelWithin",
                                                    "outFields": "pl_number"}, fetcher)
        for f in covers:
            k = norm((f.get("attributes") or {}).get("pl_number"))
            if k in plans:
                plans[k]["relation"] = "COVERS"
    except Exception as e:  # noqa: BLE001
        errors.append(f"plans: {str(e)[:250]}")
    cells: list[dict] = []
    if "landuse" in lyr:
        try:
            feats, complete = paged(f"/{lyr['landuse']}/query", {**base, "geometry": iq, "spatialRel": "esriSpatialRelIntersects",
                                                                 "outFields": CELL_FIELDS}, fetcher)
            if not complete:
                errors.append("land use: page limit")
            seen = set()
            for f in feats:
                a = f.get("attributes") or {}
                k = (norm(a.get("pl_number")), norm(a.get("num")), a.get("mavat_name"))
                if k not in seen:
                    seen.add(k)
                    cells.append({"plan": a.get("pl_number"), "cell": a.get("num"), "designation": a.get("mavat_name"),
                                  "status": a.get("station_desc"), "legal_area": a.get("legal_area")})
        except Exception as e:  # noqa: BLE001
            errors.append(f"land use: {str(e)[:250]}")
    ordered = sorted(plans.values(), key=lambda p: (p["relation"] != "COVERS", p["published"] or "9999", p["plan"]))
    return {"status": "PARTIAL" if errors else "CANDIDATES_FOUND", "plans": ordered, "land_use": cells, "errors": errors,
            "tolerance_m": TOLERANCE_M, "geometry_simplified_m": simp, "service": BASE, "coverage_complete": False}


# ---------------------------------------------------------------- case jobs

def _cells_for(s, case: PermitCase) -> list[tuple[str, str, str]]:
    """(plan, cell, how known) candidates: the declared lot / plot, else the authority ledger's only cell for the block."""
    plans = [p for p in (case.applicable_plans or []) if isinstance(p, str) and p.strip()]
    d = case.declared or {}
    lot = d.get("lot") or d.get("plot") or d.get("cell")
    if lot:
        return [(p, str(lot), "declared") for p in plans]
    if not case.gush:
        return []
    rows = [r for r in s.scalars(select(Property).where(Property.tenant_id == case.tenant_id, Property.gush == case.gush,
                                                        Property.cell.is_not(None)))
            if norm(r.plan) in {norm(p) for p in plans}]
    return [(rows[0].plan, rows[0].cell, "authority_ledger")] if len(rows) == 1 else []


def run_case(s, case: PermitCase, fetcher=None) -> dict:
    """Do the discovery for one case now (crawler process, or tests with a fake fetcher)."""
    fetcher = fetcher or F.fetch
    checked = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        lyr = layers(fetcher)
    except Exception as e:  # noqa: BLE001
        return {"status": "UNAVAILABLE", "plans": [], "land_use": [], "declared_plans": [], "errors": [str(e)[:300]],
                "coverage_complete": False, "checked_at": checked}
    declared = lookup_plans([p for p in case.applicable_plans or [] if isinstance(p, str)], lyr, fetcher)
    _, _, _, _, geo = property_context(s, case)
    source = None
    if geo:
        source = {"kind": "PARCEL_VERIFIED", "note_he": "גבול מגרש מאומת מתוך רשומה רגולטורית"}
    else:
        for plan, cell, how in _cells_for(s, case):
            c = plan_cell(plan, cell, lyr, fetcher)
            if c:
                geo = c.pop("geometry")
                source = {"kind": "PLAN_CELL_XPLAN", **c, "cell_known_from": how,
                          "note_he": f"תא שטח {c['cell']} בתכנית {plan} כפי שמופיע ב־XPLAN — אינו גבול חלקה רשום"}
                break
    if not geo:
        return {"status": "MISSING_GEOMETRY", "plans": [], "land_use": [], "declared_plans": declared, "errors": [],
                "coverage_complete": False, "checked_at": checked}
    out = discover(geo, fetcher, lyr)
    if any(not d.get("found") for d in declared):
        out["status"] = "PARTIAL" if out["status"] == "CANDIDATES_FOUND" else out["status"]
    return {**out, "declared_plans": declared, "geometry_source": source, "geometry": geo, "checked_at": checked}


def queue(s, case: PermitCase, user: str) -> ParcelPlanDiscovery:
    row = s.get(ParcelPlanDiscovery, case.id)
    if row is not None and row.tenant_id != case.tenant_id:
        raise ValueError("scope mismatch")
    if row is not None and row.state in ("queued", "running"):
        return row
    now = dt.datetime.now(dt.timezone.utc)
    if row is None:
        row = ParcelPlanDiscovery(case_id=case.id, tenant_id=case.tenant_id, result={"status": "QUEUED", "plans": []})
        s.add(row)
    row.state, row.requested_by, row.requested_at, row.error = "queued", user, now, None
    s.flush()
    return row


def claim(session_factory) -> str | None:
    with session_factory() as s:
        row = s.scalars(select(ParcelPlanDiscovery).where(ParcelPlanDiscovery.state == "queued")
                        .order_by(ParcelPlanDiscovery.requested_at).limit(1).with_for_update(skip_locked=True)).first()
        if row is None:
            return None
        row.state = "running"
        s.commit()
        return row.case_id


def run_claimed(session_factory, case_id: str, fetcher=None) -> None:
    with session_factory() as s:
        row = s.get(ParcelPlanDiscovery, case_id)
        case = s.get(PermitCase, case_id)
        try:
            if fetcher is None and not enabled():
                raise XplanError("איתור XPLAN כבוי בהגדרות השרת (BBP_XPLAN_ENABLED)")
            result = run_case(s, case, fetcher)
            row.result, row.state, row.error = result, "done", None
            row.parcel_hash = digest(result["geometry"]) if result.get("geometry") else None
            row.checked_at = dt.datetime.now(dt.timezone.utc)
            _passport(s, case, result)
        except Exception as e:  # noqa: BLE001 — recorded; the worker goes on
            s.rollback()
            row = s.get(ParcelPlanDiscovery, case_id)
            row.state, row.error = "failed", f"{type(e).__name__}: {e}"[:300]
            row.result = {"status": "FAILED", "plans": [], "errors": [row.error]}
        from . import audit
        audit.record(s, row.tenant_id, "system:crawler", "plans.discover", "case", case_id,
                     {"state": row.state, "status": (row.result or {}).get("status"), "plans": len((row.result or {}).get("plans") or [])})
        s.commit()


def _passport(s, case: PermitCase, result: dict) -> None:
    """The declared plans as XPLAN shows them, on the property passport (standing from XPLAN's own status)."""
    if not (case.gush and case.helka):
        return
    from . import building as B
    prop = B.get_property(s, case.tenant_id, case.gush, case.helka, None)
    for d in result.get("declared_plans") or []:
        if d.get("found"):
            B.put_fact(s, prop, "plan", d["plan"], {k: d.get(k) for k in ("plan", "name", "status", "stage", "published", "subtype", "committee")},
                       "APPROVED" if d.get("status") == "אישור" else "UNVERIFIED", "xplan", d["plan"], d.get("url"),
                       valid_from=d.get("published"), user="system:crawler")
    src = result.get("geometry_source") or {}
    if src.get("kind") == "PLAN_CELL_XPLAN":
        B.put_fact(s, prop, "plan_cell", f"{src['plan']}:{src['cell']}",
                   {k: src.get(k) for k in ("plan", "cell", "designation", "status", "legal_area", "cell_known_from")},
                   "APPROVED" if src.get("status") == "אישור" else "UNVERIFIED", "xplan", src["plan"], None, user="system:crawler")


def fail_interrupted(session_factory) -> int:
    with session_factory() as s:
        rows = list(s.scalars(select(ParcelPlanDiscovery).where(ParcelPlanDiscovery.state == "running")))
        for r in rows:
            r.state, r.error = "failed", "הסורק הופעל מחדש באמצע העבודה"
            r.result = {"status": "FAILED", "plans": [], "errors": [r.error]}
        s.commit()
        return len(rows)


def view(s, case: PermitCase) -> dict:
    """The stored discovery for the case, for the API (geometry left out)."""
    row = s.get(ParcelPlanDiscovery, case.id)
    if row is None or row.tenant_id != case.tenant_id:
        return {"state": None, "status": "NOT_DISCOVERED", "status_he": STATUS_HE["NOT_DISCOVERED"], "plans": []}
    r = {k: v for k, v in (row.result or {}).items() if k != "geometry"}
    status = {"queued": "QUEUED", "running": "RUNNING"}.get(row.state) or r.get("status") or "NOT_DISCOVERED"
    return {**r, "state": row.state, "status": status, "status_he": STATUS_HE.get(status, status), "error": row.error,
            "requested_at": row.requested_at and row.requested_at.isoformat(), "checked_at": row.checked_at and row.checked_at.isoformat()}


def refresh(s, case: PermitCase, fetcher=None, user: str = "system") -> dict:
    """Compatibility entry: with a fetcher (tests) run now; otherwise queue for the crawler."""
    if fetcher is not None:
        row = queue(s, case, user)
        s.commit()
        run_claimed(lambda: _Same(s), case.id, fetcher)
        return view(s, case)
    queue(s, case, user)
    s.commit()
    return view(s, case)


class _Same:
    """Context manager handing back an existing session (refresh with a test fetcher)."""
    def __init__(self, s):
        self.s = s

    def __enter__(self):
        return self.s

    def __exit__(self, *a):
        return False


__all__ = ["discover", "run_case", "queue", "claim", "run_claimed", "fail_interrupted", "view", "refresh", "STATUS_HE",
           "esri_to_geojson"]
