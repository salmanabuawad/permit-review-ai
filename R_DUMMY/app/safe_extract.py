"""Text extraction from untrusted documents in a separate, resource-limited process.

PDF / Office parsers are large native libraries; a hostile or broken file must not be able to exhaust the crawler's
memory, spin forever or take the worker down. The child process gets a memory cap, a CPU-time cap, a wall-clock
timeout and no inherited file descriptors, and returns the page texts as JSON on stdout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = str(Path(__file__).resolve().parents[1])
MEMORY_BYTES = 1536 * 1024 * 1024
CPU_SECONDS = 90
WALL_SECONDS = 120

_CHILD = (
    "import json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from app.source_monitor.service import extract_text\n"
    "body = open(sys.argv[2], 'rb').read()\n"
    "pages = extract_text(body, sys.argv[3])\n"
    "with open(sys.argv[4], 'w', encoding='utf-8') as out:\n"
    "    json.dump(pages, out, ensure_ascii=False)\n"
)


def _limits():                                   # runs in the child, before exec
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


def extract(body: bytes, ext: str) -> list[str]:
    """Page texts, or raises ValueError with a short reason."""
    if ext not in (".pdf", ".docx", ".xlsx", ".txt"):
        return []
    # the result goes to a file: parsers may print warnings on stdout, which must not corrupt it
    with tempfile.NamedTemporaryFile(suffix=ext) as f, tempfile.NamedTemporaryFile(suffix=".json") as res:
        f.write(body)
        f.flush()
        try:
            out = subprocess.run([sys.executable, "-c", _CHILD, BACKEND, f.name, ext, res.name], capture_output=True,
                                 timeout=WALL_SECONDS, preexec_fn=_limits, close_fds=True,
                                 env={k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "HOME") or k.startswith("BBP_")})
        except subprocess.TimeoutExpired as e:
            raise ValueError("חילוץ הטקסט חרג מזמן מוקצב") from e
        if out.returncode != 0:
            last = (out.stderr.decode("utf-8", "ignore").strip().splitlines() or ["?"])[-1]
            raise ValueError(f"חילוץ הטקסט נכשל: {last[:160]}")
        try:
            pages = json.loads(Path(res.name).read_text(encoding="utf-8") or "[]")
        except ValueError as e:
            raise ValueError("חילוץ הטקסט החזיר תוצאה לא תקינה") from e
    return [p if isinstance(p, str) else "" for p in pages]
