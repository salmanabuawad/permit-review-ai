"""Fetch the candidate sources the site probe found for each committee into versioned, searchable snapshots.

Runs only in the crawler process (public internet only). Per committee and run:
  * only the committee's own site (and its BarTech / Complot host) is fetched; a link elsewhere is recorded, skipped;
  * documents (PDF, DOCX, XLSX) are stored content-addressed; a changed document becomes a new snapshot, an unchanged
    one is recognised (ETag / Last-Modified, then SHA-256) and not stored twice;
  * an HTML source page is read for its text, and documents it links to are followed one level, relevant links only;
  * at most MAX_FETCH requests, one per second;
  * text extraction runs in a resource-limited child process (safe_extract);
  * everything is an unverified candidate of the committee, outside every authority's verified knowledge.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html as htmllib
import re
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import CommitteeDocument, CommitteePassage, CommitteeSnapshot, PlanningCommittee

MAX_FETCH = 40
DOC_EXT = {".pdf": "application/pdf",
           ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
CT_EXT = {v: k for k, v in DOC_EXT.items()}
LEGACY = (".doc", ".xls", ".ppt")
VENDOR_HOSTS = (".bartech-net.co.il", ".complot.co.il")


def store_root() -> Path:
    p = settings.storage_dir / "_sources" / "committees"
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(0o2770)
    except PermissionError:
        pass
    return p


def html_text(body: bytes) -> str:
    from .source_monitor import fetch as F
    t = F.decode_html(body)
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", htmllib.unescape(t))).strip()


def _ext(url: str, content_type: str | None) -> str | None:
    path = urlsplit(url).path.lower()
    for e in (*DOC_EXT, *LEGACY):
        if path.endswith(e):
            return e
    return CT_EXT.get((content_type or "").split(";")[0].strip())


def _allowed(c: PlanningCommittee) -> set[str]:
    from .committees import _hosts
    hosts = set()
    for u in (c.website_url, c.request_search_url, c.engineering_url):
        if u:
            h = urlsplit(u).hostname or ""
            if h in _hosts(c.website_url or "") or h.endswith(VENDOR_HOSTS):
                hosts |= _hosts(u)
    moved = ((c.kb_detail or {}).get("probe") or {}).get("redirected_to")
    if moved:
        hosts |= _hosts("https://" + moved)
    return hosts


def sync_documents(s: Session, c: PlanningCommittee) -> int:
    """Create document rows for the probe's candidate sources (idempotent)."""
    have = {d.url for d in s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id))}
    n = 0
    for x in c.sources or []:
        if x["url"] not in have:
            s.add(CommitteeDocument(committee_id=c.id, url=x["url"][:1000], title=(x.get("title") or "")[:300],
                                    kind=x.get("kind") or "procedure", status="pending"))
            have.add(x["url"])
            n += 1
    s.flush()
    return n


def _save(s: Session, doc: CommitteeDocument, body: bytes, content_type: str, ext: str, pages: list[str] | None,
          extract) -> CommitteeSnapshot:
    sha = hashlib.sha256(body).hexdigest()
    rel = f"{sha[:2]}/{sha}{ext}"
    path = store_root() / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(body)
        tmp.chmod(0o640)
        tmp.replace(path)
    status = "none"
    if pages is None:
        # the same bytes were extracted before (another committee, another URL): reuse that text
        twin = s.scalars(select(CommitteeSnapshot).where(CommitteeSnapshot.sha256 == sha,
                                                         CommitteeSnapshot.text_status.in_(("ok", "empty")))).first()
        if twin:
            pages = [p.text_he for p in s.scalars(select(CommitteePassage).where(CommitteePassage.snapshot_id == twin.id)
                                                  .order_by(CommitteePassage.page))]
            status = twin.text_status
        else:
            try:
                pages = extract(body, ext)
            except ValueError as e:
                pages, status = [], "failed"
                doc.message = str(e)[:300]
    if status == "none" and pages is not None:
        status = "ok" if any(p.strip() for p in pages) else ("empty" if pages else "none")
    snap = CommitteeSnapshot(document_id=doc.id, sha256=sha, content_type=content_type[:120], size=len(body), path=rel,
                             pages=len(pages or []), text_status=status)
    s.add(snap)
    s.flush()
    for i, t in enumerate(pages or [], 1):
        if t.strip():
            s.add(CommitteePassage(snapshot_id=snap.id, page=i, text_he=t[:200000]))
    doc.sha256 = sha
    return snap


def fetch_committee(s: Session, c: PlanningCommittee, fetcher=None, sleep=None, extract=None) -> dict:
    import time

    from .committees import PAGE_WORDS, SOURCE_WORDS, _links
    from .safe_extract import extract as sandboxed
    from .source_monitor import fetch as F
    from .source_monitor.service import load_config
    fetcher, sleep, extract = fetcher or F.fetch, sleep or time.sleep, extract or sandboxed
    cfg = load_config()
    allowed = _allowed(c)
    sync_documents(s, c)
    words = tuple(w for ws in SOURCE_WORDS.values() for w in ws) + tuple(cfg.get("relevance_keywords") or ()) + PAGE_WORDS
    out = {"fetched": 0, "new_versions": 0, "unchanged": 0, "skipped": 0, "failed": 0, "linked_documents": 0}
    queue = list(s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id,
                                                           CommitteeDocument.status.in_(("pending", "failed")))
                           .order_by(CommitteeDocument.found_on.is_not(None), CommitteeDocument.id)))
    queue += [d for d in s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id,
                                                                   CommitteeDocument.status.in_(("ok", "unchanged"))))]
    now = dt.datetime.now(dt.timezone.utc)
    while queue and out["fetched"] < MAX_FETCH:
        doc = queue.pop(0)
        host = urlsplit(doc.url).hostname or ""
        if host not in allowed:
            doc.status, doc.message, doc.checked_at = "skipped", "קישור לאתר אחר — לא נשלף", now
            out["skipped"] += 1
            continue
        ext = _ext(doc.url, None)
        if ext in LEGACY:
            doc.status, doc.message, doc.checked_at = "skipped", f"פורמט ישן ({ext}) — נשמר כקישור בלבד", now
            out["skipped"] += 1
            continue
        if out["fetched"]:
            sleep(cfg["delay_between_requests_s"])
        r = fetcher(doc.url, cfg, allowed, doc.etag, doc.last_modified)
        out["fetched"] += 1
        doc.checked_at, doc.http_status = dt.datetime.now(dt.timezone.utc), r.http_status
        if r.status == "not_modified":
            doc.status, doc.message = "unchanged", None
            out["unchanged"] += 1
            continue
        if r.status != "ok":
            doc.status, doc.message = "failed", (r.message or r.status)[:300]
            out["failed"] += 1
            continue
        doc.etag, doc.last_modified = (r.etag or None), (r.last_modified or None)
        ct = (r.content_type or "").split(";")[0].strip()
        ext = _ext(r.final_url or doc.url, ct)
        sha = hashlib.sha256(r.body).hexdigest()
        if sha == doc.sha256:
            doc.status, doc.message = "unchanged", None
            out["unchanged"] += 1
            continue
        if ct in ("text/html", "application/xhtml+xml"):
            text = html_text(r.body)
            _save(s, doc, r.body, ct, ".html", [text], extract)
            doc.status, doc.message = "ok", None
            out["new_versions"] += 1
            if doc.found_on is None:             # follow documents linked from a source page, one level only
                known = {d.url for d in s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id))}
                for u, label in _links(F.decode_html(r.body), r.final_url or doc.url):
                    e = _ext(u, None)
                    if e in DOC_EXT and u not in known and (urlsplit(u).hostname or "") in allowed \
                            and any(w in (label + " " + u) for w in words):
                        own = next((k for k, ws in SOURCE_WORDS.items() if any(w in label for w in ws)), None)
                        child = CommitteeDocument(committee_id=c.id, url=u[:1000], title=(label or "")[:300], kind=own or doc.kind,
                                                  found_on=doc.url[:1000], status="pending")
                        s.add(child)
                        s.flush()
                        queue.insert(0, child)
                        known.add(u)
                        out["linked_documents"] += 1
        elif ext in DOC_EXT:
            _save(s, doc, r.body, ct or DOC_EXT[ext], ext, None, extract)
            doc.status = "ok"
            out["new_versions"] += 1
        else:
            doc.status, doc.message = "skipped", f"סוג תוכן לא נתמך ({ct or 'לא ידוע'})"
            out["skipped"] += 1
        s.commit()
    s.commit()
    return out


def committee_counts(s: Session, committee_id: str) -> dict:
    q = select(CommitteeDocument.status, func.count()).where(CommitteeDocument.committee_id == committee_id).group_by(CommitteeDocument.status)
    by = dict(s.execute(q).all())
    pages = s.scalar(select(func.count()).select_from(CommitteePassage).join(CommitteeSnapshot)
                     .join(CommitteeDocument).where(CommitteeDocument.committee_id == committee_id)) or 0
    return {"documents": sum(by.values()), "by_status": by, "passages": pages}


def retry_failed_extractions(s: Session, extract=None, limit: int = 500) -> dict:
    """Re-extract text for stored snapshots whose extraction failed (from the stored file; nothing is fetched)."""
    from .safe_extract import extract as sandboxed
    extract = extract or sandboxed
    out = {"retried": 0, "ok": 0, "still_failed": 0}
    for snap in s.scalars(select(CommitteeSnapshot).where(CommitteeSnapshot.text_status == "failed").limit(limit)):
        out["retried"] += 1
        ext = Path(snap.path).suffix
        try:
            pages = extract((store_root() / snap.path).read_bytes(), ext)
        except (ValueError, OSError):
            out["still_failed"] += 1
            continue
        for i, t in enumerate(pages, 1):
            if t.strip():
                s.add(CommitteePassage(snapshot_id=snap.id, page=i, text_he=t[:200000]))
        snap.pages = len(pages)
        snap.text_status = "ok" if any(p.strip() for p in pages) else "empty"
        doc = s.get(CommitteeDocument, snap.document_id)
        if doc and doc.message and doc.sha256 == snap.sha256:
            doc.message = None
        out["ok"] += 1
    s.commit()
    return out
