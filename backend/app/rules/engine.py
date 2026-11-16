"""Deterministic rule engine.

Principles (enforced here, covered by tests/test_rules_engine.py):
  * Applicability first. Out of scope -> NA. Unknown applicability fact -> UNCERTAIN.
  * Missing operand / missing threshold in source -> UNCERTAIN (INCOMPLETE), never FAIL.
  * Measurement uncertainty is respected: a value whose uncertainty band straddles the
    threshold -> UNCERTAIN.
  * A rule that is not professionally approved can never produce a binding FAIL: the
    computed FAIL is kept in `computed_result`, but `status` becomes UNCERTAIN with flag
    RULE_NOT_APPROVED. (Demo-fixture rules are binding only inside a demo tenant.)
  * Qualitative guidance is never turned into an arbitrary number -> REVIEW_REQUIRED.
  * Two applicable rules on the same operand with different thresholds -> CONFLICT
    finding for a human decision; no automatic precedence.
  * Every result is advisory. Statutory decisions are made by an authorised person.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EPS = 1e-6     # numeric noise only (1 µm / 1 µm²); NOT a legal tolerance

BINDING_REVIEW_STATES = {"PROFESSIONALLY_APPROVED"}
REVIEW_STATES = ["DRAFT", "SOURCE_MISSING", "SOURCE_LOCATED", "SOURCE_VERIFIED",
                 "PROFESSIONALLY_APPROVED", "DESIGN_ASSUMPTION", "DEMO_FIXTURE", "RETIRED"]
LEGAL_LEVEL_RANK = {   # for display/ordering only — never used to auto-resolve conflicts
    "STATUTE": 1, "REGULATION": 2, "STATUTORY_PLAN": 3, "SPATIAL_GUIDELINES": 4,
    "MUNICIPAL_POLICY": 5, "COMMITTEE_DECISION": 6, "CASE_INFO": 7, "INTERNAL_QA": 8, "DEMO": 9,
}

UNKNOWN = object()


@dataclass
class Rule:
    raw: dict

    def __getattr__(self, k):  # convenient read access
        try:
            return self.raw[k]
        except KeyError as e:
            raise AttributeError(k) from e

    @property
    def check(self) -> dict:
        return self.raw["check"]


@dataclass
class Result:
    rule_id: str
    rule_version: str
    report: str
    computed_result: str
    status: str
    severity: str
    title_he: str
    explanation_he: str
    fix_hint_he: str | None = None
    measured_value: float | None = None
    measured_uncertainty: float | None = None
    threshold: float | None = None
    operator: str | None = None
    units: str | None = None
    confidence: float = 1.0
    citations: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    overlay_wkt: str | None = None
    flags: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


# ------------------------------------------------------------------ loading

def load_rules(paths: list[Path]) -> list[Rule]:
    rules = []
    for p in paths:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for r in data.get("rules", []):
            rules.append(Rule(r))
    ids = [r.id for r in rules]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"duplicate rule ids: {sorted(dup)}")
    return rules


def ruleset_hash(rules: list[Rule]) -> str:
    blob = json.dumps([r.raw for r in rules], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ facts

def get_fact(facts: dict, path: str):
    cur: Any = facts
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return UNKNOWN
    if cur is None:
        return UNKNOWN
    return cur


def _cond(facts: dict, c: dict) -> bool | object:
    v = get_fact(facts, c["fact"])
    op = c.get("op", "eq")
    if op is True or op is False:      # YAML 1.1 parses bare true/false as booleans
        op = "true" if op else "false"
    if op == "exists":
        return v is not UNKNOWN
    if v is UNKNOWN:
        return UNKNOWN
    target = c.get("value")
    if op == "eq":
        return v == target
    if op == "ne":
        return v != target
    if op == "in":
        return v in target
    if op == "not_in":
        return v not in target
    if op == "true":
        return bool(v) is True
    if op == "false":
        return bool(v) is False
    if op == "contains":
        return target in v
    raise ValueError(f"unknown op {op}")


def applicability(rule: Rule, facts: dict) -> tuple[str, list[str]]:
    """Return ('APPLIES'|'NA'|'UNKNOWN', reasons)."""
    reasons = []
    case = facts.get("case", {})
    pts = rule.raw.get("permit_types")
    if pts and case.get("permit_type") not in pts:
        return "NA", [f"סוג הבקשה ({case.get('permit_type')}) אינו בתחולת הכלל"]
    stages = rule.raw.get("stages")
    if stages and case.get("stage") not in stages:
        return "NA", [f"שלב ({case.get('stage')}) אינו בתחולת הכלל"]
    ref_date = case.get("reference_date")
    if ref_date:
        d = dt.date.fromisoformat(ref_date)
        vf, vt = rule.raw.get("valid_from"), rule.raw.get("valid_to")
        if vf and d < dt.date.fromisoformat(str(vf)):
            return "NA", [f"הכלל בתוקף מ־{vf}; מועד הקובע לתיק {ref_date}"]
        if vt and d > dt.date.fromisoformat(str(vt)):
            return "NA", [f"תוקף הכלל הסתיים ב־{vt}"]
    scope = rule.raw.get("spatial_scope") or {}
    if scope.get("plans"):
        plans = case.get("applicable_plans") or []
        if not plans:
            return "UNKNOWN", ["לא הוזנו תכניות חלות על המגרש — לא ניתן לקבוע תחולה מרחבית"]
        if not set(scope["plans"]) & set(plans):
            return "NA", ["התכנית שבתחולת הכלל אינה חלה על המגרש לפי הנתונים בתיק"]
    unknown = []
    for group, mode in (("all", all), ("any", any)):
        conds = (rule.raw.get("applicability") or {}).get(group)
        if not conds:
            continue
        vals = [_cond(facts, c) for c in conds]
        if any(v is UNKNOWN for v in vals):
            known = [v for v in vals if v is not UNKNOWN]
            if group == "all" and any(v is False for v in known):
                return "NA", ["אחד מתנאי התחולה אינו מתקיים"]
            if group == "any" and any(v is True for v in known):
                continue
            unknown += [c.get("label_he", c["fact"]) for c, v in zip(conds, vals) if v is UNKNOWN]
            continue
        if not mode(vals):
            failing = [c for c, v in zip(conds, vals) if v is False] or conds
            return "NA", [failing[0].get("label_he", failing[0]["fact"]) + " — לא מתקיים"]
    if unknown:
        return "UNKNOWN", [f"חסר נתון לקביעת תחולה: {u}" for u in unknown]
    return "APPLIES", reasons


# ------------------------------------------------------------------ comparison

def compare(value: float, unc: float, op: str, t: float) -> str:
    lo, hi = value - unc, value + unc
    if op == ">=":
        return "PASS" if lo >= t - EPS else ("FAIL" if hi < t - EPS else "UNCERTAIN")
    if op == ">":
        return "PASS" if lo > t + EPS else ("FAIL" if hi <= t + EPS else "UNCERTAIN")
    if op == "<=":
        return "PASS" if hi <= t + EPS else ("FAIL" if lo > t + EPS else "UNCERTAIN")
    if op == "<":
        return "PASS" if hi < t - EPS else ("FAIL" if lo >= t - EPS else "UNCERTAIN")
    if op == "==":
        return "PASS" if (abs(value - t) + unc) <= EPS else ("FAIL" if abs(value - t) - unc > EPS else "UNCERTAIN")
    raise ValueError(op)


OP_HE = {">=": "≥", ">": ">", "<=": "≤", "<": "<", "==": "="}


def _threshold(rule: Rule, facts: dict) -> tuple[float | None, str | None]:
    chk = rule.check
    if "threshold_by" in chk:
        tb = chk["threshold_by"]
        key = get_fact(facts, tb["fact"])
        if key is UNKNOWN:
            return None, f"חסר נתון ({tb.get('label_he', tb['fact'])}) לקביעת ערך הסף"
        val = (tb.get("map") or {}).get(key)
        if val is None:
            return None, f"אין ערך סף מאומת עבור '{key}'"
        return float(val), None
    t = chk.get("threshold")
    if t is None:
        return None, chk.get("threshold_missing_he") or "ערך הסף אינו מופיע במקור שאומת — נדרש מסמך תכנית/תקנון"
    return float(t), None


def _operand(facts: dict, ref: str) -> tuple[Any, float, dict | None]:
    """operand refs: 'measure.<key>' (Measurement dict) | 'declared.<k>' | any fact path."""
    v = get_fact(facts, ref)
    if isinstance(v, dict) and "value" in v:       # a Measurement
        if v.get("value") is None:
            return UNKNOWN, 0.0, v
        return float(v["value"]), float(v.get("uncertainty") or 0.0), v
    if v is UNKNOWN:
        return UNKNOWN, 0.0, None
    return v, 0.0, None


# ------------------------------------------------------------------ evaluation

def _citations(rule: Rule, sources: dict) -> list[dict]:
    out = []
    for c in rule.raw.get("sources", []):
        src = sources.get(c.get("source_id"), {})
        out.append({
            "source_id": c.get("source_id"), "title_he": src.get("title_he", c.get("source_id")),
            "url": src.get("url"), "edition": src.get("edition"),
            "page": c.get("page"), "section": c.get("section"),
            "verification": src.get("verification", "UNKNOWN"),
            "quote_he": c.get("quote_he"),
        })
    return out


def evaluate_rule(rule: Rule, facts: dict, sources: dict, tenant_is_demo: bool) -> Result:
    chk = rule.check
    kind = chk["kind"]
    base = dict(rule_id=rule.id, rule_version=str(rule.raw.get("version", "0")),
                report=rule.raw.get("report", "reviewer"), severity=rule.raw.get("severity", "medium"),
                title_he=rule.title_he, fix_hint_he=rule.raw.get("fix_hint_he"),
                citations=_citations(rule, sources), units=chk.get("units"), operator=chk.get("operator"))
    flags: list[str] = []
    state = rule.raw.get("review_state", "DRAFT")
    if state == "DEMO_FIXTURE":
        flags.append("DEMO_RULE")
        if not tenant_is_demo:
            return Result(**base, computed_result="NA", status="NA", flags=flags,
                          explanation_he="כלל הדגמה — אינו מופעל על תיק אמיתי")
    if state not in BINDING_REVIEW_STATES and state != "DEMO_FIXTURE" and rule.raw.get("legal_level") != "INTERNAL_QA":
        flags.append("RULE_NOT_APPROVED")

    app, reasons = applicability(rule, facts)
    if app == "NA":
        return Result(**base, computed_result="NA", status="NA", flags=flags,
                      explanation_he="לא חל: " + "; ".join(reasons))
    if app == "UNKNOWN":
        return Result(**base, computed_result="UNCERTAIN", status="UNCERTAIN", flags=flags + ["APPLICABILITY_UNKNOWN"],
                      explanation_he="; ".join(reasons), confidence=0.0)

    computed, expl, extra = "UNCERTAIN", "", {}
    if kind == "compare":
        val, unc, meas = _operand(facts, chk["operand"])
        t, t_err = _threshold(rule, facts)
        extra.update(threshold=t)
        if meas:
            extra.update(evidence=[{"type": "measurement", **{k: meas.get(k) for k in
                                    ("key", "method", "source_entities", "units", "uncertainty")}}],
                         overlay_wkt=meas.get("overlay_wkt"))
        if val is UNKNOWN:
            computed = "UNCERTAIN"
            flags.append("INCOMPLETE")
            expl = (meas or {}).get("note_he") or f"חסר נתון למדידה ({chk.get('operand_label_he', chk['operand'])})"
        elif t is None:
            computed = "UNCERTAIN"
            flags.append("THRESHOLD_SOURCE_MISSING")
            extra.update(measured_value=val, measured_uncertainty=unc)
            verb = "נתון בתיק" if chk["operand"].startswith(("declared.", "facts_derived.")) else "נמדד"
            expl = f"{verb}: {val:.2f} {chk.get('units','')}; {t_err}"
        else:
            computed = compare(val, unc, chk["operator"], t)
            extra.update(measured_value=val, measured_uncertainty=unc)
            band = f" (±{unc:.2f})" if unc else ""
            verb = "נתון בתיק" if chk["operand"].startswith(("declared.", "facts_derived.")) else "נמדד"
            expl = (f"{verb}: {val:.2f}{band} {chk.get('units','')}; נדרש {OP_HE[chk['operator']]} {t:.2f} "
                    f"{chk.get('units','')}. שיטה: {chk.get('geometry_method_he', '—')}")
            if computed == "UNCERTAIN":
                flags.append("WITHIN_UNCERTAINTY_BAND")
    elif kind == "doc_required":
        present = get_fact(facts, f"docs.present.{chk['doc_type']}")
        computed = "PASS" if present is True else "FAIL"
        expl = ("המסמך הוגש" if computed == "PASS" else f"לא נמצא מסמך מסוג: {chk.get('doc_label_he', chk['doc_type'])}")
    elif kind == "cad_roles":
        found = get_fact(facts, "cad.roles")
        if found is UNKNOWN:
            computed, expl = "FAIL", "לא הוגש קובץ CAD (DXF/DWG) מנותח"
        else:
            required = chk.get("roles") or get_fact(facts, "cad.required_roles")
            required = [] if required is UNKNOWN else required
            missing = [r for r in required if r not in found]
            computed = "PASS" if not missing else "FAIL"
            expl = "כל השכבות הנדרשות נמצאו" if not missing else "שכבות חסרות: " + ", ".join(missing)
    elif kind == "declared_bool":
        v = get_fact(facts, chk["fact"])
        if v is UNKNOWN:
            computed, expl = "UNCERTAIN", f"לא הוצהר/לא סומן בתיק: {chk.get('fact_label_he', chk['fact'])}"
            flags.append("INCOMPLETE")
        else:
            ok = bool(v) == bool(chk.get("expected", True))
            computed = "PASS" if ok else "FAIL"
            expl = f"{chk.get('fact_label_he', chk['fact'])}: {'כן' if v else 'לא'}"
    elif kind == "consistency":
        a, ua, ma = _operand(facts, chk["operand_a"])
        b, _, _ = _operand(facts, chk["operand_b"])
        if a is UNKNOWN or b is UNKNOWN:
            computed, expl = "UNCERTAIN", "חסר אחד הנתונים להשוואה (שרטוט/טבלת שטחים)"
            flags.append("INCOMPLETE")
        else:
            rel = abs(a - b) / max(abs(b), EPS)
            computed = "PASS" if rel <= chk["max_rel_diff"] + EPS else "FAIL"
            extra.update(measured_value=round(rel * 100, 3), threshold=chk["max_rel_diff"] * 100,
                         operator="<=", units="%")
            if ma:
                extra.update(overlay_wkt=ma.get("overlay_wkt"))
            expl = (f"{chk.get('a_label_he','A')}: {a:.2f} מ\"ר; {chk.get('b_label_he','B')}: {b:.2f} מ\"ר; "
                    f"הפרש {rel*100:.2f}% (סף {chk['max_rel_diff']*100:.1f}%)")
    elif kind == "qualitative":
        computed = "UNCERTAIN"
        flags.append("REVIEW_REQUIRED")
        expl = "הנחיה איכותנית — נדרשת הכרעת בודק מקצועי. המערכת אינה ממירה אותה למדידה כמותית."
    elif kind == "condition":
        computed = "UNCERTAIN"
        flags.append("CONDITION_FOR_PERMIT")
        expl = rule.raw.get("condition_he", "תנאי למתן היתר — יש לוודא קיומו לפני הוצאת ההיתר")
    else:
        raise ValueError(f"unknown check kind {kind}")

    status = computed
    if computed == "FAIL" and "RULE_NOT_APPROVED" in flags:
        status = "UNCERTAIN"
        expl += " | הכלל טרם אושר ע\"י בודק מוסמך — אי-התאמה פוטנציאלית בלבד, ללא פסילה אוטומטית."
    conf = 1.0 if status in ("PASS", "FAIL", "NA") else 0.5
    return Result(**{**base, **{k: v for k, v in extra.items() if k in ("threshold", "operator", "units")}},
                  computed_result=computed, status=status, explanation_he=expl, flags=flags, confidence=conf,
                  **{k: v for k, v in extra.items() if k not in ("threshold", "operator", "units")})


def detect_conflicts(rules: list[Rule], results: list[Result], facts: dict) -> list[Result]:
    by_operand: dict[str, list[tuple[Rule, Result]]] = {}
    for r, res in zip(rules, results):
        if r.check["kind"] == "compare" and res.status != "NA" and res.threshold is not None:
            by_operand.setdefault(r.check["operand"], []).append((r, res))
    out = []
    for operand, items in by_operand.items():
        variants = {(res.operator, res.threshold) for _, res in items}
        if len(variants) > 1:
            cites = [c for _, res in items for c in res.citations]
            desc = "; ".join(f"{r.id}: {OP_HE.get(res.operator, res.operator)} {res.threshold}" for r, res in items)
            out.append(Result(rule_id=f"CONFLICT:{operand}", rule_version="-", report="reviewer",
                              computed_result="UNCERTAIN", status="UNCERTAIN", severity="high",
                              title_he="סתירה בין מקורות — נדרשת הכרעה אנושית",
                              explanation_he=f"כללים חלים עם ספים שונים לאותו נתון: {desc}. "
                                             "המערכת אינה מכריעה אוטומטית בין מקורות.",
                              citations=cites, flags=["SOURCE_CONFLICT", "REVIEW_REQUIRED"], confidence=0.0))
    return out


def evaluate(rules: list[Rule], facts: dict, sources: dict, tenant_is_demo: bool = False) -> list[Result]:
    active = [r for r in rules if r.raw.get("review_state") != "RETIRED"]
    results = [evaluate_rule(r, facts, sources, tenant_is_demo) for r in active]
    return results + detect_conflicts(active, results, facts)
