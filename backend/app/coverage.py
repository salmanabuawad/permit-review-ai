"""Required-check inventory and coverage per rule family (V9 §Output and orchestration).

The old coverage figure was "completed / applicable" over whatever rules happened to run — an empty rule set gave
0/0 and nothing stopped "no defects". Here coverage is measured against a fixed inventory of the checks a review
must complete (knowledge/coverage/required_checks.yaml). Each required check is:

  COMPLETED        a matching rule reached a final review status (PASS, CONFIRMED_DEFECT, DOCUMENTED_DISCREPANCY)
                   — for `independent` checks a PASS counts only when it rests on measured / document evidence
  OPEN             a matching rule ran but is UNRESOLVED / NOT_CHECKED (or an `independent` PASS from declared values)
  NOT_APPLICABLE   every matching rule is NOT_APPLICABLE
  FUTURE_STAGE     every matching rule belongs to a later licensing stage
  NOT_IMPLEMENTED  no rule in this case's rule set can satisfy it

A family is COMPLETE only when none of its checks is OPEN or NOT_IMPLEMENTED (and at least one completed).
`full_compliance_possible` is True only when every family is COMPLETE — the decision engine never returns
NO_DEFECTS_IDENTIFIED otherwise.
"""
from __future__ import annotations

from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path

import yaml

from .config import settings

FINAL = {"PASS", "CONFIRMED_DEFECT", "DOCUMENTED_DISCREPANCY"}
OPEN = {"UNRESOLVED", "NOT_CHECKED"}


def inventory_path() -> Path:
    return settings.knowledge_dir / "coverage" / "required_checks.yaml"


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_inventory(path: Path | None = None) -> dict:
    p = path or inventory_path()
    if not p.exists():
        return {"families": {}}
    return _load(str(p), p.stat().st_mtime)


def _status(r) -> str:
    return next((f[7:] for f in r.flags if f.startswith("STATUS_")), "NOT_CHECKED")


def _independent(r) -> bool:
    return ("RESOLVED_FROM_DOCUMENTS" in r.flags or "MEASURED" in r.flags
            or any(isinstance(e, dict) and e.get("type") == "measurement" for e in (r.evidence or [])))


def _check_state(check: dict, results: list) -> tuple[str, list[str]]:
    pats = check.get("rules") or []
    hits = [r for r in results if any(fnmatch(r.rule_id, p) for p in pats)]
    if not hits:
        return "NOT_IMPLEMENTED", []
    ids = [r.rule_id for r in hits]
    st = {r.rule_id: _status(r) for r in hits}
    done = [r for r in hits if st[r.rule_id] in FINAL
            and not (check.get("independent") and st[r.rule_id] == "PASS" and not _independent(r))]
    if done:
        # a completed rule never hides an open one of the same check
        if any(st[r.rule_id] in OPEN for r in hits):
            return "OPEN", ids
        return "COMPLETED", ids
    if all(st[i] == "NOT_APPLICABLE" for i in ids):
        return "NOT_APPLICABLE", ids
    if all(st[i] in ("FUTURE_STAGE", "NOT_APPLICABLE") for i in ids):
        return "FUTURE_STAGE", ids
    return "OPEN", ids


def family_coverage(results: list, inventory: dict | None = None) -> dict:
    """{families: {name: {state, completed, required, checks: [...]}}, full_compliance_possible, open: [...]}"""
    inv = inventory if inventory is not None else load_inventory()
    fams = inv.get("families") or {}
    out, open_checks = {}, []
    for name, fam in fams.items():
        checks = []
        for c in fam.get("checks") or []:
            state, rules = _check_state(c, results)
            checks.append({"id": c["id"], "label_he": c.get("label_he"), "state": state, "rules": rules,
                           "independent": bool(c.get("independent"))})
            if state in ("OPEN", "NOT_IMPLEMENTED"):
                open_checks.append(f"{name}.{c['id']}")
        required = [c for c in checks if c["state"] not in ("NOT_APPLICABLE", "FUTURE_STAGE")]
        completed = [c for c in required if c["state"] == "COMPLETED"]
        if not checks:
            state = "NO_CHECKS"
        elif required and len(completed) == len(required):
            state = "COMPLETE"
        elif not required:
            state = "NOT_APPLICABLE"
        elif completed:
            state = "PARTIAL"
        else:
            state = "NONE"
        out[name] = {"label_he": fam.get("label_he"), "state": state, "completed": len(completed),
                     "required": len(required), "checks": checks}
    full = bool(out) and all(f["state"] in ("COMPLETE", "NOT_APPLICABLE") for f in out.values()) \
        and any(f["state"] == "COMPLETE" for f in out.values())
    return {"inventory_version": inv.get("version"), "families": out,
            "full_compliance_possible": full, "open": open_checks}


def disclaimer_he(cov: dict) -> str:
    fams = cov.get("families") or {}
    if not fams:
        return "לא הוגדרה רשימת בדיקות נדרשות — אין לראות בדוח זה אישור התאמה."
    done = [f["label_he"] for f in fams.values() if f["state"] == "COMPLETE"]
    part = [f["label_he"] for f in fams.values() if f["state"] in ("PARTIAL", "NONE", "NO_CHECKS")]
    s = "הדוח מפרט ליקויים שאומתו בבדיקות שהושלמו בלבד ואינו אישור התאמה."
    if part:
        s += " תחומים שלא נבדקו במלואם: " + ", ".join(part) + "."
    return s
