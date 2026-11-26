"""Compare collected documents with the knowledge base: which are already registered sources (same SHA-256), which are
new, and which registered sources carry no hash. Nothing is overwritten or activated.

    python scripts/kb_compare.py <dir> [<dir> ...]
"""
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def registry() -> dict:
    out = {}
    for f in sorted((ROOT / "knowledge" / "sources.d").glob("*.yaml")):
        for s in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("sources", []):
            if s.get("sha256"):
                out[s["sha256"]] = s["id"]
    return out


def main(dirs):
    reg = registry()
    rows = []
    for d in dirs:
        for p in sorted(Path(d).rglob("*.pdf")):
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            rows.append({"file": p.name, "sha256": h[:16], "status": "DUPLICATE" if h in reg else "NEW",
                         "source_id": reg.get(h)})
    print(json.dumps({"documents": len(rows), "duplicate": sum(r["status"] == "DUPLICATE" for r in rows),
                      "new": [r["file"] for r in rows if r["status"] == "NEW"],
                      "registered": [f"{r['file']} = {r['source_id']}" for r in rows if r["source_id"]]},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
