"""Crawl the official sources in the register, keep every version, and draft candidate rule clauses."""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile
import json
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..knowledge import sources_for_tenant
from ..models import RuleDraft, SourceCrawl, SourceDocument, SourceSnapshot, Municipality, CandidatePassage
from . import fetch as F
from .drafts import find_drafts

STALE_AFTER = dt.timedelta(minutes=30)
NO_DRAFT_CATEGORIES = {"TENDER", "DEMO", "INTERNAL"}     # tracked for changes, not a source of permit rules
EXT_BY_TYPE = {"application/pdf": ".pdf", "application/msword": ".doc",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
               "application/vnd.ms-excel": ".xls", "text/plain": ".txt",
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx"}


@lru_cache(maxsize=1)
def load_config() -> dict:
    return yaml.safe_load((settings.knowledge_dir / "source_monitor.yaml").read_text(encoding="utf-8"))


def storage_root() -> Path:
    p = settings.storage_dir / "_sources"
    p.mkdir(parents=True, exist_ok=True)
    return p


def register_targets(tenant_id: str | None = None, session: Session | None = None) -> list[dict]:
    """Every http(s) URL in the register. A URL shared by several sources (an index page) belongs to none."""
    owners: dict[str, list[str]] = {}
    for sid, src in sources_for_tenant(tenant_id).items():
        for key in ("document_url", "url", "url_2", "index_url"):
            u = src.get(key)
            if u and str(u).startswith(("http://", "https://")):
                owners.setdefault(F.canonical(u), [])
                if sid not in owners[F.canonical(u)]:
                    owners[F.canonical(u)].append(sid)
    sources = sources_for_tenant(tenant_id)
    out = []
    for url, sids in owners.items():
        sid = sids[0] if len(sids) == 1 else None
        out.append({"url": url, "source_id": sid, "title": sources[sid].get("title_he") if sid else None, "from": None})
    if session is not None and tenant_id:
        o = session.get(Municipality, tenant_id)
        from ..authority_onboarding import safe_url
        for u in (o.settings or {}).get('official_urls', []) if o else []:
            if safe_url(u) and F.canonical(u) not in owners:
                out.append({'url':F.canonical(u),'source_id':None,'title':None,'from':None,'discovery':True})
    return out


def allowed_hosts(tenant_id: str | None = None, session: Session | None = None) -> set[str]:
    hosts = {F.host(t["url"]) for t in register_targets(tenant_id, session)}
    return hosts | {h.lower() for h in load_config().get("extra_hosts", [])}


def _words(s: str) -> set[str]:
    import re
    return {w for w in re.split(r"[\s\-–—_,.:;()\"'״׳/]+", s or "") if len(w) > 1}


def match_register(url: str, text: str, tenant_id: str | None = None) -> str | None:
    """Register id for a discovered document: exact document_url, else a strong title match."""
    sources = sources_for_tenant(tenant_id)
    for sid, src in sources.items():
        if src.get("document_url") and F.canonical(src["document_url"]) == url:
            return sid
    words = _words(text)
    if len(words) >= 3:
        for sid, src in sources.items():
            title = _words(src.get("title_he", ""))
            if title and len(words & title) / len(words) >= 0.75:
                return sid
    return None


# ------------------------------------------------------------------ crawl

def start_crawl(session_factory, tenant: str, user: str, wait: bool = False,
                fetcher: Callable | None = None, sleep: Callable = time.sleep) -> str:
    """Create a crawl record and run it in a background thread (or inline when wait=True)."""
    with session_factory() as s:
        running = s.scalars(select(SourceCrawl).where(SourceCrawl.tenant_id == tenant, SourceCrawl.status == "running")).all()
        now = dt.datetime.now(dt.timezone.utc)
        for c in running:
            if now - c.started_at > STALE_AFTER:            # server restarted mid-crawl
                c.status, c.finished_at = "failed", now
                c.summary = {**(c.summary or {}), "error": "הסריקה הופסקה (השרת הופעל מחדש)"}
            else:
                raise RuntimeError("סריקה כבר רצה")
        crawl = SourceCrawl(tenant_id=tenant, triggered_by=user, summary={})
        s.add(crawl)
        audit.record(s, tenant, user, "source.crawl.start", "source_crawl", None, {})
        s.commit()
        cid = crawl.id

    def work():
        with session_factory() as s2:
            c = s2.get(SourceCrawl, cid)
            try:
                execute_crawl(s2, c, fetcher=fetcher, sleep=sleep)
            except Exception as e:                           # noqa: BLE001 — record, never crash the server
                s2.rollback()
                c = s2.get(SourceCrawl, cid)
                c.status, c.finished_at = "failed", dt.datetime.now(dt.timezone.utc)
                c.summary = {**(c.summary or {}), "error": str(e)[:500]}
                s2.commit()

    if wait:
        work()
    else:
        threading.Thread(target=work, name=f"source-crawl-{cid}", daemon=True).start()
    return cid


def execute_crawl(s: Session, crawl: SourceCrawl, fetcher: Callable | None = None, sleep: Callable = time.sleep) -> None:
    cfg = load_config()
    fetcher = fetcher or F.fetch
    tenant = crawl.tenant_id
    hosts = allowed_hosts(tenant, s)
    summary = {"checked": 0, "ok": 0, "new": 0, "changed": 0, "unchanged": 0, "blocked": 0, "unreachable": 0,
               "error": 0, "documents_found": 0, "links_ignored": 0, "drafts_new": 0, "skipped_limit": 0}
    queue = register_targets(tenant, s)
    visited: set[str] = set()
    last_host_hit: dict[str, float] = {}
    while queue:
        t = queue.pop(0)
        url = t["url"]
        if url in visited:
            continue
        visited.add(url)
        if summary["checked"] >= cfg["max_documents_per_crawl"]:
            summary["skipped_limit"] += 1
            continue
        h = F.host(url)
        wait_s = cfg["delay_between_requests_s"] - (time.monotonic() - last_host_hit.get(h, -1e9))
        if wait_s > 0:
            sleep(wait_s)
        doc = s.scalars(select(SourceDocument).where(SourceDocument.tenant_id == tenant, SourceDocument.url == url)).first()
        if not doc:
            doc = SourceDocument(tenant_id=tenant, url=url, kind="document", source_id=t.get("source_id"),
                                 title=t.get("title"), discovered_from=t.get("from"), links=[])
            s.add(doc)
            s.flush()
        elif t.get("source_id") and not doc.source_id:
            doc.source_id = t["source_id"]
        res = fetcher(url, cfg, hosts, doc.etag, doc.last_modified)
        last_host_hit[h] = time.monotonic()
        summary["checked"] += 1
        doc.last_checked = dt.datetime.now(dt.timezone.utc)
        doc.http_status, doc.message = res.http_status, res.message
        if res.status == "ok":
            summary["ok"] += 1
            doc.fetch_status = "ok"
            doc.etag, doc.last_modified = res.etag, res.last_modified
            if res.content_type in ("text/html", "application/xhtml+xml"):
                links = _apply_page(s, doc, res, cfg, summary)
                if t.get('discovery'):
                    links = links + F.discover_pages(F.decode_html(res.body), url, cfg)
                    doc.links = links
            else:
                links = []
                _apply_document(s, doc, res.body, res.content_type, crawl.id, None, summary)
        elif res.status == "not_modified":
            doc.fetch_status = "not_modified"
            doc.change_state = "unchanged"
            summary["unchanged"] += 1
            links = doc.links if doc.kind == "page" else []
        else:
            doc.fetch_status = res.status
            summary[res.status if res.status in summary else "error"] += 1
            links = []
        for ln in links:
            if ln["url"] not in visited:
                queue.append({"url": ln["url"], "source_id": match_register(ln["url"], ln["text"], tenant),
                              "title": ln["text"], "from": url, "discovery": t.get("discovery",False)})
        crawl.summary = dict(summary)
        s.commit()
    crawl.status, crawl.finished_at = "done", dt.datetime.now(dt.timezone.utc)
    crawl.summary = dict(summary)
    audit.record(s, tenant, crawl.triggered_by, "source.crawl.done", "source_crawl", crawl.id, summary)
    s.commit()


def _mark_change(doc: SourceDocument, new_hash: str, summary: dict) -> bool:
    """Update change_state from the content hash. Returns True if the content is new or changed."""
    if doc.sha256 is None:
        doc.change_state = "new"
    elif doc.sha256 != new_hash:
        doc.change_state = "changed"
    else:
        doc.change_state = "unchanged"
        summary["unchanged"] += 1
        return False
    summary[doc.change_state] += 1
    doc.sha256 = new_hash
    doc.changed_at = dt.datetime.now(dt.timezone.utc)
    doc.acknowledged, doc.acknowledged_by = False, None
    return True


def _apply_page(s: Session, doc: SourceDocument, res: F.Fetched, cfg: dict, summary: dict) -> list[dict]:
    doc.kind, doc.content_type, doc.size = "page", res.content_type, len(res.body)
    text = F.decode_html(res.body)
    doc.title = doc.title or F.page_title(text)
    links, ignored = (F.discover_links(text, doc.url, cfg) if cfg.get("discover_links_from_pages", True) else ([], 0))
    summary["documents_found"] += len(links)
    summary["links_ignored"] += ignored
    # a page "changes" when the set of documents it links to changes — not on every cosmetic HTML change
    digest = hashlib.sha256(json.dumps(links, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    _mark_change(doc, digest, summary)
    doc.links = links
    return links


def _apply_document(s: Session, doc: SourceDocument, body: bytes, content_type: str | None, crawl_id: str | None,
                    uploaded_by: str | None, summary: dict) -> SourceSnapshot | None:
    doc.kind = "manual" if uploaded_by and doc.kind == "manual" else "document"
    doc.content_type, doc.size = content_type, len(body)
    doc.message = None
    sha = hashlib.sha256(body).hexdigest()
    if not _mark_change(doc, sha, summary):
        return None
    ext = EXT_BY_TYPE.get(content_type or "") or Path(F.urlsplit(doc.url).path).suffix.lower() or ".bin"
    path = storage_root() / f"{sha}{ext}"
    if not path.exists():
        path.write_bytes(body)
    doc.storage_path = str(path)
    pages: list[str] = []
    doc.page_count = None
    try:
        pages = extract_text(body, ext)
        if ext == '.pdf': doc.page_count = len(pages)
    except Exception as e:
        doc.message = f"לא ניתן לחלץ טקסט: {type(e).__name__}"
    if not any(p.strip() for p in pages):
        doc.message = "לא חולץ טקסט — ייתכן שנדרש OCR או פורמט נתמך"

    snap = SourceSnapshot(tenant_id=doc.tenant_id, document_id=doc.id, crawl_id=crawl_id, sha256=sha, size=len(body),
                          storage_path=str(path), origin="upload" if uploaded_by else "crawl", uploaded_by=uploaded_by,
                          text_chars=sum(len(p) for p in pages))
    s.add(snap)
    s.flush()
    category = sources_for_tenant(doc.tenant_id).get(doc.source_id or "", {}).get("category")
    if pages and category in NO_DRAFT_CATEGORIES:
        doc.message = "נשמר לצורך מעקב שינויים בלבד — אינו מקור לכללי בדיקה"
    elif pages:
        for i, page in enumerate(pages,1):
            for start in range(0,len(page),3500):
                text=page[start:start+4000].strip()
                if text: s.add(CandidatePassage(tenant_id=doc.tenant_id,document_id=doc.id,snapshot_id=snap.id,page=i,text_he=text))
        summary["drafts_new"] += _store_drafts(s, doc, snap, pages)
    elif doc.page_count is None and not doc.message:
        doc.message = "לא חולץ טקסט (המסמך אינו PDF או שהוא סרוק)"
    return snap


def _store_drafts(s: Session, doc: SourceDocument, snap: SourceSnapshot, pages: list[str]) -> int:
    found = find_drafts(pages, load_config().get("max_drafts_per_document", 300))
    existing = {d.key: d for d in s.scalars(select(RuleDraft).where(RuleDraft.tenant_id == doc.tenant_id,
                                                                    RuleDraft.document_id == doc.id))}
    keys = {d.key for d in found}
    new = 0
    for d in found:
        old = existing.get(d.key)
        if old:
            old.page, old.section, old.snapshot_id = d.page, d.section, snap.id
            if old.status == "superseded":
                old.status = "open"
            continue
        s.add(RuleDraft(tenant_id=doc.tenant_id, document_id=doc.id, snapshot_id=snap.id, key=d.key, page=d.page,
                        section=d.section, kind=d.kind, topics=d.topics, text_he=d.text_he, values=d.values))
        new += 1
    for k, old in existing.items():                      # clause no longer in the new version
        if k not in keys and old.status in ("open", "for_authoring"):
            old.status = "superseded"
    return new


def validate_upload(body: bytes, ext: str) -> str:
    if not body: raise ValueError('קובץ ריק')
    if ext == '.pdf':
        if not body.startswith(b'%PDF-'): raise ValueError('PDF לא תקין')
        try:
            import pymupdf
            with pymupdf.open(stream=body,filetype='pdf') as f:
                if f.needs_pass or f.page_count < 1: raise ValueError('PDF מוצפן או ריק')
        except Exception as e: raise ValueError('PDF לא קריא') from e
        return 'application/pdf'
    if ext == '.txt':
        try: body.decode('utf-8-sig')
        except UnicodeError as e: raise ValueError('נדרש TXT בקידוד UTF-8') from e
        if b'\x00' in body: raise ValueError('TXT בינארי')
        return 'text/plain'
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            infos=z.infolist()
            if len(infos)>10000 or sum(i.file_size for i in infos)>160*1024**2 or any(i.flag_bits & 1 for i in infos): raise ValueError('ארכיון לא בטוח')
            if ('word/document.xml' if ext=='.docx' else 'xl/workbook.xml') not in z.namelist(): raise ValueError('פורמט לא תואם')
    except (zipfile.BadZipFile,ValueError) as e: raise ValueError('קובץ Office לא תקין או גדול מדי') from e
    return 'application/vnd.openxmlformats-officedocument.'+('wordprocessingml.document' if ext=='.docx' else 'spreadsheetml.sheet')


def extract_text(body: bytes, ext: str) -> list[str]:
    if ext not in ('.pdf','.docx','.xlsx','.txt'): return []
    validate_upload(body,ext)
    if ext=='.pdf':
        import pymupdf
        with pymupdf.open(stream=body,filetype='pdf') as f: return [p.get_text() for p in f]
    if ext=='.txt': return [body.decode('utf-8-sig')]
    if ext=='.docx':
        from docx import Document
        d=Document(io.BytesIO(body));return ['\n'.join([p.text for p in d.paragraphs]+[' | '.join(c.text for c in row.cells) for t in d.tables for row in t.rows])]
    import openpyxl
    w=openpyxl.load_workbook(io.BytesIO(body),read_only=True,data_only=True,keep_links=False)
    try:
        return [sheet.title+'\n'+'\n'.join(' | '.join(str(x) if x is not None else '' for x in row) for row in sheet.iter_rows(max_row=min(sheet.max_row or 1,20000),max_col=min(sheet.max_column or 1,200),values_only=True)) for sheet in w.worksheets[:100]]
    finally: w.close()


def ingest_upload(s: Session, tenant: str, user: str, filename: str, body: bytes, content_type: str | None,
                  document_id: int | None = None, source_id: str | None = None) -> SourceDocument:
    """Manual upload for a source the server cannot fetch (blocked / unreachable site)."""
    if document_id is not None:
        doc = s.get(SourceDocument, document_id)
        if not doc or doc.tenant_id != tenant:
            raise LookupError("מסמך מקור לא נמצא")
    elif source_id is None:
        # Hash-addressed independent upload, never overwrite a different regulation.
        sha=hashlib.sha256(body).hexdigest()
        url=f"upload:sha256:{sha}"
        doc=s.scalars(select(SourceDocument).where(SourceDocument.tenant_id==tenant,SourceDocument.url==url)).first()
        if not doc:
            doc=SourceDocument(tenant_id=tenant,url=url,kind="manual",title=Path(filename).name[:400],links=[])
            s.add(doc);s.flush()
    else:
        if source_id not in sources_for_tenant(tenant):
            raise LookupError("מקור לא מוכר ברשם המקורות")
        url = f"upload:{source_id}"
        doc = s.scalars(select(SourceDocument).where(SourceDocument.tenant_id == tenant, SourceDocument.url == url)).first()
        if not doc:
            doc = SourceDocument(tenant_id=tenant, url=url, kind="manual", source_id=source_id,
                                 title=sources_for_tenant(tenant)[source_id].get("title_he"), links=[])
            s.add(doc)
            s.flush()
    if not body:
        raise ValueError("קובץ ריק")
    ext=Path(filename).suffix.lower()
    if ext in ('.pdf','.docx','.xlsx','.txt'):
        content_type=validate_upload(body,ext)
    else:
        raise ValueError('פורמט נתמך להעלאת ידע: PDF, DOCX, XLSX, TXT')
    summary = {"new": 0, "changed": 0, "unchanged": 0, "drafts_new": 0}
    if doc.kind == "page":
        raise ValueError("זהו עמוד אינטרנט — יש להעלות את המסמך עצמו דרך המקור ברשם")
    snap = _apply_document(s, doc, body, content_type, None, user, summary)
    doc.fetch_status = "manual" if doc.kind == "manual" else doc.fetch_status
    doc.last_checked = dt.datetime.now(dt.timezone.utc)
    audit.record(s, tenant, user, "source.upload", "source_document", str(doc.id),
                 {"file": filename, "sha256": doc.sha256, "new_version": snap is not None, **summary})
    return doc
