"""Blind evaluation: run the licensing-route engine on a case's applicant-side inputs, write its result, and only then
compare it with the official decision (ground truth). The ground truth never reaches the engine.

Usage: python scripts/evaluate_blind.py validation/cases/<id> [--json]
Scores each official finding as DETECTED (engine confirmed it), FLAGGED (engine raised the topic but could not decide,
naming the missing inputs), or MISSED; engine-confirmed defects with no official counterpart are FALSE_POSITIVE.
Also checks the engine's rights reading against the committee's.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def run_engine(case: Path) -> dict:
    from app.rules import route as R
    facts = json.loads((case / "register_facts.json").read_text(encoding="utf-8"))
    gis = json.loads((case / "gis.json").read_text(encoding="utf-8")) if (case / "gis.json").exists() else None
    p = R.proposal_from_register(facts, gis)
    res = R.validate(p, ROOT / "knowledge" / "rights", ROOT / "knowledge" / "law" / "deviation_regulations_2002.yaml")
    out = res.as_dict() | {"summary_he": R.summary_he(res)}
    return out


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
    return {"findings": rows, "false_positives": fp,
            "counts": {k: sum(r["result"] == k for r in rows) for k in ("DETECTED", "FLAGGED", "MISSED")}}


def rights_check(truth: dict) -> dict:
    import yaml
    r = yaml.safe_load((ROOT / "knowledge/rights/tama39_residential_single.yaml").read_text(encoding="utf-8"))["rights"]
    off = truth.get("official_rights_reading") or {}
    return {k: {"engine": r.get(k), "official": v, "match": r.get(k) == v} for k, v in off.items() if k in r}


def main() -> None:
    case = Path(sys.argv[1]).resolve()
    engine = run_engine(case)                                   # 1. the independent result, written first
    out = ROOT / "validation" / "results"
    out.mkdir(exist_ok=True)
    (out / f"{case.name}.engine.json").write_text(json.dumps(engine, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    import yaml                                                 # 2. only now the official decision
    truth = yaml.safe_load((ROOT / "validation" / "ground_truth" / f"{case.name}.yaml").read_text(encoding="utf-8"))
    rep = {"application_id": case.name, "engine_verdict": engine["verdict"], "engine_confirmed": engine["confirmed"],
           "engine_summary_he": engine["summary_he"], "score": score(engine, truth), "rights_reading": rights_check(truth)}
    (out / f"{case.name}.score.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
