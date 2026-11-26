"""National register of local planning committees: who they are, where they publish, what knowledge we have.

Seeded from the Planning Administration's list (knowledge/committees/gov_il_local_committees.json) so knowledge can be
built for every committee before its first customer. The import is idempotent and never overwrites what an
administrator or a probe filled in (codes, URLs, vendor, sources, status).

Knowledge status (kb_status):
  NOT_STARTED       listed only
  SITE_PROBED       the committee's site was read; nothing usable found yet
  SOURCES_FOUND     candidate regulation / guideline sources found (unverified)
  BLOCKED           the site refused or could not be reached
  IN_SYSTEM         an authority of this system is linked; its own knowledge base is the reference
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import CommitteeSettlement, Municipality, PlanningCommittee

REGISTER = "committees/gov_il_local_committees.json"
STATUSES = ("NOT_STARTED", "SITE_PROBED", "SOURCES_FOUND", "BLOCKED", "IN_SYSTEM")
STATUS_HE = {"NOT_STARTED": "טרם התחיל", "SITE_PROBED": "אתר נסרק — לא נמצאו מקורות", "SOURCES_FOUND": "נמצאו מקורות מועמדים",
             "BLOCKED": "האתר חסום / לא זמין", "IN_SYSTEM": "רשות פעילה במערכת"}
VENDORS = ("BarTech", "Complot", "other", "unknown")
REGIONAL = " (ועדה מרחבית)"
PREFIXES = ("הוועדה המקומית לתכנון ובנייה", "הועדה המקומית לתכנון ובניה", "ועדה מקומית", "ועדה מרחבית", "עיריית", "מועצה אזורית")


def committee_id(name_he: str) -> str:
    return "lc-" + hashlib.sha1(name_he.encode("utf-8")).hexdigest()[:10]


def base_name(name: str) -> str:
    n = (name or "").replace(REGIONAL, "").strip()
    for p in PREFIXES:
        if n.startswith(p):
            n = n[len(p):].strip(" -–")
    return re.sub(r"\s+", " ", n.replace("־", "-")).strip()


def vendor_from_url(url: str | None) -> tuple[str, str | None]:
    host = (urlsplit(url).hostname or "") if url else ""
    if host.endswith(".bartech-net.co.il"):
        return "BarTech", f"כתובת האתר ב־{host}"
    if host.endswith(".complot.co.il"):
        return "Complot", f"כתובת האתר ב־{host}"
    return "unknown", None


def import_register(s: Session, path: Path | None = None) -> dict:
    """Load or refresh the register. Returns counts."""
    data = json.loads((path or settings.knowledge_dir / REGISTER).read_text(encoding="utf-8"))
    src = {k: data["source"][k] for k in ("url", "page_updated", "retrieved")}
    regional = {(d, n) for d, names in data.get("regional_committees_list", {}).items() for n in names}
    added = updated = 0
    for district, rows in data["districts"].items():
        for name, url, towns in rows:
            name = name.strip()
            short = base_name(name)
            kind = "regional" if REGIONAL in name or (district, short) in regional else "local"
            c = s.scalars(select(PlanningCommittee).where(PlanningCommittee.name_he == short)).first()
            if c is None:
                vendor, why = vendor_from_url(url)
                c = PlanningCommittee(id=committee_id(short), name_he=short, district=district, kind=kind, website_url=url,
                                      vendor=vendor, vendor_evidence=why, sources=[], kb_status="NOT_STARTED",
                                      kb_detail={}, registry_source=src)
                s.add(c)
                added += 1
            else:                                   # published facts follow the source; curated fields are kept
                if (c.district, c.kind, c.website_url) != (district, kind, url):
                    c.district, c.kind, c.website_url = district, kind, url
                    updated += 1
                c.registry_source = src
            s.flush()
            have = {x.name_he for x in s.scalars(select(CommitteeSettlement).where(CommitteeSettlement.committee_id == c.id))}
            for t in dict.fromkeys(t.strip() for t in towns if t.strip()):
                if t not in have:
                    s.add(CommitteeSettlement(committee_id=c.id, name_he=t))
    s.flush()
    linked = link_authorities(s)
    return {"committees": s.scalar(select(func.count()).select_from(PlanningCommittee)), "added": added,
            "updated": updated, "linked": linked}


def link_authorities(s: Session) -> list[str]:
    """Link each authority of the system to its committee when exactly one committee has the same name."""
    by_name: dict[str, list[PlanningCommittee]] = {}
    for c in s.scalars(select(PlanningCommittee)):
        by_name.setdefault(base_name(c.name_he), []).append(c)
    out = []
    for m in s.scalars(select(Municipality).where(Municipality.is_demo.is_(False), Municipality.committee_id.is_(None))):
        hits = by_name.get(base_name(m.name_he), [])
        if len(hits) == 1:
            m.committee_id = hits[0].id
            out.append(m.id)
    s.flush()
    return out


def ensure_imported(s: Session) -> None:
    if not s.scalar(select(func.count()).select_from(PlanningCommittee)):
        import_register(s)
        s.commit()


def as_dict(s: Session, c: PlanningCommittee, authorities: dict[str, list[Municipality]] | None = None) -> dict:
    orgs = (authorities or {}).get(c.id)
    if orgs is None:
        orgs = list(s.scalars(select(Municipality).where(Municipality.committee_id == c.id)))
    status = "IN_SYSTEM" if orgs else c.kb_status
    towns = [t.name_he for t in s.scalars(select(CommitteeSettlement).where(CommitteeSettlement.committee_id == c.id))]
    return {"id": c.id, "committee_code": c.committee_code, "name_he": c.name_he, "district": c.district, "kind": c.kind,
            "settlements": towns, "website_url": c.website_url, "engineering_url": c.engineering_url,
            "request_search_url": c.request_search_url, "vendor": c.vendor, "vendor_evidence": c.vendor_evidence,
            "sources": c.sources or [], "kb_status": status, "kb_status_he": STATUS_HE[status], "kb_detail": c.kb_detail or {},
            "authorities": [{"id": o.id, "name_he": o.name_he} for o in orgs],
            "last_probed_at": c.last_probed_at.isoformat() if c.last_probed_at else None,
            "registry_source": c.registry_source}


def listing(s: Session) -> dict:
    orgs: dict[str, list[Municipality]] = {}
    for m in s.scalars(select(Municipality).where(Municipality.committee_id.is_not(None))):
        orgs.setdefault(m.committee_id, []).append(m)
    rows = [as_dict(s, c, orgs) for c in s.scalars(select(PlanningCommittee).order_by(PlanningCommittee.district, PlanningCommittee.name_he))]
    count = lambda key: {k: sum(1 for r in rows if r[key] == k) for k in dict.fromkeys(r[key] for r in rows)}  # noqa: E731
    return {"committees": rows, "totals": {"committees": len(rows), "by_district": count("district"), "by_vendor": count("vendor"),
                                           "by_status": count("kb_status"), "regional": sum(r["kind"] == "regional" for r in rows)},
            "status_he": STATUS_HE}


EDITABLE = ("committee_code", "engineering_url", "request_search_url", "vendor")


def update(s: Session, c: PlanningCommittee, changes: dict) -> dict:
    out = {}
    for k, v in changes.items():
        if k not in EDITABLE or v == getattr(c, k):
            continue
        if k == "vendor" and v not in VENDORS:
            raise ValueError("ספק לא מוכר")
        if k.endswith("_url") and v and not re.fullmatch(r"https?://[^\s]{3,490}", v):
            raise ValueError("כתובת לא תקינה")
        if k == "committee_code" and v and not re.fullmatch(r"[0-9A-Za-z-]{1,40}", v):
            raise ValueError("קוד ועדה לא תקין")
        out[k] = [getattr(c, k), v or None]
        setattr(c, k, v or None)
    if "vendor" in out:
        c.vendor_evidence = "נקבע ידנית"
    c.updated_at = dt.datetime.now(dt.timezone.utc)
    s.flush()
    return out
