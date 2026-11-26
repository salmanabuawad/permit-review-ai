"""Blind evaluation over a downloaded committee package of rejected applications (e.g. Hof Ashkelon).

    python scripts/evaluate_rejected.py run   <package_dir>   # engine on 01_BLIND_REVIEW only, results frozen
    python scripts/evaluate_rejected.py score <package_dir>   # only now: official reasons from the evaluation store

Isolation (same rules as evaluate_blind.py):
  * `run` reads only <package>/01_BLIND_REVIEW (the package's own blind_runtime.json is honoured). Every input file is
    hashed against the package's document_manifest.json; a missing or changed file stops the run.
  * Each document's text is scanned for decision vocabulary, committee letterhead and application numbers. A document
    that hits is excluded from the engine input and recorded (committee letters are not applicant submissions).
  * Results are written with their SHA-256 to <package>/../results/engine.json + frozen.json before any label is read.
  * `score` reads 02_RESTRICTED_VALIDATION from the evaluation store (BBP_EVAL_STORE/<package name>/), never from the
    package folder the engine saw, and refuses to run without an unchanged frozen result.
Personal data: results hold the neutral case ids, rule topics and counts only — no names, addresses or ID numbers.
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "agent")]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_blind import DECISION_WORDS, eval_store  # noqa: E402

COMMITTEE_LETTER = re.compile(r"הועדה המקומית לתכנון ולבניה|מנהלת? ועדה|הנחיות לפרסום|לכבוד\s|א\.ג\.נ")
APPLICATION_NO = re.compile(r"(?<!\d)(?:19|20)\d{6}(?!\d)")
# the committee register's application types → the route the applicant filed
ROUTE_BY_TYPE = [(re.compile(r"ללא הקלות"), "81"), (re.compile(r"כולל הקלות"), "82"), (re.compile(r"רישוי מקוצר"), "83")]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def doc_text(p: Path) -> str | None:
    """Text layer of a document, or None when it has none (image-only PDF, CAD, binary)."""
    suf = p.suffix.lower()
    try:
        if suf == ".docx":
            x = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8", "replace")
            return re.sub(r"<[^>]+>", " ", re.sub(r"</w:p>", "\n", x))
        if suf == ".pdf":
            import fitz
            with fitz.open(p) as d:
                t = "".join(pg.get_text() for pg in d)
            return t if t.strip() else None
    except (zipfile.BadZipFile, KeyError, RuntimeError, ValueError):
        return None
    return None


def screen(p: Path) -> tuple[bool, str]:
    """(usable as an applicant input, reason)."""
    t = doc_text(p)
    if t is None:
        return (False, "no text layer — not screened, not used") if p.suffix.lower() in (".pdf", ".docx") else \
               (False, f"{p.suffix.lower()} — no decoder / not screened")
    if DECISION_WORDS.search(t):
        return False, "decision vocabulary"
    if COMMITTEE_LETTER.search(t):
        return False, "committee letter, not an applicant submission"
    if APPLICATION_NO.search(t):
        return False, "contains an application number"
    return True, "screened"


def facts_from_metadata(m: dict) -> dict:
    code = next((c for rx, c in ROUTE_BY_TYPE if rx.search(m.get("application_type") or "")), None)
    land = [{"מספר גוש": x.get("block"), "מספר חלקה": x.get("parcel"), "מספר מגרש": x.get("lot"),
             "תוכנית קובעת מגרש": x.get("plan_defining_lot")} for x in m.get("land") or []]
    return {"application_id": m["case_id"], "submission_date": m["submission_date"], "application_type_code": code,
            "main_use": m.get("main_use"), "description": m.get("requested_construction_type"),
            "request_text": m.get("request_text") or "", "primary_area": m.get("primary_area") or "",
            "service_area": m.get("service_area") or "", "land": land}


def run_case(case: Path) -> dict:
    from app.rules import route as R
    import dwf_legacy
    m = json.loads((case / "application_metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads((case / "document_manifest.json").read_text(encoding="utf-8"))
    listed = {d["file"]: d for d in manifest}
    present = {str(p.relative_to(case)) for p in case.rglob("*") if p.is_file()} - {"application_metadata.json",
                                                                                     "document_manifest.json"}
    # nested archive members are extracted next to their container; they are listed under the container
    unlisted = {f for f in present - set(listed) if not f.startswith("extracted_archives/")}
    if unlisted:
        raise SystemExit(f"{case.name}: not in the document manifest: {sorted(unlisted)}")
    for f, d in listed.items():
        if not (case / f).exists() or sha(case / f) != d["sha256"]:
            raise SystemExit(f"{case.name}: input missing or changed since download: {f}")
    if DECISION_WORDS.search(m.get("request_text") or ""):     # the register text was edited after the decision
        return {"case": case.name, "excluded": "decision vocabulary in the request text (label leak)"}
    docs = []
    for f in sorted(present):
        p = case / f
        if p.suffix.lower() in (".dwf", ".dwfx"):
            inv = dwf_legacy.process(p)
            docs.append({"file": f, "category": f.split("/")[0], "used": False, "reason": inv.get("status")})
            continue
        ok, why = screen(p)
        docs.append({"file": f, "category": f.split("/")[0], "used": ok, "reason": why})
    facts = facts_from_metadata(m)
    p = R.proposal_from_register(facts)
    res = R.validate(p, ROOT / "knowledge" / "rights", ROOT / "knowledge" / "law" / "deviation_regulations_2002.yaml")
    out = res.as_dict()
    out.pop("application_id", None)
    return {"case": case.name, "route_filed": p.selected_route, "plans": p.plans, "verdict": res.verdict,
            "confirmed": res.confirmed, "checks": [{k: c[k] for k in ("topic", "status", "confirmable")} for c in out["checks"]],
            "notes": out.get("notes"), "summary_he": R.summary_he(res), "documents": docs,
            "drawings_available": any(d["category"] == "cad_originals" for d in docs),
            "documents_used": sum(d["used"] for d in docs)}


def results_dir(pkg: Path) -> Path:
    return pkg.parent / "results"


def cmd_run(pkg: Path) -> None:
    cfg = pkg / "04_DOWNLOAD_TOOLS" / "configuration" / "blind_runtime.json"
    if cfg.exists():
        allowed = json.loads(cfg.read_text(encoding="utf-8"))["allowed_read_paths"]
        assert "01_BLIND_REVIEW/" in allowed
    if (pkg / "02_RESTRICTED_VALIDATION").exists():
        raise SystemExit("the restricted validation set is next to the blind set — move it to the evaluation store first")
    cases = sorted((pkg / "01_BLIND_REVIEW").glob("CASE_*"))
    engine = {"package": pkg.name, "cases": [run_case(c) for c in cases]}
    body = json.dumps(engine, ensure_ascii=False, indent=1)
    out = results_dir(pkg)
    out.mkdir(exist_ok=True)
    (out / "engine.json").write_text(body, encoding="utf-8")
    (out / "frozen.json").write_text(json.dumps({"engine_sha256": hashlib.sha256(body.encode()).hexdigest(),
                                                 "cases": len(cases), "frozen_at": dt.datetime.now(dt.timezone.utc)
                                                 .isoformat(timespec="seconds")}), encoding="utf-8")
    c = collections.Counter(x.get("verdict", "EXCLUDED") for x in engine["cases"])
    print(json.dumps({"cases": len(cases), "verdicts": c, "frozen": str(out / "frozen.json")}, ensure_ascii=False))


def load_frozen(pkg: Path) -> dict:
    out = results_dir(pkg)
    meta = json.loads((out / "frozen.json").read_text(encoding="utf-8"))
    body = (out / "engine.json").read_bytes()
    if hashlib.sha256(body).hexdigest() != meta["engine_sha256"]:
        raise SystemExit("engine result changed after it was frozen")
    return json.loads(body)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("run", "score"):
        print(__doc__)
        sys.exit(2)
    pkg = Path(sys.argv[2]).resolve()
    if sys.argv[1] == "run":
        cmd_run(pkg)
    else:
        import evaluate_rejected_score
        evaluate_rejected_score.main(pkg, load_frozen(pkg))
