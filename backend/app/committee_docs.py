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

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import CommitteeDocument, CommitteePassage, CommitteeSnapshot, PlanningCommittee

MAX_FETCH = 40
NATIONAL_HE = "ידע ארצי"
UPLOAD_KINDS = {"law": "חוק", "regulation": "תקנות", "guideline": "הנחיות", "procedure": "נוהל", "plan": "תכנית", "bylaw": "חוק עזר",
                "other": "אחר"}
MAX_UPLOAD = 50 * 1024 * 1024
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


def clean(text: str) -> str:
    """Text as PostgreSQL stores it: no NUL bytes (some PDFs contain them)."""
    return (text or "").replace("\x00", "")


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
    status, ocr_done = "none", None
    if pages is None:
        # the same bytes were extracted before (another committee, another URL): reuse that text
        twin = s.scalars(select(CommitteeSnapshot).where(CommitteeSnapshot.sha256 == sha,
                                                         CommitteeSnapshot.text_status.in_(("ok", "ocr", "empty")))).first()
        if twin:
            pages = [p.text_he for p in s.scalars(select(CommitteePassage).where(CommitteePassage.snapshot_id == twin.id)
                                                  .order_by(CommitteePassage.page))]
            status, ocr_done = twin.text_status, twin.ocr_pages
        else:
            try:
                pages = extract(body, ext)
            except ValueError as e:
                pages, status = [], "failed"
                doc.message = str(e)[:300]
    if status == "none" and pages is not None:
        status = "ok" if any(p.strip() for p in pages) else ("empty" if pages else "none")
    snap = CommitteeSnapshot(document_id=doc.id, sha256=sha, content_type=content_type[:120], size=len(body), path=rel,
                             pages=len(pages or []), text_status=status, ocr_pages=ocr_done)
    s.add(snap)
    s.flush()
    for i, t in enumerate(pages or [], 1):
        t = clean(t)
        if t.strip():
            s.add(CommitteePassage(snapshot_id=snap.id, page=i, text_he=t[:200000]))
    doc.sha256 = sha
    return snap


def fetch_committee(s: Session, c: PlanningCommittee, fetcher=None, sleep=None, extract=None, limit: int = MAX_FETCH,
                    pending_only: bool = False) -> dict:
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
    if not pending_only:
        queue += [d for d in s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id,
                                                                       CommitteeDocument.status.in_(("ok", "unchanged"))))]
    now = dt.datetime.now(dt.timezone.utc)
    while queue and out["fetched"] < limit:
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
            doc.status, doc.message = "failed", clean(r.message or r.status)[:300]
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
                        child = CommitteeDocument(committee_id=c.id, url=u[:1000], title=clean(label)[:300], kind=own or doc.kind,
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
            t = clean(t)
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


# ---------------------------------------------------------------- deep crawl (one committee, on request)

DEEP_MAX_PAGES = 300        # HTML pages read per deep crawl
DEEP_MAX_DOCS = 400         # documents fetched per deep crawl
DEEP_DEPTH = 3              # link depth from the home page and the probe's sources
SKIP_PATH = re.compile(r"\.(jpe?g|png|gif|svg|webp|ico|css|js|mp4|mp3|zip|rar|7z|exe|dwg|dwfx?)$|/(login|signin|account|"
                       r"umbraco|wp-admin|wp-login|feed|print|share|search)(/|\?|$)|mailto:|tel:|javascript:", re.I)


def _canon(u: str) -> str:
    p = urlsplit(u)
    return p._replace(fragment="", query="" if not p.query or len(p.query) > 80 else p.query).geturl()


def deep_crawl(s: Session, c: PlanningCommittee, fetcher=None, sleep=None, extract=None,
               max_pages: int = DEEP_MAX_PAGES, max_docs: int = DEEP_MAX_DOCS, depth: int = DEEP_DEPTH) -> dict:
    """Read the committee's own site breadth-first (own hosts only, one request per delay, no search or account pages):
    every content page is stored as text, every document it links (PDF / DOCX / XLSX) is queued and fetched. Same
    storage and versioning as the regular fetch; everything stays an unverified candidate of the committee."""
    import time

    from .committees import NOT_SOURCE, SEARCH_URL, SOURCE_WORDS, _links
    from .safe_extract import extract as sandboxed
    from .source_monitor import fetch as F
    from .source_monitor.service import load_config
    fetcher, sleep, extract = fetcher or F.fetch, sleep or time.sleep, extract or sandboxed
    cfg = load_config()
    allowed = _allowed(c)
    sync_documents(s, c)
    docs = {d.url: d for d in s.scalars(select(CommitteeDocument).where(CommitteeDocument.committee_id == c.id))}
    starts = [u for u in [c.website_url, c.engineering_url, *[x.get("url") for x in c.sources or []]] if u]
    frontier = [(_canon(u), 0) for u in starts if (urlsplit(u).hostname or "") in allowed and _ext(u, None) not in DOC_EXT]
    seen = {u for u, _ in frontier}
    out = {"pages_read": 0, "pages_stored": 0, "pages_unchanged": 0, "documents_found": 0, "failed": 0, "skipped_links": 0}
    first = True
    while frontier and out["pages_read"] < max_pages:
        url, d = frontier.pop(0)
        if not first:
            sleep(cfg["delay_between_requests_s"])
        first = False
        r = fetcher(url, cfg, allowed)
        out["pages_read"] += 1
        if r.status != "ok":
            out["failed"] += 1
            continue
        ct = (r.content_type or "").split(";")[0].strip()
        if ct not in ("text/html", "application/xhtml+xml"):
            continue
        html = F.decode_html(r.body)
        text = html_text(r.body)
        title = clean(re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I).group(1)).strip()[:300] \
            if re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I) else None
        if len(text) >= 300:                                   # a content page: keep its text (versioned)
            doc = docs.get(url)
            if doc is None:
                kind = next((k for k, ws in SOURCE_WORDS.items() if any(w in (title or "") for w in ws)), "procedure")
                doc = CommitteeDocument(committee_id=c.id, url=url[:1000], title=title, kind=kind, found_on="deep:" + url[:990],
                                        status="pending")
                s.add(doc)
                s.flush()
                docs[url] = doc
            sha = hashlib.sha256(r.body).hexdigest()
            doc.checked_at, doc.http_status = dt.datetime.now(dt.timezone.utc), r.http_status
            if sha == doc.sha256:
                doc.status = "unchanged"
                out["pages_unchanged"] += 1
            else:
                _save(s, doc, r.body, ct, ".html", [text], extract)
                doc.status, doc.message = "ok", None
                out["pages_stored"] += 1
        for u, label in _links(html, r.final_url or url):
            u = _canon(u)
            host = urlsplit(u).hostname or ""
            if host not in allowed or SKIP_PATH.search(u) or SEARCH_URL.search(u) or any(w in label.lower() for w in NOT_SOURCE):
                out["skipped_links"] += 1
                continue
            e = _ext(u, None)
            if e in DOC_EXT:
                if u not in docs and out["documents_found"] < max_docs:
                    kind = next((k for k, ws in SOURCE_WORDS.items() if any(w in label for w in ws)), "procedure")
                    docs[u] = CommitteeDocument(committee_id=c.id, url=u[:1000], title=clean(label)[:300] or None, kind=kind,
                                                found_on=url[:1000], status="pending")
                    s.add(docs[u])
                    out["documents_found"] += 1
            elif e is None and u not in seen and d + 1 <= depth:
                seen.add(u)
                frontier.append((u, d + 1))
        s.commit()
    out["pages_not_read"] = len(frontier)
    fetched = fetch_committee(s, c, fetcher, sleep, extract, limit=max_docs, pending_only=True)
    return {**out, "documents": fetched}


def hybrid_search(s: Session, q: str, committee_id: str | None = None, mode: str = "hybrid", k: int = 50) -> list[dict]:
    """Fetched committee text (unverified candidates): keyword (exact phrase) and local-embedding retrieval fused by
    reciprocal rank (mode=hybrid), or one of them. Each hit says what found it and, when semantic, its similarity."""
    from . import embeddings as E
    from .models import CommitteeChunk
    q = E.normalize_query(q)
    base = (select(CommitteePassage, CommitteeSnapshot, CommitteeDocument, PlanningCommittee)
            .join(CommitteeSnapshot, CommitteePassage.snapshot_id == CommitteeSnapshot.id)
            .join(CommitteeDocument, CommitteeSnapshot.document_id == CommitteeDocument.id)
            .outerjoin(PlanningCommittee, CommitteeDocument.committee_id == PlanningCommittee.id)
            .where(CommitteeDocument.sha256 == CommitteeSnapshot.sha256))
    if committee_id:                                   # the committee's own text, and national knowledge
        base = base.where(or_(CommitteeDocument.committee_id == committee_id, CommitteeDocument.committee_id.is_(None)))
    rows, kw, sem, best_chunk = {}, [], [], {}
    if mode in ("hybrid", "keyword"):
        for x, snap, d, c in s.execute(base.where(CommitteePassage.text_he.contains(q, autoescape=True)).limit(k)):
            rows[x.id] = (x, snap, d, c)
            kw.append(x.id)
    if mode in ("hybrid", "semantic"):
        hits = E.semantic(s, q, k=k, committee_id=committee_id)
        if hits:
            chunk_rows = {ch.id: ch for ch in s.scalars(select(CommitteeChunk).where(CommitteeChunk.id.in_([h[0] for h in hits])))}
            for cid, sim in hits:
                ch = chunk_rows.get(cid)
                if ch and ch.passage_id not in best_chunk:
                    best_chunk[ch.passage_id] = (ch, sim)
                    sem.append(ch.passage_id)
            missing = [pid for pid in sem if pid not in rows]
            for x, snap, d, c in s.execute(base.where(CommitteePassage.id.in_(missing))) if missing else []:
                rows[x.id] = (x, snap, d, c)
    out = []
    for pid in E.rrf(kw, sem)[:k]:
        if pid not in rows:
            continue
        x, snap, d, c = rows[pid]
        if pid in kw:
            i = x.text_he.find(q)
            excerpt = x.text_he[max(0, i - 200): i + 300]
        else:
            ch, _ = best_chunk[pid]
            excerpt = x.text_he[ch.start:ch.end]
        out.append({"committee": c.name_he if c else NATIONAL_HE, "committee_id": c.id if c else None, "document": d.title or d.url, "url": d.url, "kind": d.kind,
                    "page": x.page, "snapshot_id": snap.id, "excerpt": excerpt, "verification": "UNVERIFIED",
                    "found_by": [n for n, lst in (("keyword", kw), ("semantic", sem)) if pid in lst],
                    "similarity": round(best_chunk[pid][1], 3) if pid in best_chunk else None, "passage_id": pid})
    return out


# ---------------------------------------------------------------- uploads to the AI knowledge base (superadmin)

def upload(s: Session, committee_id: str | None, body: bytes, filename: str, kind: str, title: str, user: str) -> CommitteeDocument:
    """Add a document to the knowledge base the assistant searches: a committee's, or national (committee_id None).
    Text is extracted in the sandbox; the crawler worker splits and embeds it when idle. The same file twice is one
    document; a retired one comes back."""
    import datetime as dt
    import hashlib

    from .safe_extract import extract as sandboxed
    from .source_monitor.service import validate_upload
    if committee_id is not None and s.get(PlanningCommittee, committee_id) is None:
        raise ValueError("ועדה לא נמצאה")
    if kind not in UPLOAD_KINDS:
        raise ValueError("סוג מסמך לא מוכר")
    if len(body) > MAX_UPLOAD:
        raise ValueError("הקובץ גדול מ־50 MB")
    name = (filename or "upload").lower()
    ext = next((e for e in DOC_EXT if name.endswith(e)), None)
    if ext is None:
        raise ValueError("רק PDF, DOCX או XLSX")
    validate_upload(body, ext)
    sha = hashlib.sha256(body).hexdigest()
    url = f"upload:{sha}"
    q = select(CommitteeDocument).where(CommitteeDocument.url == url)
    q = q.where(CommitteeDocument.committee_id.is_(None) if committee_id is None else CommitteeDocument.committee_id == committee_id)
    doc = s.scalars(q).first()
    if doc is None:
        doc = CommitteeDocument(committee_id=committee_id, url=url, title=(title or filename or "")[:300], kind=kind,
                                found_on=f"upload:{user}", status="pending")
        s.add(doc)
        s.flush()
        _save(s, doc, body, DOC_EXT[ext], ext, None, sandboxed)
    elif doc.status == "retired":
        doc.sha256 = sha
    doc.kind, doc.title = kind, (title or doc.title or filename or "")[:300]
    doc.status, doc.checked_at = "ok", dt.datetime.now(dt.timezone.utc)
    if committee_id is not None:            # the committee now has documents in the knowledge base (e.g. its site is blocked)
        c = s.get(PlanningCommittee, committee_id)
        if c.kb_status != "DOCUMENTS_FETCHED":
            c.kb_status = "DOCUMENTS_FETCHED"
    return doc


def reextract(s: Session, doc: CommitteeDocument, extract=None) -> str:
    """Extract the text of a document whose extraction failed (e.g. the process was stopped by a service restart)
    again from the stored file. Returns the new text status; documents whose text is fine are left alone."""
    if extract is None:
        from .safe_extract import extract
    snap = s.scalars(select(CommitteeSnapshot).where(CommitteeSnapshot.document_id == doc.id)
                     .order_by(CommitteeSnapshot.id.desc())).first()
    if snap is None or snap.text_status != "failed":
        return snap.text_status if snap else "none"
    body = (store_root() / snap.path).read_bytes()
    ext = Path(snap.path).suffix
    try:
        pages = extract(body, ext)
    except ValueError as e:
        doc.message = str(e)[:300]
        return "failed"
    status = "ok" if any(p.strip() for p in pages) else ("empty" if pages else "none")
    snap.pages, snap.text_status, doc.message = len(pages), status, None
    for i, txt in enumerate(pages, 1):
        txt = clean(txt)
        if txt.strip():
            s.add(CommitteePassage(snapshot_id=snap.id, page=i, text_he=txt[:200000]))
    return status


def retire(s: Session, doc: CommitteeDocument) -> None:
    """Take an uploaded document out of the knowledge base (kept on disk and in the audit; searches skip it)."""
    doc.status, doc.sha256 = "retired", None


def uploads(s: Session, scope: str | None = None) -> list[dict]:
    """Uploaded documents with extraction and indexing progress. scope: None all, "national", or a committee id."""
    from .models import CommitteeChunk
    q = select(CommitteeDocument).where(CommitteeDocument.url.like("upload:%"))
    if scope == "national":
        q = q.where(CommitteeDocument.committee_id.is_(None))
    elif scope:
        q = q.where(CommitteeDocument.committee_id == scope)
    out = []
    for d in s.scalars(q.order_by(CommitteeDocument.id.desc()).limit(500)):
        snap = s.scalars(select(CommitteeSnapshot).where(CommitteeSnapshot.document_id == d.id)
                         .order_by(CommitteeSnapshot.id.desc())).first()
        passages = chunks = embedded = 0
        if snap:
            pids = select(CommitteePassage.id).where(CommitteePassage.snapshot_id == snap.id)
            passages = s.scalar(select(func.count()).select_from(CommitteePassage).where(CommitteePassage.snapshot_id == snap.id)) or 0
            chunks = s.scalar(select(func.count()).select_from(CommitteeChunk).where(CommitteeChunk.passage_id.in_(pids))) or 0
            embedded = s.scalar(select(func.count()).select_from(CommitteeChunk).where(CommitteeChunk.passage_id.in_(pids),
                                                                                         CommitteeChunk.model.is_not(None))) or 0
        c = s.get(PlanningCommittee, d.committee_id) if d.committee_id else None
        out.append({"id": d.id, "title": d.title, "kind": d.kind, "kind_he": UPLOAD_KINDS.get(d.kind, d.kind),
                    "committee_id": d.committee_id, "scope_he": c.name_he if c else NATIONAL_HE, "status": d.status,
                    "uploaded_by": (d.found_on or "").removeprefix("upload:") or None,
                    "uploaded_at": d.checked_at.isoformat() if d.checked_at else None,
                    "text_status": snap.text_status if snap else None, "pages": snap.pages if snap else 0,
                    "ocr_pages": snap.ocr_pages if snap else None,
                    "size": snap.size if snap else None, "passages": passages, "chunks": chunks, "embedded": embedded,
                    "message": d.message})
    return out
