"""Legacy DWF (DWF 6 package / W2D stream) intake — V9 §Run and integrate 2.

A W2D stream is Autodesk's binary WHIP format. Decoding its geometry needs a licensed decoder (Autodesk DWF Toolkit,
ODA Drawings SDK, or a validated ezdwf build). None is installed or licensed on this system, so this module:

  * opens the package safely (archive limits, no path traversal, bounded expansion),
  * records the file SHA-256, every section and stream with its own SHA-256, the page name, the *paper* size and its
    unit, and the W2D header (version, creator) — these are metadata, never measurements;
  * checks for a decoder; without one the result is `status: BLOCKED_NO_DECODER` with `measured: false`.

Nothing here is promoted to metres: paper millimetres are paper, and the model-to-paper transform is inside the
undecoded W2D stream. A BLOCKED result is never a PASS for any check that needs the drawing.

    python agent/dwf_legacy.py in.dwf out.json [--decode]
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ALGORITHM = "dwf_legacy/1"
MAX_MEMBERS = 2000
MAX_TOTAL_BYTES = 1_500_000_000
MAX_RATIO = 200                      # uncompressed / compressed per member (zip-bomb guard)
DECODERS = {
    "ezdwf": lambda: importlib.util.find_spec("ezdwf") is not None,
    "ODAFileConverter": lambda: shutil.which("ODAFileConverter") is not None,
    "dwftk": lambda: importlib.util.find_spec("dwftk") is not None or shutil.which("DWFToolkitConvert") is not None,
}


class ArchiveRejected(ValueError):
    pass


def check_archive(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = z.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ArchiveRejected(f"too many members: {len(infos)}")
    total = 0
    for i in infos:
        name = i.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise ArchiveRejected(f"unsafe member path: {i.filename}")
        total += i.file_size
        if i.compress_size and i.file_size / i.compress_size > MAX_RATIO and i.file_size > 10_000_000:
            raise ArchiveRejected(f"suspicious compression ratio: {i.filename}")
    if total > MAX_TOTAL_BYTES:
        raise ArchiveRejected(f"expands to {total} bytes")
    return infos


def available_decoders() -> list[str]:
    return [n for n, probe in DECODERS.items() if probe()]


def _open(src: Path) -> zipfile.ZipFile:
    data = src.read_bytes()
    head = data[:16]
    if head.startswith(b"(DWF V"):                 # DWF 6.x: a 12-byte "(DWF V06.xx)" prefix, then a ZIP
        import io
        return zipfile.ZipFile(io.BytesIO(data[data.index(b"PK"):]))
    return zipfile.ZipFile(src)


def inventory(src: Path) -> dict:
    src = Path(src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    out = {"algorithm": ALGORITHM, "file": src.name, "file_sha256": sha, "measured": False,
           "sections": [], "streams": [], "pages": []}
    with _open(src) as z:
        infos = check_archive(z)
        for i in infos:
            name = i.filename.replace("\\", "/")
            if name.endswith(".w2d"):
                b = z.read(i)
                hdr = b[:400].decode("latin-1", "replace")
                m = re.match(r"\(W2D V(\d+\.\d+)\)", hdr)
                cr = re.search(r"\(Creator '([^']*)'", hdr)
                out["streams"].append({"name": name, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                                       "w2d_version": m.group(1) if m else None,
                                       "creator": cr.group(1) if cr else None})
            elif name.endswith("descriptor.xml"):
                try:
                    root = ET.fromstring(z.read(i))
                except ET.ParseError:
                    continue
                for el in root.iter():
                    tag = el.tag.split("}")[-1]
                    if tag == "Page":
                        out["pages"].append({"section": name.split("/")[0], "object_id": el.get("objectId"),
                                             "name": el.get("name")})
                    elif tag == "Paper":
                        # paper size is plot metadata — explicitly not a building measurement
                        out["pages"] and out["pages"][-1].update(paper={"units": el.get("units"),
                                                                        "width": el.get("width"),
                                                                        "height": el.get("height"),
                                                                        "kind": "paper_metadata_not_measurement"})
            if "/" in name:
                sec = name.split("/")[0]
                if sec not in out["sections"]:
                    out["sections"].append(sec)
    return out


def process(src: Path, decode: bool = False) -> dict:
    out = inventory(src)
    decs = available_decoders()
    out["decoders_found"] = decs
    if not decode:
        out["status"] = "INVENTORY_ONLY"
    elif not decs:
        out["status"] = "BLOCKED_NO_DECODER"
        out["blocker"] = ("No licensed W2D decoder (Autodesk DWF Toolkit, ODA Drawings SDK or a validated ezdwf) is "
                          "installed; geometry, layers, clipping and model-to-paper transforms cannot be read. "
                          "Checks that need this drawing stay NOT_CHECKED.")
    else:
        # a decoder exists but has not been validated against reference drawings here: do not trust its numbers
        out["status"] = "BLOCKED_DECODER_UNVALIDATED"
        out["blocker"] = f"decoder {decs[0]} found but not validated / pinned on reference drawings"
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    res = process(Path(args[0]), decode="--decode" in sys.argv)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    (Path(args[1]).write_text(text, encoding="utf-8") if len(args) > 1 else print(text))
