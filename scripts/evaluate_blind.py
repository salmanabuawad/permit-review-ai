"""Blind evaluation (V9 §Validation): run the engines on a case's curated applicant-side inputs, FREEZE the result, and
only then read the official decision from a physically separate evaluation store.

Isolation, in order:
  1. Input allowlist — validation/cases/<id>/allowlist.yaml lists every input file with its SHA-256 and role. A file
     in the case folder that is not listed, or whose hash differs, stops the run. Role labels alone prove nothing,
     so every input is also scanned for decision vocabulary (refusal, committee decision, protocol ...) and refused.
  2. Freeze — the engine result is written with its SHA-256 and time to validation/results/<id>.frozen.json.
  3. Reveal — the ground truth is read from the evaluation store (BBP_EVAL_STORE, default
     ~/.local/share/permit-review-eval, outside the repository and never on the app server). The score step
     refuses to run without a frozen result whose hash still matches.

Usage: python scripts/evaluate_blind.py validation/cases/<id>
       python scripts/evaluate_blind.py --summary          # sample size and counts over every frozen case
Development datasets (validation/dev_cases/*) are never scored here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
RESULTS = ROOT / "validation" / "results"
ALLOWED_EXTRA = {"README.md", "allowlist.yaml"}
DECISION_WORDS = re.compile(r"סירוב|לסרב|נדחת|נדחה|החלטת (?:ה)?ועדה|החלטות|פרוטוקול|חוות דעת מהנדס|"
                            r"refus|reject|decision|protocol", re.I)


def eval_store() -> Path:
    return Path(os.environ.get("BBP_EVAL_STORE") or Path.home() / ".local/share/permit-review-eval")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_inputs(case: Path) -> list[dict]:
    allow = yaml.safe_load((case / "allowlist.yaml").read_text(encoding="utf-8"))
    listed = {e["file"]: e for e in allow["inputs"]}
    present = {p.name for p in case.iterdir() if p.is_file()} - ALLOWED_EXTRA
    if present - set(listed):
        raise SystemExit(f"not on the input allowlist: {sorted(present - set(listed))}")
    for name, e in listed.items():
        p = case / name
        if not p.exists():
            raise SystemExit(f"allowlisted input missing: {name}")
        if sha(p) != e["sha256"]:
            raise SystemExit(f"input changed since it was curated: {name}")
        text = p.read_text(encoding="utf-8", errors="replace")
        # the curation note lists what was excluded — those key names are not content
        scan = re.sub(r'"excluded_from_blind"\s*:\s*\[[^\]]*\]', "", text)
        hit = DECISION_WORDS.search(scan)
        if hit:
            raise SystemExit(f"decision vocabulary in input {name}: {hit.group(0)!r}")
    return allow["inputs"]


def run_engine(case: Path) -> dict:
    from app.rules import route as R
    check_inputs(case)
    facts = json.loads((case / "register_facts.json").read_text(encoding="utf-8"))
    gis = json.loads((case / "gis.json").read_text(encoding="utf-8")) if (case / "gis.json").exists() else None
    p = R.proposal_from_register(facts, gis)
    res = R.validate(p, ROOT / "knowledge" / "rights", ROOT / "knowledge" / "law" / "deviation_regulations_2002.yaml")
    return res.as_dict() | {"summary_he": R.summary_he(res)}


def freeze(case_id: str, engine: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    body = json.dumps(engine, ensure_ascii=False, indent=2, default=str)
    (RESULTS / f"{case_id}.engine.json").write_text(body, encoding="utf-8")
    f = RESULTS / f"{case_id}.frozen.json"
    f.write_text(json.dumps({"case": case_id, "engine_sha256": hashlib.sha256(body.encode()).hexdigest(),
                             "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")
    return f


def load_frozen(case_id: str) -> dict:
    f, e = RESULTS / f"{case_id}.frozen.json", RESULTS / f"{case_id}.engine.json"
    if not f.exists() or not e.exists():
        raise SystemExit("no frozen engine result — run the engine before revealing the labels")
    meta = json.loads(f.read_text(encoding="utf-8"))
    if hashlib.sha256(e.read_bytes()).hexdigest() != meta["engine_sha256"]:
        raise SystemExit("engine result changed after it was frozen")
    return json.loads(e.read_text(encoding="utf-8"))


def load_truth(case_id: str) -> dict:
    p = eval_store() / "ground_truth" / f"{case_id}.yaml"
    if not p.exists():
        raise SystemExit(f"ground truth not in the evaluation store: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def score(engine: dict, truth: dict) -> dict:
    checks = {c["topic"]: c for c in engine["checks"]}
    rows = []
    for t in truth["findings"]:
        if "route" in t["engine_topics"]:
            hit = engine["verdict"] in ("WRONG_ROUTE", "PROHIBITED_DEVIATION")
            st = ("DETECTED" if hit and engine["confirmed"] else "FLAGGED" if hit or engine["verdict"] == "INSUFFICIENT_EVIDENCE"
                  else "MISSED")
            rows.append({"official": t["id"], "result": st, "engine": f"{engine['verdict']} (confirmed={engine['confirmed']})"})
            continue
        found = [checks[k] for k in t["engine_topics"] if k in checks]
        dev = [c for c in found if c["status"] in ("RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED")]
        open_ = [c for c in found if c["status"] in ("NOT_CHECKED", "POSSIBLE_DEVIATION")]
        st = ("DETECTED" if dev and all(c["confirmable"] for c in dev) else "FLAGGED" if dev or open_ else "MISSED")
        cls_ok = None if not dev or "classification" not in t else dev[0]["status"] == t["classification"]
        rows.append({"official": t["id"], "result": st, "classification_match": cls_ok,
                     "engine": "; ".join(f"{c['topic']}={c['status']}" for c in found) or "no check"})
    truth_topics = {k for t in truth["findings"] for k in t["engine_topics"]}
    fp = [c["topic"] for c in engine["checks"] if c["status"] in ("RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED")
          and c["confirmable"] and c["topic"] not in truth_topics]
    # a confirmed engine finding with no official counterpart is a false positive; an unconfirmed one is "unsupported"
    unsupported = [c["topic"] for c in engine["checks"] if c["status"] in ("RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED")
                   and not c["confirmable"] and c["topic"] not in truth_topics]
    return {"findings": rows, "false_positives": fp, "unsupported": unsupported,
            "counts": {k: sum(r["result"] == k for r in rows) for k in ("DETECTED", "FLAGGED", "MISSED")}}


def rights_check(truth: dict) -> dict:
    r = yaml.safe_load((ROOT / "knowledge/rights/tama39_residential_single.yaml").read_text(encoding="utf-8"))["rights"]
    off = truth.get("official_rights_reading") or {}
    return {k: {"engine": r.get(k), "official": v, "match": r.get(k) == v} for k, v in off.items() if k in r}


def summary() -> dict:
    cases = sorted(f.name.split(".")[0] for f in RESULTS.glob("*.score.json"))
    tot = {"DETECTED": 0, "FLAGGED": 0, "MISSED": 0, "false_positives": 0, "unsupported": 0}
    complete = 0
    for c in cases:
        sc = json.loads((RESULTS / f"{c}.score.json").read_text(encoding="utf-8"))
        for k in ("DETECTED", "FLAGGED", "MISSED"):
            tot[k] += sc["score"]["counts"][k]
        tot["false_positives"] += len(sc["score"]["false_positives"])
        tot["unsupported"] += len(sc["score"].get("unsupported", []))
        complete += bool(sc.get("complete_inputs"))
    off = tot["DETECTED"] + tot["FLAGGED"] + tot["MISSED"]
    return {"cases_scored": len(cases), "cases_with_complete_inputs": complete, "target": 30, **tot,
            "recall_confirmed": round(tot["DETECTED"] / off, 3) if off else None,
            "recall_flagged_or_confirmed": round((tot["DETECTED"] + tot["FLAGGED"]) / off, 3) if off else None,
            "precision_confirmed": (round(tot["DETECTED"] / (tot["DETECTED"] + tot["false_positives"]), 3)
                                    if tot["DETECTED"] + tot["false_positives"] else None)}


def main() -> None:
    if sys.argv[1] == "--summary":
        print(json.dumps(summary(), ensure_ascii=False, indent=2))
        return
    case = Path(sys.argv[1]).resolve()
    if case.parent.name == "dev_cases":
        raise SystemExit("development dataset: not part of the official evaluation")
    freeze(case.name, run_engine(case))                         # 1-2. independent result, frozen
    engine = load_frozen(case.name)
    truth = load_truth(case.name)                               # 3. only now the official decision
    allow = yaml.safe_load((case / "allowlist.yaml").read_text(encoding="utf-8"))
    rep = {"application_id": case.name, "engine_verdict": engine["verdict"], "engine_confirmed": engine["confirmed"],
           "engine_summary_he": engine["summary_he"], "complete_inputs": bool(allow.get("complete_inputs")),
           "missing_inputs": allow.get("missing_inputs", []),
           "score": score(engine, truth), "rights_reading": rights_check(truth)}
    (RESULTS / f"{case.name}.score.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
