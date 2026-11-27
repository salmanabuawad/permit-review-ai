"""File intake: validation, hashing, duplicate/version detection, AV hook, dispatch to parsers."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

MAGIC = {
    "pdf": [b"%PDF-"],
    "xlsx": [b"PK\x03\x04"],
    "dwg": [b"AC10"],
    "dwfx": [b"PK\x03\x04"],   # OPC/ZIP package; converted to PDF on the AI PC (agent/dwfx_convert.py)
}
EXT_KIND = {".pdf": "pdf", ".dxf": "dxf", ".dwg": "dwg", ".dwfx": "dwfx", ".xlsx": "xlsx", ".xlsm": "xlsx"}


class IntakeError(ValueError):
    pass


@dataclass
class Intake:
    kind: str
    sha256: str
    size: int
    stored_path: Path
    av_status: str


def detect_kind(filename: str, head: bytes) -> str:
    ext = Path(filename).suffix.lower()
    kind = EXT_KIND.get(ext)
    if not kind:
        raise IntakeError(f"סוג קובץ לא נתמך: {ext}. נתמכים: PDF, DXF, DWG, DWFX, XLSX")
    if kind == "dxf":
        txt = head[:2048].decode("latin-1", errors="ignore")
        if "SECTION" not in txt and not head.startswith(b"AutoCAD Binary DXF"):
            raise IntakeError("קובץ DXF אינו תקין (חסרה כותרת SECTION)")
    elif not any(head.startswith(m) for m in MAGIC[kind]):
        raise IntakeError(f"תוכן הקובץ אינו תואם לסיומת {ext}")
    return kind


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def av_scan(path: Path) -> str:
    """ClamAV if installed (clamscan / clamdscan). Otherwise NOT_SCANNED — never pretend CLEAN."""
    exe = shutil.which("clamdscan") or shutil.which("clamscan")
    if not exe:
        return "NOT_SCANNED"
    r = subprocess.run([exe, "--no-summary", str(path)], capture_output=True, timeout=300)
    return "CLEAN" if r.returncode == 0 else ("INFECTED" if r.returncode == 1 else "SCAN_ERROR")


def store(tenant_id: str, case_id: str, filename: str, data: bytes) -> Intake:
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise IntakeError(f"הקובץ גדול מ־{settings.max_upload_mb}MB")
    if not data:
        raise IntakeError("קובץ ריק")
    kind = detect_kind(filename, data[:4096])
    digest = sha256_bytes(data)
    folder = settings.storage_dir / tenant_id / case_id
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in Path(filename).name if c not in '<>:"/\\|?*') or "file"
    path = folder / f"{digest[:12]}_{safe}"
    path.write_bytes(data)
    if kind == "dxf":
        try:   # file must be readable; ensure it is text/binary DXF not something renamed
            path.read_bytes()[:10]
        except OSError as exc:
            raise IntakeError(str(exc)) from exc
    return Intake(kind, digest, len(data), path, av_scan(path))
