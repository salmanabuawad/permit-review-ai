"""Permit Dependency Graph v1 (Permit360 phase 2): per-rule input fingerprints, reuse proof and revision reports.

* Each rule evaluation records the exact facts the engine read (a recording dict wraps the facts), the rule's own
  definition and a fingerprint of the run's post-processing context (input files, declarations, drawing values,
  register status). Fingerprint = hash of all three plus ENGINE_VERSION.
* Dependency completeness: the post-processing context is coarse — any change there counts as a change for every rule
  (the "broader recheck" fallback) until per-document dependencies are traced.
* Parity check on every run: a rule whose fingerprint equals the previous run's but whose result differs means a
  dependency was missed; it is recorded (`parity_violations`) and such a rule is never reused.
* Revision report: files added / changed / removed; findings new / corrected / unchanged / newly unresolved / newly
  applicable; and for each changed finding the exact inputs whose values changed.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CheckRun, PdgNode

ENGINE_VERSION = "engine-2026-11-26"
OPEN = ("FAIL",)
UNRESOLVED = ("UNCERTAIN",)


class Tracking(dict):
    """A dict that records every key path read through it (nested dicts are wrapped on access)."""

    def __init__(self, data: dict, log: dict, prefix: str = ""):
        super().__init__(data)
        self._log, self._prefix = log, prefix

    def _wrap(self, k, v):
        path = f"{self._prefix}{k}"
        if isinstance(v, dict):
            return Tracking(v, self._log, path + ".")
        self._log[path] = v
        return v

    def __getitem__(self, k):
        return self._wrap(k, super().__getitem__(k))

    def get(self, k, default=None):
        if k in self:
            return self[k]
        self._log[f"{self._prefix}{k}"] = None
        return default

    def __contains__(self, k):
        present = super().__contains__(k)
        if not present:
            self._log.setdefault(f"{self._prefix}{k}", None)
        return present


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def rule_inputs(rule, facts: dict, sources: dict, demo: bool) -> dict:
    """The facts one rule's evaluation reads, path → value."""
    from .rules.engine import evaluate_rule
    log: dict = {}
    try:
        evaluate_rule(rule, Tracking(facts, log), sources, demo)
    except Exception:  # noqa: BLE001 — the real run reports errors; here only the read set matters
        pass
    return {k: v for k, v in sorted(log.items())}


def context_fingerprint(input_hashes: list, declared: dict, drawing_values: dict | None, register_status) -> str:
    return _h({"files": sorted((x.get("file"), x.get("sha256")) for x in input_hashes or []), "declared": declared or {},
               "drawing": drawing_values or {}, "register": register_status})


def record(s: Session, run: CheckRun, rules: list, facts: dict, sources: dict, demo: bool, results: list, context: str) -> dict:
    """Write this run's rule-evaluation nodes; compare with the previous run. Returns the run's PDG summary."""
    by_id = {r.id: r for r in rules}
    prev = previous_nodes(s, run)
    reusable, changed, violations = 0, 0, []
    for res in results:
        rule = by_id.get(res.rule_id)
        if rule is None:                      # synthetic results (conflicts) have no single rule
            continue
        inputs = rule_inputs(rule, facts, sources, demo)
        fp = _h({"engine": ENGINE_VERSION, "rule": rule.raw, "inputs": inputs, "context": context})
        out = {"status": res.status, "measured": res.measured_value, "threshold": res.threshold}
        s.add(PdgNode(tenant_id=run.tenant_id, run_id=run.id, kind="rule_evaluation", key=res.rule_id, fingerprint=fp,
                      inputs={"facts": inputs, "rule_version": str(rule.raw.get("version")), "rule_hash": _h(rule.raw)[:16],
                              "context": context},
                      output=out))
        p = prev.get(res.rule_id)
        if p is not None and p.fingerprint == fp:
            if (p.output or {}).get("status") == res.status:
                reusable += 1
            else:
                violations.append(res.rule_id)
        else:
            changed += 1
    s.flush()
    return {"engine": ENGINE_VERSION, "nodes": reusable + changed + len(violations), "unchanged_inputs": reusable,
            "changed_inputs": changed, "parity_violations": violations,
            "note": "post-processing context is coarse: any document change counts as a change for every rule"}


def previous_run(s: Session, run: CheckRun) -> CheckRun | None:
    return s.scalars(select(CheckRun).where(CheckRun.case_id == run.case_id, CheckRun.version < run.version)
                     .order_by(CheckRun.version.desc())).first()


def previous_nodes(s: Session, run: CheckRun) -> dict:
    prev = previous_run(s, run)
    if prev is None:
        return {}
    return {n.key: n for n in s.scalars(select(PdgNode).where(PdgNode.run_id == prev.id, PdgNode.kind == "rule_evaluation"))}


def revision(s: Session, run: CheckRun) -> dict:
    """What changed between the previous run of the case and this one, and why."""
    prev = previous_run(s, run)
    if prev is None:
        return {"run": run.version, "previous": None}
    old_files = {x.get("file"): x.get("sha256") for x in prev.input_hashes or []}
    new_files = {x.get("file"): x.get("sha256") for x in run.input_hashes or []}
    files = {"added": sorted(set(new_files) - set(old_files)), "removed": sorted(set(old_files) - set(new_files)),
             "changed": sorted(f for f in set(new_files) & set(old_files) if new_files[f] != old_files[f]),
             "unchanged": len([f for f in set(new_files) & set(old_files) if new_files[f] == old_files[f]])}
    old = {f.rule_id: f for f in prev.findings}
    new = {f.rule_id: f for f in run.findings}
    nodes_old = {n.key: n for n in s.scalars(select(PdgNode).where(PdgNode.run_id == prev.id))}
    nodes_new = {n.key: n for n in s.scalars(select(PdgNode).where(PdgNode.run_id == run.id))}
    groups = {k: [] for k in ("new_defects", "corrected", "unchanged_defects", "newly_unresolved", "newly_applicable", "other_changes")}
    for rid in sorted(set(old) | set(new)):
        a, b = old.get(rid), new.get(rid)
        sa, sb = (a.status if a else None), (b.status if b else None)
        why = _why(nodes_old.get(rid), nodes_new.get(rid))
        item = {"rule_id": rid, "title_he": (b or a).title_he, "before": sa, "after": sb, "changed_inputs": why}
        if sb in OPEN and sa not in OPEN:
            groups["new_defects"].append(item)
        elif sa in OPEN and sb not in OPEN:
            groups["corrected"].append(item)
        elif sa in OPEN and sb in OPEN:
            groups["unchanged_defects"].append(item)
        elif sb in UNRESOLVED and sa not in UNRESOLVED:
            groups["newly_unresolved"].append(item)
        elif sa in ("NA", None) and sb not in ("NA", None):
            groups["newly_applicable"].append(item)
        elif sa != sb:
            groups["other_changes"].append(item)
    ruleset_changed = prev.ruleset_hash != run.ruleset_hash
    return {"run": run.version, "previous": prev.version, "files": files, "ruleset_changed": ruleset_changed,
            **groups, "counts": {k: len(v) for k, v in groups.items()}}


def _why(a: PdgNode | None, b: PdgNode | None) -> list[dict]:
    if a is None or b is None:
        return [{"input": "rule", "before": a is not None, "after": b is not None}]
    out = []
    fa, fb = (a.inputs or {}).get("facts") or {}, (b.inputs or {}).get("facts") or {}
    for k in sorted(set(fa) | set(fb)):
        if fa.get(k) != fb.get(k):
            out.append({"input": k, "before": fa.get(k), "after": fb.get(k)})
    if (a.inputs or {}).get("rule_version") != (b.inputs or {}).get("rule_version"):
        out.append({"input": "rule_version", "before": a.inputs.get("rule_version"), "after": b.inputs.get("rule_version")})
    if (a.inputs or {}).get("rule_hash") != (b.inputs or {}).get("rule_hash") and not any(x["input"] == "rule_version" for x in out):
        out.append({"input": "rule_definition", "before": "…", "after": "changed (e.g. professional approval)"})
    if (a.inputs or {}).get("context") != (b.inputs or {}).get("context") and not out:
        out.append({"input": "documents_or_declarations", "before": "…", "after": "changed"})
    return out[:20]
