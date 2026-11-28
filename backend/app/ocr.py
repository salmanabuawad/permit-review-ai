"""OCR for knowledge-base PDFs that have no text layer (scanned plans, protocols, old regulations).

Runs on the server with Tesseract (Hebrew + English + Arabic models, installed from the distribution) — no document
leaves the server. A background thread in the application process works through committee snapshots whose
text_status is "empty", a few pages at a time, and records progress per page (committee_snapshots.ocr_pages), so a
restart loses at most the pages being read at that moment. Each page is rendered and read in its own
resource-limited child process (an untrusted PDF must not take the application down). Recognised text is stored as
ordinary passages, so clause extraction and embedding pick it up as for any other text; the snapshot becomes
text_status "ocr" (text from OCR — unverified, may contain recognition errors).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import func, select

from .safe_extract import BACKEND

log = logging.getLogger("bbp.ocr")

LANGS = "heb+eng"
DPI = 300
MAX_SIDE = 7000              # px; large plan sheets are scaled down (an A3 page at 300 dpi is 4961 px)
MIN_CHARS = 20               # below this a page counts as "no text" (same threshold as case intake)
MEMORY_BYTES = 1536 * 1024 * 1024
CPU_SECONDS = 150
WALL_SECONDS = 240
PARALLEL = max(1, int(os.environ.get("BBP_OCR_PARALLEL", "2")))   # pages read at the same time (the server has 4 cores)
BATCH = 8                    # pages per pass before the queue is looked at again

_CHILD = (
    "import subprocess, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import pymupdf\n"
    "path, n, png, dpi, side, langs = sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5]), int(sys.argv[6]), sys.argv[7]\n"
    "with pymupdf.open(path) as d:\n"
    "    p = d[n - 1]\n"
    "    z = min(dpi / 72, side / max(p.rect.width, p.rect.height, 1))\n"
    "    p.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY).save(png)\n"
    "r = subprocess.run(['tesseract', png, 'stdout', '-l', langs, '--psm', '3'], capture_output=True)\n"
    "if r.returncode:\n"
    "    sys.stderr.write(r.stderr.decode('utf-8', 'ignore')); sys.exit(2)\n"
    "sys.stdout.write(r.stdout.decode('utf-8', 'ignore'))\n"
)


def _limits():                                   # runs in the child, before exec
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


_avail: bool | None = None


def available() -> bool:
    """Tesseract with the Hebrew model is installed."""
    global _avail
    if _avail is None:
        try:
            out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, timeout=20) if shutil.which("tesseract") else None
            _avail = bool(out and out.returncode == 0 and "heb" in out.stdout.decode("utf-8", "ignore").split())
        except (OSError, subprocess.SubprocessError):
            _avail = False
    return _avail


def read_page(path: Path, page: int) -> str:
    """Text of one PDF page (1-based) by OCR; raises ValueError with a short reason."""
    with tempfile.NamedTemporaryFile(suffix=".png") as png:
        try:
            out = subprocess.run([sys.executable, "-c", _CHILD, BACKEND, str(path), str(page), png.name, str(DPI),
                                  str(MAX_SIDE), LANGS], capture_output=True, timeout=WALL_SECONDS,
                                 preexec_fn=_limits, close_fds=True,
                                 env={**{k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR")},
                                      "OMP_THREAD_LIMIT": "1"})
        except subprocess.TimeoutExpired as e:
            raise ValueError("OCR חרג מזמן מוקצב") from e
        if out.returncode != 0:
            last = (out.stderr.decode("utf-8", "ignore").strip().splitlines() or ["?"])[-1]
            raise ValueError(f"OCR נכשל: {last[:160]}")
        return out.stdout.decode("utf-8", "ignore")


def _queue(s):
    from .models import CommitteeDocument, CommitteeSnapshot
    return (select(CommitteeSnapshot).join(CommitteeDocument, CommitteeSnapshot.document_id == CommitteeDocument.id)
            .where(CommitteeSnapshot.text_status == "empty", CommitteeSnapshot.path.like("%.pdf"),
                   CommitteeSnapshot.pages > 0, func.coalesce(CommitteeSnapshot.ocr_pages, 0) < CommitteeSnapshot.pages,
                   CommitteeDocument.sha256 == CommitteeSnapshot.sha256, CommitteeDocument.status != "retired"))


def pending(s) -> dict:
    """Snapshots and pages still waiting for OCR."""
    q = _queue(s).subquery()
    docs, pages, done = s.execute(select(func.count(), func.coalesce(func.sum(q.c.pages), 0),
                                         func.coalesce(func.sum(func.coalesce(q.c.ocr_pages, 0)), 0))).one()
    return {"documents": docs, "pages": int(pages) - int(done)}


def run_batch(s, max_pages: int = BATCH, reader=None) -> dict:
    """OCR the next pages of the next scanned snapshot. Returns {"pages": n read, "snapshot": id or None}."""
    from .committee_docs import clean, store_root
    from .models import CommitteeDocument, CommitteePassage, CommitteeSnapshot
    reader = reader or read_page
    snap = s.scalars(_queue(s).order_by(CommitteeDocument.committee_id.is_not(None), CommitteeSnapshot.id).limit(1)).first()
    if snap is None:
        return {"pages": 0, "snapshot": None}
    path = store_root() / snap.path
    start = (snap.ocr_pages or 0) + 1
    todo = list(range(start, min(snap.pages, start + max_pages - 1) + 1))
    if not path.exists():                                   # file gone: nothing to read, do not retry forever
        snap.ocr_pages = snap.pages
        s.commit()
        return {"pages": 0, "snapshot": snap.id}

    def one(n):
        try:
            return n, reader(path, n), None
        except ValueError as e:
            return n, "", str(e)

    with ThreadPoolExecutor(max_workers=min(PARALLEL, len(todo))) as pool:
        results = list(pool.map(one, todo))
    have = {p for (p,) in s.execute(select(CommitteePassage.page).where(CommitteePassage.snapshot_id == snap.id))}
    for n, text, err in results:
        text = clean(text)
        if err:
            log.info("ocr snapshot %s page %s: %s", snap.id, n, err)
        elif len(text.strip()) >= MIN_CHARS and n not in have:
            s.add(CommitteePassage(snapshot_id=snap.id, page=n, text_he=text[:200000]))
    snap.ocr_pages = todo[-1]
    if snap.ocr_pages >= snap.pages:
        found = s.scalar(select(func.count()).select_from(CommitteePassage).where(CommitteePassage.snapshot_id == snap.id))
        if found:
            snap.text_status = "ocr"
    s.commit()
    return {"pages": len(todo), "snapshot": snap.id}


# ---------------------------------------------------------------- background thread (application process)

_wake = threading.Event()
_lock = threading.Lock()
_started = False


def worker(factory) -> None:
    while True:
        try:
            with factory() as s:
                out = run_batch(s)
            if out["snapshot"] is not None:
                continue
        except Exception:  # noqa: BLE001 — the worker never dies
            log.exception("ocr")
            time.sleep(60)
        _wake.wait(600)
        _wake.clear()


def kick(factory=None) -> None:
    """Start (or wake) the OCR thread: one per application process."""
    global _started
    if not available():
        return
    with _lock:
        if not _started:
            if factory is None:
                from .db import SessionLocal as factory  # noqa: N813
            threading.Thread(target=worker, args=(factory,), daemon=True, name="ocr").start()
            _started = True
    _wake.set()

