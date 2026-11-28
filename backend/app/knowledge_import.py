"""ZIP import into the AI knowledge base (superadmin): an archive of many documents, up to a few GB.

The upload is streamed to disk (never into memory), then a background thread inside the application adds each PDF,
DOCX or XLSX in the archive as its own knowledge document through committee_docs.upload — the same checks, sandboxed
text extraction and duplicate handling as a single upload; the crawler worker splits and embeds them when idle.
Progress lives in a small JSON file next to the archive, so an import interrupted by a restart resumes where it
stopped. The archive is deleted when the import finishes (the documents themselves are kept in storage).

Regulation360 exports are understood: a file under ui_upload/<NNN>_<NATIONAL | code>_<committee name>/ goes to that
scope (committees matched by Hebrew name), with the type, title and official address from the folder's index.csv
(columns kind, title, source_url; else the subfolder name, else the import's type); main_system/ server packages are not imported but kept in <job>-server/ for an
operator to install into knowledge/.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from .config import settings

log = logging.getLogger(__name__)

MAX_ZIP = 8 * 1024 ** 3            # the archive as uploaded
MAX_MEMBERS = 1_000_000        # Regulation360 exports carry ~45k page texts per few committees
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
    try:
        raw = info.filename.encode("cp437")
    except UnicodeEncodeError:      # already decoded properly (e.g. from the Unicode Path extra field)
        return info.filename
    for enc in ("utf-8", "cp862", "cp1255"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return info.filename


def mb(n: int) -> str:
    return f"{n / 1024 ** 3:.2f} GB" if n >= 1024 ** 3 else f"{max(1, round(n / 1024 ** 2))} MB"


def sniff(path: Path, size: int) -> str:
    """Why a file named .zip is not one: another archive format renamed, one part of a split archive, or cut off."""
    with open(path, "rb") as f:
        head = f.read(8)
        f.seek(max(0, size - 1024 * 1024))
        tail = f.read()
    if size == 0:
        return "הקובץ ריק"
    if head.startswith(b"Rar!"):
        return "זהו ארכיון RAR — יש לשמור כ־ZIP"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "זהו ארכיון 7-Zip — יש לשמור כ־ZIP"
    if head.startswith(b"PK\x07\x08"):
        return "חלק ראשון של ארכיון מפוצל — יש ליצור ZIP אחד שלם"
    if head.startswith(b"PK\x03\x04"):
        if b"PK\x05\x06" not in tail:
            return "סוף הארכיון חסר — ייתכן שהקובץ נקטע או שזהו חלק מארכיון מפוצל"
        return "מבנה הארכיון פגום"
    if head.startswith((b"\x1f\x8b", b"BZh", b"\xfd7zXZ")):
        return "זהו קובץ דחוס מסוג אחר (gz/bz2/xz) — יש לשמור כ־ZIP"
    return "סוג הקובץ אינו ZIP"


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
        why = sniff(part, size)
        part.unlink(missing_ok=True)
        log.warning("knowledge import rejected: %s bytes, %s", size, why)
        raise ValueError(f"הקובץ אינו ארכיון ZIP תקין: {why} ({mb(size)})")
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


# Regulation360 exports: ui_upload/<NNN>_<NATIONAL | committee code>_<committee name>/… — the folder sets the scope;
# main_system/ holds server packages (installed into knowledge/ by an operator, not through this import).
SCOPE_DIR = re.compile(r"^\d{1,4}_(NATIONAL|[A-Z]{1,3}-[A-Z]{1,3}-\d{1,4})_(.*)$")
SERVER_KEEP = re.compile(r"(^|/)main_system/(packages/[^/]+\.zip|manifest\.json|IMPORT_README\.md)$")


def _key(name: str) -> str:
    return re.sub(r"[\s\-\u05be\u2013\u2014\"'״׳]", "", name or "")


def folder_scope(name: str, s, cache: dict) -> tuple[str, str | None, str, str] | None:
    """("national", None, label, root) / ("committee", id, label, root) / ("missing", None, label, root) for a file
    inside a scope folder (root = the path up to that folder); None when the path has no scope folder."""
    from .models import PlanningCommittee
    parts = name.split("/")
    for n, seg in enumerate(parts[:-1]):
        m = SCOPE_DIR.match(seg)
        if not m:
            continue
        code, label, root = m.group(1), m.group(2).strip(), "/".join(parts[:n + 1])
        if code == "NATIONAL":
            return ("national", None, label or code, root)
        if seg not in cache:
            if "names" not in cache:
                cache["names"] = {_key(n): i for i, n in s.execute(select(PlanningCommittee.id, PlanningCommittee.name_he))}
            cache[seg] = cache["names"].get(_key(label))
        cid = cache[seg]
        return ("committee", cid, label, root) if cid else ("missing", None, f"{code} {label}", root)


def folder_index(z: zipfile.ZipFile, names: dict, root: str, cache: dict) -> dict:
    """The scope folder's index.csv (file → kind, title, source_url), when the export has one."""
    key = f"index:{root}"
    if key not in cache:
        cache[key] = {}
        info = names.get(f"{root}/index.csv")
        if info is not None and info.file_size < 50 * 1024 * 1024:
            try:
                text = z.read(info).decode("utf-8-sig", errors="replace")
                for row in csv.DictReader(io.StringIO(text)):
                    if row.get("file"):
                        cache[key][row["file"].replace("\\", "/")] = (row.get("kind") or "", (row.get("title") or "").strip(),
                                                                    (row.get("source_url") or "").strip())
            except (csv.Error, OSError, zipfile.BadZipFile):
                pass
    return cache[key]
    return None


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
    cache: dict = {}
    job.setdefault("server_packages", 0)
    job.setdefault("scopes", {})
    with z:
        members = [i for i in z.infolist() if not i.is_dir()]
        names = {member_name(i).replace("\\", "/"): i for i in members}
        job["total"] = len(members)
        for idx in range(job["processed"], len(members)):
            info = members[idx]
            name = member_name(info).replace("\\", "/")
            base = PurePosixPath(name).name
            ext = PurePosixPath(base.lower()).suffix
            wrote = False
            try:
                if "/main_system/" in f"/{name}":
                    job["skipped"] += 1
                    if SERVER_KEEP.search(name):            # kept for the operator to install into knowledge/
                        rel = name[name.index("main_system/") + len("main_system/"):]
                        dest = import_dir() / f"{job['id']}-server" / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(info) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out, 8 * 1024 * 1024)
                        job["server_packages"] += 1
                elif any(seg.startswith("_") for seg in name.split("/")[:-1]):
                    job["skipped"] += 1                     # _cache/, __MACOSX/ … — working folders, not documents
                elif not base or base.startswith(".") or base in ("index.csv", "summary.json"):
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
                    with factory() as s:
                        fs = folder_scope(name, s, cache)
                        if fs and fs[0] == "missing":
                            raise ValueError(f"ועדה לא נמצאה: {fs[2]}")
                        cid = fs[1] if fs else job["committee_id"]
                        label = fs[2] if fs else job["scope"]
                        kind, title_hint, source_url = job["kind"], "", None
                        if fs:                              # type and title from the folder's index.csv / subfolder
                            rel = name[len(fs[3]) + 1:]
                            k, title_hint, source_url = folder_index(z, names, fs[3], cache).get(rel, ("", "", ""))
                            sub = rel.split("/")[0] if "/" in rel else ""
                            kind = k if k in CD.UPLOAD_KINDS else sub if sub in CD.UPLOAD_KINDS else job["kind"]
                        with z.open(info) as f:
                            body = f.read(CD.MAX_UPLOAD + 1)
                        url = f"upload:{hashlib.sha256(body).hexdigest()}"
                        q = select(CommitteeDocument.id).where(CommitteeDocument.url == url)
                        q = q.where(CommitteeDocument.committee_id.is_(None) if cid is None
                                    else CommitteeDocument.committee_id == cid)
                        existed = s.scalar(q) is not None
                        title = "" if existed else (title_hint or PurePosixPath(base).stem)  # a copy keeps the first title
                        doc = CD.upload(s, cid, body, base, kind, title, job["user"], source_url=source_url)
                        audit.record(s, job["tenant"], job["user"], "knowledge.upload", "committee_document",
                                     str(doc.id), {"scope": cid or "national", "kind": kind, "url": doc.url, "source_url": doc.source_url,
                                                   "import": job["id"], "member": name[-300:]})
                        s.commit()
                    job["duplicate" if existed else "added"] += 1
                    job["scopes"][label] = job["scopes"].get(label, 0) + 1
                    wrote = True
            except ValueError as e:
                job["failed"] += 1
                _note(job, name, str(e))
            except Exception as e:  # noqa: BLE001 — one bad document never stops the import
                job["failed"] += 1
                _note(job, name, f"שגיאה בעיבוד ({type(e).__name__})")
            job["processed"] = idx + 1
            if wrote or idx % 200 == 0 or idx + 1 == len(members):
                _write(job)
    _retry_failed_text(job, factory)
    job["status"], job["finished_at"] = "done", _now()
    _write(job)
    path.unlink(missing_ok=True)
    from .config import settings
    if settings.ocr_worker:                    # scanned PDFs in the archive: OCR in the background
        from . import ocr
        ocr.kick()
    return job


def _retry_failed_text(job: dict, factory) -> None:
    """Uploads whose text extraction failed (a service restart during the import stops the extraction running at
    that moment): try each once more from the stored file."""
    from . import committee_docs as CD
    from .models import CommitteeDocument, CommitteeSnapshot
    with factory() as s:
        ids = s.scalars(select(CommitteeDocument.id).join(CommitteeSnapshot, CommitteeSnapshot.document_id == CommitteeDocument.id)
                        .where(CommitteeDocument.url.like("upload:%"), CommitteeDocument.found_on == f"upload:{job['user']}",
                               CommitteeSnapshot.text_status == "failed")).all()
    fixed = 0
    for i in ids:
        with factory() as s:
            if CD.reextract(s, s.get(CommitteeDocument, i)) != "failed":
                fixed += 1
            s.commit()
    job["text_retried"], job["text_fixed"] = len(ids), fixed


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
