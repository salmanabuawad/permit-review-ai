"""National register of local planning committees: who they are, where they publish, what knowledge we have.

Seeded from the Planning Administration's list (knowledge/committees/gov_il_local_committees.json) so knowledge can be
built for every committee before its first customer. The import is idempotent and never overwrites what an
administrator or a probe filled in (codes, URLs, vendor, sources, status).

Knowledge status (kb_status):
  NOT_STARTED       listed only
  SITE_PROBED       the committee's site was read; nothing usable found yet
  SOURCES_FOUND     candidate regulation / guideline sources found (unverified)
  DOCUMENTS_FETCHED candidate sources fetched into versioned, searchable snapshots (still unverified)
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
STATUSES = ("NOT_STARTED", "SITE_PROBED", "SOURCES_FOUND", "DOCUMENTS_FETCHED", "BLOCKED", "IN_SYSTEM")
STATUS_HE = {"NOT_STARTED": "טרם התחיל", "SITE_PROBED": "אתר נסרק — לא נמצאו מקורות", "SOURCES_FOUND": "נמצאו מקורות מועמדים", "DOCUMENTS_FETCHED": "מסמכים נקלטו (טרם אומתו)",
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
    from .models import CommitteeDocument
    docs: dict[str, dict] = {}
    for cid, st, n in s.execute(select(CommitteeDocument.committee_id, CommitteeDocument.status, func.count())
                                .group_by(CommitteeDocument.committee_id, CommitteeDocument.status)):
        docs.setdefault(cid, {})[st] = n
    for r in rows:
        r["documents"] = docs.get(r["id"], {})
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
    if out:                                         # from now on these are the administrator's values
        auto = set((c.kb_detail or {}).get("auto_fields") or []) - set(out)
        c.kb_detail = {**(c.kb_detail or {}), "auto_fields": sorted(auto)}
    c.updated_at = dt.datetime.now(dt.timezone.utc)
    s.flush()
    return out


# ------------------------------------------------------------------ site probe (runs only in the crawler process)
# Reads a committee's published site: the home page and at most MAX_PAGES further pages on the same site whose link
# text is about permits, plans or guidelines; one request per second. Records the vendor fingerprint, a candidate
# request-search system, the engineering site and candidate regulation / guideline sources. Everything found is a
# candidate for a person to confirm; nothing becomes a rule. Fields an administrator filled in are never replaced.

MAX_PAGES, MAX_SOURCES = 5, 40
SEARCH_WORDS = ("איתור בקשות", "חיפוש בקשות", "בקשות להיתר", "מעקב בקשות", "מעקב אחר בקשות", "תיק בניין", "תיקי בניין",
                "תיק בנין", "מידע על בקשות", "חיפוש תיק", "חיפוש היתרים", "מאגר היתרים", "מידע על תיק")
ENGINEERING_WORDS = ("מחלקת הנדסה", "אגף הנדסה", "מינהל הנדסה", "הנדסה", "רישוי ופיקוח", "רישוי בנייה")
SOURCE_WORDS = {"guideline": ("הנחיות מרחביות", "הנחיות מרחבית", "הנחיות הוועדה", "הנחיות תכנון", "הנחיות בינוי", "מדיניות"),
                "plan": ("תב\"ע", "תב״ע", "תכניות בניין עיר", "תוכניות בניין עיר", "תכנית מתאר", "תוכנית מתאר", "תקנון"),
                "bylaw": ("חוקי עזר", "חוק עזר"),
                "procedure": ("נהלים", "נוהל", "טפסים", "מידע תכנוני", "תיק מידע")}
SEARCH_URL = re.compile(r"searchpermit|permitapplication|tikbinyan|tik-binyan|buildingfile|bakashot|requests?search|/rishuy/?search", re.I)
NOT_SOURCE = ("פרטיות", "נגישות", "עוגיות", "cookies", "תנאי שימוש", "תנאי השימוש", "צור קשר", "התנגדות")
PAGE_WORDS = ("הנדסה", "רישוי", "תכנון", "ועדה", "מידע", "הנחיות", "בקשות", "תכניות", "תוכניות")
FINGERPRINTS = (("BarTech", re.compile(r"bartech", re.I)), ("Complot", re.compile(r"complot", re.I)))


def run_deep(session_factory, cid: str, fetcher=None, sleep=None, extract=None) -> None:
    """Deep search of one committee: its site breadth-first, then its online plans from XPLAN."""
    from . import plan_discovery as PD
    from .committee_docs import committee_counts, deep_crawl
    with session_factory() as s:
        c = s.get(PlanningCommittee, cid)
        try:
            out = {"site": deep_crawl(s, c, fetcher, sleep, extract)}
            try:
                out["xplan"] = PD.committee_catalogue(s, s.get(PlanningCommittee, cid), fetcher, extract)
            except Exception as e:                      # noqa: BLE001 — the site part still counts
                s.rollback()
                out["xplan"] = {"error": f"{type(e).__name__}: {e}"[:300]}
            c = s.get(PlanningCommittee, cid)
            counts = committee_counts(s, c.id)
            if (counts["by_status"].get("ok") or 0) + (counts["by_status"].get("unchanged") or 0):
                c.kb_status = "DOCUMENTS_FETCHED"
            c.kb_detail = {**(c.kb_detail or {}), "deep": {"state": "done", "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                                            "last_run": out, **counts}}
            c.updated_at = dt.datetime.now(dt.timezone.utc)
            s.commit()
        except Exception as e:                          # noqa: BLE001 — recorded; the worker goes on
            s.rollback()
            c = s.get(PlanningCommittee, cid)
            c.kb_detail = {**(c.kb_detail or {}), "deep": {"state": "failed", "error": f"{type(e).__name__}: {e}"[:300]}}
            s.commit()


def _links(html_text: str, base: str) -> list[tuple[str, str]]:
    from html.parser import HTMLParser
    from urllib.parse import urljoin

    out: list[tuple[str, str]] = []

    class P(HTMLParser):
        href = None
        text: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.href, self.text = dict(attrs).get("href"), [dict(attrs).get("title") or ""]

        def handle_data(self, data):
            if self.href is not None:
                self.text.append(data)

        def handle_endtag(self, tag):
            if tag == "a" and self.href:
                h = self.href.strip()
                if not h.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
                    out.append((urljoin(base, h).split("#")[0], re.sub(r"\s+", " ", " ".join(self.text)).strip()[:200]))
            if tag == "a":
                self.href = None

    try:
        P().feed(html_text)
    except Exception:                                   # noqa: BLE001 — a broken page yields what was parsed
        pass
    return out


def _hosts(url: str) -> set[str]:
    h = (urlsplit(url).hostname or "").lower()
    bare = h[4:] if h.startswith("www.") else h
    return {bare, "www." + bare} - {"www."}


def probe(s: Session, c: PlanningCommittee, fetcher=None, sleep=None) -> dict:
    """Read the committee's site and record what it shows. Returns the probe summary."""
    import time

    from .source_monitor import fetch as F
    from .source_monitor.service import load_config
    fetcher, sleep = fetcher or F.fetch, sleep or time.sleep
    cfg = load_config()
    now = dt.datetime.now(dt.timezone.utc)
    summary: dict = {"at": now.isoformat(), "pages": 0, "errors": []}
    if not c.website_url:
        summary["errors"].append("אין כתובת אתר ברשימה")
        return _finish(s, c, summary, blocked=True)
    allowed = _hosts(c.website_url)
    # the published link is often an old deep page: when it fails, the site's home page (https, then http) is tried
    parts = urlsplit(c.website_url)
    fallbacks = [f"{sch}://{parts.hostname}/" for sch in ("https", "http")
                 if f"{sch}://{parts.hostname}/" != c.website_url]
    queue, seen, pages = [c.website_url], set(), []
    while queue and summary["pages"] < 1 + MAX_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if summary["pages"]:
            sleep(cfg["delay_between_requests_s"])
        r = fetcher(url, cfg, allowed)
        if r.status == "error" and "הפניה לאתר" in (r.message or "") and not pages:
            m = re.search(r"\(([^()]+)\)\s*$", r.message or "")     # the home page moved to another site: follow once
            if m and "." in m.group(1):
                allowed |= _hosts("https://" + m.group(1))
                summary["redirected_to"] = m.group(1)
                r = fetcher(url, cfg, allowed)
        summary["pages"] += 1
        if r.status != "ok" or not (r.content_type or "").startswith(("text/html", "application/xhtml")):
            summary["errors"].append(f"{url}: {r.message or r.status}")
            if not pages and fallbacks:
                queue.insert(0, fallbacks.pop(0))
                summary["fallback"] = True
            continue
        text = F.decode_html(r.body)
        base = r.final_url or url
        pages.append((base, text))
        if len(pages) == 1:
            for link, label in _links(text, base):
                if urlsplit(link).hostname in allowed and any(w in label for w in PAGE_WORDS) and link not in seen:
                    queue.append(link)
    if not pages:
        return _finish(s, c, summary, blocked=True)
    # vendor: a fingerprint in the pages or their links
    blob = " ".join(t[:200000] for _, t in pages)
    for name, rx in FINGERPRINTS:
        if rx.search(blob):
            summary["vendor"] = name
            break
    links = [(u, l) for base, t in pages for u, l in _links(t, base)]
    vendor_hosts = (".bartech-net.co.il", ".complot.co.il")
    own = lambda u: (urlsplit(u).hostname or "") in allowed  # noqa: E731
    near = lambda u: own(u) or (urlsplit(u).hostname or "").endswith(vendor_hosts)  # noqa: E731
    search = next((u for u, l in links if near(u) and SEARCH_URL.search(u)), None) \
        or next((u for u, l in links if near(u) and any(w in l for w in SEARCH_WORDS)), None)
    engineering = next((u for u, l in links if own(u) and u != search and not SEARCH_URL.search(u)
                        and any(w in l for w in ENGINEERING_WORDS)), None)
    found = []
    for u, label in links:
        if any(w in label.lower() for w in NOT_SOURCE):
            continue
        kind = next((k for k, words in SOURCE_WORDS.items() if any(w in label for w in words)), None)
        if kind and u not in {f["url"] for f in found}:
            found.append({"url": u, "title": label, "kind": kind, "status": "candidate", "found_at": now.isoformat()})
    summary.update(request_search_url=search, engineering_url=engineering, sources_found=len(found[:MAX_SOURCES]))
    return _finish(s, c, summary, sources=found[:MAX_SOURCES])


def _finish(s: Session, c: PlanningCommittee, summary: dict, blocked: bool = False, sources: list | None = None) -> dict:
    c.last_probed_at = dt.datetime.now(dt.timezone.utc)
    if blocked:      # a committee whose documents are already in the knowledge base keeps that status
        c.kb_status = "DOCUMENTS_FETCHED" if c.kb_status == "DOCUMENTS_FETCHED" else "BLOCKED"
    else:
        # values the probe set itself may be corrected by a later probe; an administrator's values are never touched
        auto = set((c.kb_detail or {}).get("auto_fields") or [])
        if summary.get("vendor") and (c.vendor == "unknown" or "vendor" in auto):
            c.vendor, c.vendor_evidence = summary["vendor"], "זוהה בדף האתר"
            auto.add("vendor")
        for f in ("request_search_url", "engineering_url"):
            if not getattr(c, f) or f in auto:
                setattr(c, f, summary.get(f))
                auto.add(f)
        kept = [x for x in (c.sources or []) if x.get("status") != "candidate"]       # reviewed sources stay
        known = {x["url"] for x in kept}
        c.sources = kept + [x for x in (sources or []) if x["url"] not in known]
        c.kb_detail = {**(c.kb_detail or {}), "auto_fields": sorted(auto)}
        fetched = c.kb_status == "DOCUMENTS_FETCHED"
        c.kb_status = "DOCUMENTS_FETCHED" if fetched else "SOURCES_FOUND" if c.sources else "SITE_PROBED"
    c.kb_detail = {**(c.kb_detail or {}), "probe": {**summary, "state": "done"}}
    c.updated_at = c.last_probed_at
    s.commit()
    return summary


def queue_jobs(s: Session, job: str, ids: list[str] | None = None, only=None) -> int:
    """Mark committees for a crawler job ('probe' or 'fetch'); all when ids is None. `only` filters committees."""
    q = select(PlanningCommittee)
    if ids:
        q = q.where(PlanningCommittee.id.in_(ids))
    n = 0
    for c in s.scalars(q):
        if only and not only(c):
            continue
        if ((c.kb_detail or {}).get(job) or {}).get("state") not in ("queued", "running"):
            prev = (c.kb_detail or {}).get(job) or {}
            c.kb_detail = {**(c.kb_detail or {}), job: {**{k: v for k, v in prev.items() if k != "error"},
                                                         "state": "queued", "queued_at": dt.datetime.now(dt.timezone.utc).isoformat()}}
            n += 1
    s.commit()
    return n


def queue_probes(s: Session, ids: list[str] | None = None) -> int:
    return queue_jobs(s, "probe", ids)


def queue_fetches(s: Session, ids: list[str] | None = None) -> int:
    """Committees with candidate sources only."""
    return queue_jobs(s, "fetch", ids, only=lambda c: bool(c.sources))


def claim(session_factory, job: str) -> str | None:
    with session_factory() as s:
        for c in s.scalars(select(PlanningCommittee).order_by(PlanningCommittee.district, PlanningCommittee.name_he)):
            if ((c.kb_detail or {}).get(job) or {}).get("state") == "queued":
                c.kb_detail = {**c.kb_detail, job: {**c.kb_detail[job], "state": "running"}}
                s.commit()
                return c.id
    return None


def claim_probe(session_factory) -> str | None:
    return claim(session_factory, "probe")


def run_probe(session_factory, cid: str, fetcher=None, sleep=None) -> None:
    with session_factory() as s:
        c = s.get(PlanningCommittee, cid)
        try:
            probe(s, c, fetcher, sleep)
        except Exception as e:                          # noqa: BLE001 — recorded; the worker goes on
            s.rollback()
            c = s.get(PlanningCommittee, cid)
            c.kb_detail = {**(c.kb_detail or {}), "probe": {"state": "failed", "error": f"{type(e).__name__}: {e}"[:300]}}
            s.commit()


def run_fetch(session_factory, cid: str, fetcher=None, sleep=None, extract=None) -> None:
    from .committee_docs import committee_counts, fetch_committee
    with session_factory() as s:
        c = s.get(PlanningCommittee, cid)
        try:
            out = fetch_committee(s, c, fetcher, sleep, extract)
            counts = committee_counts(s, c.id)
            c = s.get(PlanningCommittee, cid)
            if (counts["by_status"].get("ok") or 0) + (counts["by_status"].get("unchanged") or 0):
                c.kb_status = "DOCUMENTS_FETCHED"
            c.kb_detail = {**(c.kb_detail or {}), "fetch": {"state": "done", "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                                             "last_run": out, **counts}}
            c.updated_at = dt.datetime.now(dt.timezone.utc)
            s.commit()
        except Exception as e:                          # noqa: BLE001 — recorded; the worker goes on
            s.rollback()
            c = s.get(PlanningCommittee, cid)
            c.kb_detail = {**(c.kb_detail or {}), "fetch": {"state": "failed", "error": f"{type(e).__name__}: {e}"[:300]}}
            s.commit()


def fail_interrupted(session_factory) -> int:
    """At crawler start: a probe / fetch still 'running' belonged to a crawler that stopped. Marked failed; the
    administrator queues it again (a fetch then resumes from the documents still pending)."""
    with session_factory() as s:
        n = 0
        for c in s.scalars(select(PlanningCommittee)):
            for job in ("probe", "fetch", "deep", "meetings"):
                st = (c.kb_detail or {}).get(job) or {}
                if st.get("state") == "running":
                    c.kb_detail = {**c.kb_detail, job: {**st, "state": "failed", "error": "הסורק הופעל מחדש באמצע העבודה"}}
                    n += 1
        s.commit()
        return n
