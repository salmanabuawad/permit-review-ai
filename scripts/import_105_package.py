"""Import the Bnei Brak 105 knowledge package as unverified sources and rule candidates.

Non-destructive and idempotent: every file is keyed by its SHA-256, existing entries are never
rewritten, and running the import twice changes nothing. Nothing written here is loaded by the
rule engine — candidates stay in knowledge/rule_candidates with enforcement_enabled: false until a
reviewer verifies the wording, source, applicability, validity and plan hierarchy.

Usage:
    python scripts/import_105_package.py <package_dir> <scans_dir> [--dry-run]

package_dir  the extracted Bnei_Brak_105_Claude_Knowledge_Update.zip (catalog.json, ocr/, ...)
scans_dir    the extracted 105-20261122T172906Z-1-001.zip; every PDF is re-hashed against the catalog
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
SOURCES_FILE = KNOWLEDGE / "sources.d" / "bb_105.yaml"
OCR_DIR = KNOWLEDGE / "source_texts" / "bb_105" / "ocr"
CANDIDATES_FILE = KNOWLEDGE / "rule_candidates" / "bb_105.yaml"
ARCHIVE = "105-20261122T172906Z-1-001.zip"
PACKAGE = "Bnei_Brak_105_Claude_Knowledge_Update.zip"
PARENT_SOURCE = "MAVAT-BB-105"

# Reconciliation outcome per document (reports/105_reconciliation_report.md, 22.11.2026).
# plan_number is the register entry the document most likely belongs to; plan_number_verified stays
# false until a reviewer reads the plan number on the scan itself.
DOCS = {
    "14daa24d": ("בב/105/ד", "NEW_CONTENT_FOR_LISTED_PLAN", None),
    "1f433923": ("בב/105/ש", "NEW_CONTENT_FOR_LISTED_PLAN",
                 "Register (mavat) date 02/10/2008 vs Complot 08/01/2009 — validity vs publication not verified."),
    "23d33add": ("בב/105/צ", "NEW_CONTENT_FOR_LISTED_PLAN", "Plan number only partly legible in OCR."),
    "317148c2": ("בב/105/מצ/2", "POSSIBLE_OTHER_VERSION",
                 "OCR reads מצ/2; the register lists only בב/105/מצ/1 (27/03/2008). Verify on mavat."),
    "383bbdea": ("בב/105/ד/1", "NEW_CONTENT_FOR_LISTED_PLAN", None),
    "4c3f55a5": ("בב/105/ב", "NEW_CONTENT_FOR_LISTED_PLAN", None),
    "7eb80e34": ("בב/105/צ/1", "NEW_CONTENT_FOR_LISTED_PLAN", "Tasrit; pairs with 998367c7. Not georeferenced."),
    "998367c7": ("בב/105/צ/1", "NEW_CONTENT_FOR_LISTED_PLAN", "Instructions; source of candidates R001–R005."),
    "a2fafc1a": ("בב/105/ג/2", "NEW_CONTENT_FOR_LISTED_PLAN",
                 "OCR reads 'בב/05ג/ג/2'; matched to 105/ג/2 by subject (block/parcel applicability) only."),
    "b7d9ae74": ("בב/105/ג", "NEW_CONTENT_FOR_LISTED_PLAN", None),
    "bad26f4e": ("בב/105/ס/2", "NEW_CONTENT_FOR_LISTED_PLAN",
                 "OCR reads 'ס/2 או ט/2'. Register lists בב/105/ס as rejected (a different plan); "
                 "preceded by בב/מק/105/ס/1."),
    "ccff4a3e": (None, "NOT_IDENTIFIED", "Tasrit with no legible plan number."),
    "ec897540": ("בב/105/צ", "NEW_CONTENT_FOR_LISTED_PLAN", "Tasrit; pairs with 23d33add. Not georeferenced."),
    "fa425451": ("בב/105/ד/2", "NEW_CONTENT_FOR_LISTED_PLAN",
                 "Amended by בב/מק/105/ד/2/א (2004, setback distance); possibly superseded by 501-0873794 (2023) — "
                 "see docs/00 S5. Current legal status not verified."),
}
ARCHIVES = {
    "בב_ 105_ א_תשריט-7z.7z": ("בב/105/א", "Tasrit archive; not opened, no OCR, not georeferenced."),
    "בב_ 105_ ג_תשריט-7z.7z": ("בב/105/ג", "Tasrit archive; not opened, no OCR, not georeferenced."),
}
# Rule candidates: (match_type, related existing rule/source, note). None is enforced.
CANDIDATES = {
    "R001": ("NEW", None, None),
    "R002": ("NEW", None, None),
    "R003": ("NEW", None, None),
    "R004": ("RELATED", ["BB-B105-BUILDING-LINES"], "Existing rule is a value-less placeholder for housing."),
    "R005": ("RELATED", ["BB-B105-BUILDING-LINES"], "Existing rule is a value-less placeholder for housing."),
    "R006": ("RELATED", ["server rule_draft: guidelines doc 13 §16 (sukkah minimum 5 m²)"],
             "Minimum (new buildings) vs this maximum — not a direct conflict. Check against בב/מק/105/ס/1."),
    "R007": ("NEW", None, None),
    "R008": ("NEEDS_REVIEW", ["PLAN-501-0873794"], "105/ד/2 may be superseded by the 2023 roof plan (docs/00 S5)."),
    "R009": ("NEEDS_REVIEW", ["PLAN-501-0873794"], "105/ד/2 may be superseded by the 2023 roof plan (docs/00 S5)."),
    "R010": ("NEEDS_REVIEW", ["PLAN-501-0873794"], "105/ד/2 may be superseded by the 2023 roof plan (docs/00 S5)."),
    "R011": ("CONFLICT", ["BB-POL26-RR-SETBACK", "PLAN-501-0873794"],
             "1.2 m here vs 2.5 m from the facade in the 2026 policy (in addition to the roof-plan setback); "
             "בב/מק/105/ד/2/א changed the setback distance. Keep both sources; no automatic precedence."),
    "R012": ("NEEDS_REVIEW", ["PLAN-501-0873794"], "105/ד/2 may be superseded by the 2023 roof plan (docs/00 S5)."),
    "R013": ("NEEDS_REVIEW", ["PLAN-501-0873794"], "105/ד/2 may be superseded by the 2023 roof plan (docs/00 S5)."),
    "R014": ("RELATED", ["server rule_drafts: guidelines doc 6 §22.2, §32.1–32.2 (pergola)"],
             "Existing drafts limit beam width and covering, not area. Depends on 105/ד/2 validity."),
    "R015": ("RELATED", ["server rule_drafts: guidelines doc 6 §10.1, §10.2.2, §42.3.1 (housing basements)"],
             "Different scope (public buildings vs housing) and parameter."),
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_yaml(p: Path, key: str) -> list[dict]:
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get(key, []) if p.exists() else []


def dump_yaml(p: Path, header: str, key: str, items: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({key: items}, allow_unicode=True, sort_keys=False, width=120)
    p.write_text(header + body, encoding="utf-8", newline="\n")


def build(package: Path, scans: Path) -> tuple[list[dict], dict[str, str], list[dict]]:
    catalog = json.loads((package / "catalog.json").read_text(encoding="utf-8"))["files"]
    inventory = {Path(x["name"]).name: x for x in
                 json.loads((package / "source_archive_inventory.json").read_text(encoding="utf-8"))}
    raw = json.loads((package / "candidate_rules.json").read_text(encoding="utf-8"))
    rules = raw if isinstance(raw, list) else next(v for v in raw.values() if isinstance(v, list))
    scan_files = {p.name: p for p in scans.rglob("*") if p.is_file()}

    sources, ocr, by_file = [], {}, {}
    for d in catalog:
        key = d["file"][:8]
        if key not in DOCS:
            raise SystemExit(f"catalog file {d['file']} has no reconciliation entry — stop and review")
        actual = sha256(scan_files[d["file"]]) if d["file"] in scan_files else None
        if actual != d["sha256"]:
            raise SystemExit(f"{d['file']}: scan hash {actual} does not match catalog {d['sha256']}")
        plan, match, note = DOCS[key]
        pages = sorted((package / "ocr").glob(f"{d['file'][:-4]}_p*.txt"))
        for p in pages:
            ocr[p.name] = p.read_text(encoding="utf-8")
        sid = f"BB-105-DOC-{key.upper()}"
        by_file[d["file"]] = sid
        sources.append({
            "id": sid,
            "category": "STATUTORY_PLAN",
            "title_he": f"{plan or 'תכנית לא מזוהה'} — {d['subject']} ({d['document_type']})",
            "url": None,
            "verification": "OCR_UNVERIFIED",
            "plan_number": plan,
            "plan_number_ocr": d["plan_number_ocr"],
            "plan_number_verified": False,
            "document_type": d["document_type"],
            "pages": int(d["pages"]),
            "file_name": d["file"],
            "sha256": d["sha256"],
            "size_bytes": int(d["bytes"]),
            "provenance": {"archive": ARCHIVE, "package": PACKAGE, "received": "2026-11-22",
                           "official_url": None, "note": "Scans supplied by the client; official source URL not recorded."},
            "ocr_path": f"knowledge/source_texts/bb_105/ocr/{d['file'][:-4]}_p*.txt",
            "ocr_pages": len(pages),
            "related_source": PARENT_SOURCE,
            "reconciliation": match,
            "legal_status_verified": False,
            "geography_verified": False,
            "notes": note,
        })
    for name, (plan, note) in ARCHIVES.items():
        x = inventory[name]
        actual = sha256(scan_files[name]) if name in scan_files else None
        if actual != x["sha256"]:
            raise SystemExit(f"{name}: scan hash {actual} does not match inventory {x['sha256']}")
        sources.append({
            "id": f"BB-105-ARCH-{x['sha256'][:8].upper()}",
            "category": "STATUTORY_PLAN",
            "title_he": f"{plan} — ארכיון תשריט (7z)",
            "url": None,
            "verification": "FOUND_NOT_READ",
            "plan_number": plan,
            "plan_number_verified": False,
            "document_type": "תשריט (ארכיון)",
            "file_name": name,
            "sha256": x["sha256"],
            "size_bytes": int(x["size"]),
            "provenance": {"archive": ARCHIVE, "received": "2026-11-22", "official_url": None},
            "related_source": PARENT_SOURCE,
            "reconciliation": "NOT_COMPARABLE",
            "legal_status_verified": False,
            "geography_verified": False,
            "notes": note,
        })

    candidates = []
    for r in rules:
        match, related, note = CANDIDATES[r["rule_id"]]
        candidates.append({
            "id": f"BB-105-CAND-{r['rule_id']}",
            "enforcement_enabled": False,
            "verification_status": r["verification_status"],
            "legal_effect": r["legal_effect"],
            "status": "NEEDS_REVIEW" if match in ("CONFLICT", "NEEDS_REVIEW") else "CANDIDATE",
            "reconciliation": match,
            "plan_number_candidate": r["plan_number_candidate"],
            "scope": r["scope"],
            "parameter": r["parameter"],
            "candidate_value": float(r["candidate_value"]) if "." in str(r["candidate_value"]) else int(r["candidate_value"]),
            "unit": r["unit"],
            "source": {"source_id": by_file[r["source_pdf"]], "page": int(r["page"]),
                       "ocr_evidence_he": r["ocr_evidence_excerpt"]},
            "related_existing": related,
            "review_notes_he": r["review_notes"],
            "notes": note,
        })
    return sources, ocr, candidates


def pending(sources: list[dict], ocr: dict[str, str], candidates: list[dict]):
    """What an import would add. Sources are keyed by sha256, OCR pages by file name, candidates by id;
    anything already stored is left as it is (an OCR page whose text differs is reported, not replaced)."""
    have_src = {s["sha256"] for s in load_yaml(SOURCES_FILE, "sources")}
    have_cand = {c["id"] for c in load_yaml(CANDIDATES_FILE, "candidates")}
    new_src = [s for s in sources if s["sha256"] not in have_src]
    new_ocr = {n: t for n, t in ocr.items() if not (OCR_DIR / n).exists()}
    changed_ocr = [n for n, t in ocr.items() if (OCR_DIR / n).exists() and (OCR_DIR / n).read_text(encoding="utf-8") != t]
    new_cand = [c for c in candidates if c["id"] not in have_cand]
    return new_src, new_ocr, changed_ocr, new_cand


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package_dir", type=Path)
    ap.add_argument("scans_dir", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sources, ocr, candidates = build(a.package_dir, a.scans_dir)
    new_src, new_ocr, changed_ocr, new_cand = pending(sources, ocr, candidates)

    print(f"sources:    {len(new_src)} new, {len(sources) - len(new_src)} already present  -> {SOURCES_FILE.relative_to(ROOT)}")
    print(f"ocr pages:  {len(new_ocr)} new, {len(ocr) - len(new_ocr)} already present  -> {OCR_DIR.relative_to(ROOT)}")
    print(f"candidates: {len(new_cand)} new, {len(candidates) - len(new_cand)} already present  -> "
          f"{CANDIDATES_FILE.relative_to(ROOT)} (enforcement_enabled: false)")
    if changed_ocr:
        print(f"WARNING: {len(changed_ocr)} OCR pages differ from the stored text and were left unchanged: {changed_ocr}")
    for s in new_src:
        print(f"  + {s['id']}  {s['plan_number'] or '—'}  {s['reconciliation']}")
    for c in new_cand:
        print(f"  + {c['id']}  {c['parameter']}={c['candidate_value']} {c['unit']}  {c['status']}/{c['reconciliation']}")
    if a.dry_run:
        print("dry run — nothing written")
        return 0
    if not (new_src or new_ocr or new_cand):
        print("nothing to write — already imported")
        return 0
    if new_src:
        dump_yaml(SOURCES_FILE,
                  "# Bnei Brak 105 plan documents — generated by scripts/import_105_package.py. Do not edit by hand;\n"
                  "# entries are keyed by sha256 and never rewritten. OCR text is unverified (verification: OCR_UNVERIFIED).\n",
                  "sources", load_yaml(SOURCES_FILE, "sources") + new_src)
    for n, t in new_ocr.items():
        OCR_DIR.mkdir(parents=True, exist_ok=True)
        (OCR_DIR / n).write_text(t, encoding="utf-8", newline="\n")
    if new_cand:
        dump_yaml(CANDIDATES_FILE,
                  "# Rule candidates from the Bnei Brak 105 package — NOT rules. The rule engine never loads this\n"
                  "# directory. A candidate becomes a rule only after a reviewer verifies wording, source,\n"
                  "# applicability, validity and plan hierarchy, and it is then written to knowledge/rules by hand.\n",
                  "candidates", load_yaml(CANDIDATES_FILE, "candidates") + new_cand)
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
