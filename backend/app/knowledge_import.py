"""ZIP import into the AI knowledge base (superadmin): an archive of many documents, up to a few GB.

The upload is streamed to disk (never into memory), then a background thread inside the application adds each PDF,
DOCX or XLSX in the archive as its own knowledge document through committee_docs.upload — the same checks, sandboxed
text extraction and duplicate handling as a single upload; the crawler worker splits and embeds them when idle.
Progress lives in a small JSON file next to the archive, so an import interrupted by a restart resumes where it
stopped. The archive is deleted when the import finishes (the documents themselves are kept in storage).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from .config import settings

MAX_ZIP = 8 * 1024 ** 3            # the archive as uploaded
MAX_MEMBERS = 50_000
MAX_RATIO = 200                    # zip-bomb guard per member (uncompressed / compressed)
MAX_ERRORS_KEPT = 300
_wake = threading.Event()
_started = False
_lock = threading.Lock()


def import_dir() -> Path:
    d = settings.storage_dir / "knowledge_imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _write(job: dict) -> None:
    p = import_dir() / f"{job['id']}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False))
    os.replace(tmp, p)


def _read(job_id: str) -> dict | None:
    p = import_dir() / f"{job_id}.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def jobs(limit: int = 20) -> list[dict]:
    out = []
    for p in sorted(import_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return out


def member_name(info: zipfile.ZipInfo) -> str:
    """Archive names without the UTF-8 flag are CP437 bytes as far as zipfile knows: archives made on Windows hold
    UTF-8 or the Hebrew DOS code page there — recover either."""
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode("cp437", errors="replace")
    for enc in ("utf-8", "cp862", "cp1255"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return info.filename


def save_upload(src, filename: str, committee_id: str | None, scope: str, kind: str, user: str, tenant: str) -> dict:
    """Copy the uploaded archive (a file object already on disk) into the import folder and queue it."""
    from . import committee_docs as CD
    if kind not in CD.UPLOAD_KINDS:
        raise ValueError("סוג מסמך לא מוכר")
    job_id = uuid.uuid4().hex[:12]
    part = import_dir() / f"{job_id}.zip.part"
    size = 0
    src.seek(0)
    with open(part, "wb") as out:
        while chunk := src.read(8 * 1024 * 1024):
            size += len(chunk)
            if size > MAX_ZIP:
                out.close()
                part.unlink(missing_ok=True)
                raise ValueError("הארכיון גדול מ־8 GB")
            out.write(chunk)
    if not zipfile.is_zipfile(part):
        part.unlink(missing_ok=True)
        raise ValueError("הקובץ אינו ארכיון ZIP תקין")
    try:
        with zipfile.ZipFile(part) as z:
            total = sum(1 for i in z.infolist() if not i.is_dir())
    except (zipfile.BadZipFile, OSError) as e:
        part.unlink(missing_ok=True)
        raise ValueError("הקובץ אינו ארכיון ZIP תקין") from e
    if total > MAX_MEMBERS:
        part.unlink(missing_ok=True)
        raise ValueError(f"יותר מ־{MAX_MEMBERS} קבצים בארכיון")
    os.replace(part, import_dir() / f"{job_id}.zip")
    job = {"id": job_id, "filename": (filename or "archive.zip")[:300], "size": size, "committee_id": committee_id,
           "scope": scope, "kind": kind, "user": user, "tenant": tenant, "status": "queued", "total": total,
           "processed": 0, "added": 0, "duplicate": 0, "skipped": 0, "failed": 0, "errors": [],
           "created_at": _now(), "started_at": None, "finished_at": None}
    _write(job)
    return job


def kick() -> None:
    """Start (or wake) the import thread after an archive was queued."""
    start_worker()
    _wake.set()


def _note(job: dict, name: str, reason: str) -> None:
    if len(job["errors"]) < MAX_ERRORS_KEPT:
        job["errors"].append({"name": name[-200:], "reason": reason[:200]})


def process(job: dict, factory) -> dict:
    """Add the archive's documents, from job["processed"] on. Safe to run again: the same file is one document."""
    from . import audit
    from . import committee_docs as CD
    from .models import CommitteeDocument
    path = import_dir() / f"{job['id']}.zip"
    job["status"], job["started_at"] = "running", job.get("started_at") or _now()
    _write(job)
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        job["status"], job["finished_at"], job["message"] = "failed", _now(), "הארכיון לא נפתח"
        _write(job)
        return job
    with z:
        members = [i for i in z.infolist() if not i.is_dir()]
        job["total"] = len(members)
        for idx in range(job["processed"], len(members)):
            info = members[idx]
            name = member_name(info)
            base = PurePosixPath(name.replace("\\", "/")).name
            ext = PurePosixPath(base.lower()).suffix
            try:
                if not base or base.startswith(".") or "__MACOSX" in name:
                    job["skipped"] += 1
                elif ext == ".zip":
                    job["skipped"] += 1
                    _note(job, name, "ארכיון בתוך ארכיון — לא נפתח")
                elif ext not in CD.DOC_EXT:
                    job["skipped"] += 1
                    _note(job, name, "סוג קובץ לא נתמך")
                elif info.file_size > CD.MAX_UPLOAD:
                    job["skipped"] += 1
                    _note(job, name, "גדול מ־50 MB")
                elif info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                    job["skipped"] += 1
                    _note(job, name, "יחס דחיסה חשוד")
                else:
                    with z.open(info) as f:
                        body = f.read(CD.MAX_UPLOAD + 1)
                    url = f"upload:{hashlib.sha256(body).hexdigest()}"
                    with factory() as s:
                        q = select(CommitteeDocument.id).where(CommitteeDocument.url == url)
                        q = q.where(CommitteeDocument.committee_id.is_(None) if job["committee_id"] is None
                                    else CommitteeDocument.committee_id == job["committee_id"])
                        existed = s.scalar(q) is not None
                        title = "" if existed else PurePosixPath(base).stem      # a copy keeps the first title
                        doc = CD.upload(s, job["committee_id"], body, base, job["kind"], title, job["user"])
                        audit.record(s, job["tenant"], job["user"], "knowledge.upload", "committee_document",
                                     str(doc.id), {"scope": job["scope"], "kind": job["kind"], "url": doc.url,
                                                   "import": job["id"], "member": name[-300:]})
                        s.commit()
                    job["duplicate" if existed else "added"] += 1
            except ValueError as e:
                job["failed"] += 1
                _note(job, name, str(e))
            except Exception as e:  # noqa: BLE001 — one bad document never stops the import
                job["failed"] += 1
                _note(job, name, f"שגיאה בעיבוד ({type(e).__name__})")
            job["processed"] = idx + 1
            _write(job)
    job["status"], job["finished_at"] = "done", _now()
    _write(job)
    path.unlink(missing_ok=True)
    return job


def _pending() -> dict | None:
    for j in sorted(jobs(limit=1000), key=lambda x: x.get("created_at") or ""):
        if j.get("status") in ("queued", "running") and (import_dir() / f"{j['id']}.zip").exists():
            return j
    return None


def worker(factory) -> None:
    while True:
        try:
            j = _pending()
            if j:
                process(j, factory)
                continue
        except Exception:  # noqa: BLE001 — the worker never dies
            time.sleep(30)
        _wake.wait(300)
        _wake.clear()


def start_worker(factory=None) -> None:
    """One import thread per application process (the application runs a single worker)."""
    global _started
    with _lock:
        if _started:
            return
        if factory is None:
            from .db import SessionLocal as factory  # noqa: N813
        threading.Thread(target=worker, args=(factory,), daemon=True, name="knowledge-import").start()
        _started = True
