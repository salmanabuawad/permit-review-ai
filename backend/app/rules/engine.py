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
            "quote_he": c.get("quote_he"), "jurisdiction": src.get("jurisdiction"),
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
    elif kind == "any_present":
        roles = get_fact(facts, "cad.roles")
        roles = [] if roles is UNKNOWN else roles
        found, wanted = [], []
        for item in chk["items"]:
            label = item.get("label_he", item.get("doc_type") or item.get("cad_role"))
            wanted.append(label)
            if ("doc_type" in item and get_fact(facts, f"docs.present.{item['doc_type']}") is True) or                     ("cad_role" in item and item["cad_role"] in roles):
                found.append(label)
        computed = "PASS" if found else "FAIL"
        expl = ("נמצא: " + ", ".join(found)) if found else ("לא נמצא אף אחד מאלה: " + " / ".join(wanted))
    elif kind == "declared_bool":
        v = get_fact(facts, chk["fact"])
        if v is UNKNOWN:
            computed, expl = "UNCERTAIN", f"לא הוצהר/לא סומן בתיק: {chk.get('fact_label_he', chk['fact'])}"
            flags.append("INCOMPLETE")
        else:
            ok = bool(v) == bool(chk.get("expected", True))
            computed = "PASS" if ok else "FAIL"
            expl = f"{chk.get('fact_label_he', chk['fact'])}: {'כן' if v else 'לא'}"
    elif kind == "list_empty":
        items = get_fact(facts, chk["fact"])
        if items is UNKNOWN:
            computed, expl = "UNCERTAIN", f"לא ניתן לבדוק: {chk.get('fact_label_he', chk['fact'])}"
            flags.append("INCOMPLETE")
        elif not items:
            computed, expl = "PASS", chk.get("pass_he", "לא נמצאו פריטים")
        else:
            shown = "; ".join(str(i) for i in items[:10]) + (f" (ועוד {len(items) - 10})" if len(items) > 10 else "")
            computed = "FAIL"
            expl = f"{chk.get('items_label_he', 'נמצאו')} ({len(items)}): {shown}"
            extra.update(measured_value=len(items))
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


# ------------------------------------------------------------------ validation (rules authored in the UI)

REPORTS = ("reviewer", "rights", "completeness")
SEVERITIES = ("high", "medium", "low")
OPERATORS = tuple(OP_HE)
CONDITION_OPS = ("eq", "ne", "in", "not_in", "true", "false", "contains", "exists")
CHECK_FIELDS = {          # required fields per check kind (see evaluate_rule)
    "compare": ("operand", "operator"),
    "doc_required": ("doc_type",),
    "cad_roles": (),
    "any_present": ("items",),
    "declared_bool": ("fact",),
    "list_empty": ("fact",),
    "consistency": ("operand_a", "operand_b", "max_rel_diff"),
    "qualitative": (),
    "condition": (),
}
AUTHOR_REVIEW_STATES = ("DRAFT", "SOURCE_MISSING", "SOURCE_LOCATED", "SOURCE_VERIFIED", "DESIGN_ASSUMPTION", "RETIRED")
_RULE_ID = __import__("re").compile(r"^[A-Z0-9][A-Z0-9_-]{2,79}$")


def validate_rule(raw: dict, allow_demo: bool = False) -> list[str]:
    """Problems that would make a rule unusable or misleading; empty = valid. Ends with a dry run of the
    engine on empty facts, so a rule that passes here cannot crash a check run."""
    errs: list[str] = []
    if not _RULE_ID.match(str(raw.get("id") or "")):
        errs.append("מזהה כלל: אותיות לטיניות גדולות, ספרות, '-' או '_' (3–80 תווים)")
    if not str(raw.get("title_he") or "").strip():
        errs.append("חסרה כותרת")
    if raw.get("legal_level") not in LEGAL_LEVEL_RANK:
        errs.append("רמה משפטית לא מוכרת")
    if raw.get("report", "reviewer") not in REPORTS:
        errs.append("דוח לא מוכר")
    if raw.get("severity", "medium") not in SEVERITIES:
        errs.append("חומרה לא מוכרת")
    states = AUTHOR_REVIEW_STATES + (("DEMO_FIXTURE",) if allow_demo else ())
    if raw.get("review_state", "DRAFT") not in states:
        errs.append("מצב אימות לא מותר בעריכה (אישור מקצועי ניתן רק דרך 'אישור מקצועי')")
    for k in ("valid_from", "valid_to"):
        if raw.get(k):
            try:
                dt.date.fromisoformat(str(raw[k]))
            except ValueError:
                errs.append(f"{k}: תאריך בפורמט YYYY-MM-DD")
    for k in ("permit_types", "stages"):
        if raw.get(k) is not None and not (isinstance(raw[k], list) and all(isinstance(x, str) for x in raw[k])):
            errs.append(f"{k}: רשימת מחרוזות")
    chk = raw.get("check")
    if not isinstance(chk, dict) or chk.get("kind") not in CHECK_FIELDS:
        errs.append("סוג בדיקה לא מוכר")
    else:
        missing = [f for f in CHECK_FIELDS[chk["kind"]] if chk.get(f) in (None, "", [])]
        if missing:
            errs.append("חסרים שדות בבדיקה: " + ", ".join(missing))
        if chk["kind"] == "compare":
            if chk.get("operator") not in OPERATORS:
                errs.append("אופרטור השוואה לא מוכר")
            t = chk.get("threshold")
            if t is not None and not isinstance(t, (int, float)):
                errs.append("ערך סף חייב להיות מספר (או ריק = חסר במקור)")
            tb = chk.get("threshold_by")
            if tb is not None and not (isinstance(tb, dict) and tb.get("fact") and isinstance(tb.get("map"), dict)):
                errs.append("threshold_by: נדרשים fact ו־map")
        if chk["kind"] == "consistency" and not isinstance(chk.get("max_rel_diff"), (int, float)):
            errs.append("max_rel_diff חייב להיות מספר (למשל 0.05)")
        if chk["kind"] == "any_present" and not (isinstance(chk.get("items"), list)
                                                 and all(isinstance(i, dict) and ("doc_type" in i or "cad_role" in i)
                                                         for i in chk["items"])):
            errs.append("items: רשימה של {doc_type} או {cad_role}")
    app = raw.get("applicability")
    if app is not None:
        if not isinstance(app, dict) or set(app) - {"all", "any"}:
            errs.append("תחולה: אובייקט עם all / any")
        else:
            for c in (app.get("all") or []) + (app.get("any") or []):
                if not (isinstance(c, dict) and c.get("fact")):
                    errs.append("תנאי תחולה ללא fact")
                    break
                op = c.get("op", "eq")
                op = ("true" if op else "false") if isinstance(op, bool) else op
                if op not in CONDITION_OPS:
                    errs.append(f"אופרטור תחולה לא מוכר: {op}")
                    break
    srcs = raw.get("sources", [])
    if not isinstance(srcs, list) or not all(isinstance(x, dict) and x.get("source_id") for x in srcs):
        errs.append("מקורות: רשימה של {source_id, section, page, quote_he}")
    if errs:
        return errs
    try:
        evaluate_rule(Rule(dict(raw)), {"case": {}}, {}, tenant_is_demo=True)
    except Exception as e:  # noqa: BLE001
        errs.append(f"הכלל אינו ניתן להרצה: {type(e).__name__}: {e}")
    return errs


def bump_version(v: str | None) -> str:
    """'0.1' -> '0.2', '1.9' -> '1.10', '3' -> '3.1'."""
    parts = str(v or "0").split(".")
    if len(parts) > 1 and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{v or '0'}.1"
