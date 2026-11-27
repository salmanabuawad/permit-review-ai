"""Normalised finding record (Permit360 1.8 / V11 §20–21, §30) built from what a run already stores.

Adds, per finding: difference (measured − permitted, signed), measurement method, evidence category, drawing
reference, source reference, the V11 check status and the ten accuracy gates (PASS / FAIL / NOT_EVALUATED — a gate
the engine does not model yet is reported as such, never as passed). `external_eligible` is True only for a violation
whose mandatory gates all pass; this is an internal view and does not change the current external report.
"""
from __future__ import annotations

EVIDENCE_BY_OPERAND = (("measure.", "GEOMETRIC_MEASUREMENT"), ("declared.", "DECLARED_VALUE"),
                       ("facts_derived.", "DRAWING_DIMENSION"), ("history.", "HISTORICAL_COMMITTEE_MEASUREMENT"))
GATES = ("verified_source", "geographic_applicability", "temporal_applicability", "evidence", "units_and_comparison",
         "exceptions_considered", "reliefs_considered", "measurement_uncertainty", "relevance", "current_version")
MANDATORY = ("verified_source", "geographic_applicability", "evidence", "units_and_comparison",
             "measurement_uncertainty", "relevance", "current_version")


def evidence_category(rule_raw: dict, f) -> str | None:
    chk = (rule_raw or {}).get("check") or {}
    if any((e or {}).get("type") == "measurement" for e in (f.evidence or [])):
        return "GEOMETRIC_MEASUREMENT"
    op = chk.get("operand") or ""
    for prefix, cat in EVIDENCE_BY_OPERAND:
        if op.startswith(prefix):
            return cat
    if chk.get("kind") in ("doc_required", "any_present"):
        return "DOCUMENT_PRESENCE"
    return None


def check_status(rule_raw: dict, f, gates: dict) -> str:
    kind = ((rule_raw or {}).get("check") or {}).get("kind")
    flags = set(f.flags or [])
    if "ENGINE_ERROR" in flags or "EXECUTION_ERROR" in flags:
        return "EXECUTION_ERROR"
    if f.status == "PASS":
        return "PASS"
    if f.status == "NA":
        return "NOT_APPLICABLE"
    if f.status == "FAIL":
        if kind == "consistency":
            return "DECLARATION_MISMATCH"
        if kind in ("doc_required", "any_present", "cad_roles"):
            return "DOCUMENT_INCONSISTENCY"
        return "CONFIRMED_VIOLATION" if all(gates[g] == "PASS" for g in MANDATORY) else "UNRESOLVED"
    if kind == "qualitative":
        return "DISCRETIONARY_REVIEW_REQUIRED"
    return "UNRESOLVED"


def gates_of(rule_raw: dict, f, latest: bool) -> dict:
    flags = set(f.flags or [])
    kind = ((rule_raw or {}).get("check") or {}).get("kind")
    numeric = kind == "compare"
    state = (rule_raw or {}).get("review_state")
    g = {
        "verified_source": "PASS" if f.citations and state == "PROFESSIONALLY_APPROVED" and "RULE_NOT_APPROVED" not in flags else "FAIL",
        "geographic_applicability": "FAIL" if "APPLICABILITY_UNKNOWN" in flags else "PASS",
        "temporal_applicability": "FAIL" if any("DATE" in x for x in flags) else "NOT_EVALUATED",
        "evidence": ("PASS" if f.measured_value is not None else "FAIL") if numeric else
                    ("FAIL" if "INCOMPLETE" in flags else "PASS"),
        "units_and_comparison": ("PASS" if f.operator and f.threshold is not None else "FAIL") if numeric else "PASS",
        "exceptions_considered": "NOT_EVALUATED" if not (rule_raw or {}).get("exceptions") else "PASS",
        "reliefs_considered": "PASS" if any(x.startswith("RELIEF") for x in flags) else "NOT_EVALUATED",
        "measurement_uncertainty": "FAIL" if "WITHIN_UNCERTAINTY_BAND" in flags else "PASS",
        "relevance": "FAIL" if f.status == "NA" else "PASS",
        "current_version": "PASS" if latest else "FAIL",
    }
    return g


def normalise(f, rule_raw: dict | None, latest: bool = True) -> dict:
    gates = gates_of(rule_raw or {}, f, latest)
    status = check_status(rule_raw or {}, f, gates)
    diff = None
    if f.measured_value is not None and f.threshold is not None:
        diff = round(float(f.measured_value) - float(f.threshold), 4)
    meas = next((e for e in (f.evidence or []) if (e or {}).get("type") == "measurement"), None) or {}
    chk = ((rule_raw or {}).get("check") or {})
    return {
        "finding_id": f.id, "rule_id": f.rule_id, "rule_version": f.rule_version, "description": f.title_he,
        "explanation": f.explanation_he, "severity": f.severity, "engine_status": f.status,
        "check_status": status,
        "measured_value": f.measured_value, "measured_uncertainty": f.measured_uncertainty,
        "permitted_value": f.threshold, "operator": f.operator, "units": f.units, "difference": diff,
        "method": meas.get("method") or chk.get("geometry_method_he"),
        "evidence_category": evidence_category(rule_raw or {}, f),
        "drawing_reference": {"entities": meas.get("source_entities"), "key": meas.get("key"),
                              "overlay": bool(f.overlay_wkt)} if meas or f.overlay_wkt else None,
        "source_references": f.citations or [], "confidence": f.confidence,
        "recommended_action": f.fix_hint_he, "professional_validation": f.reviewer_decision or "PENDING",
        "gates": gates, "external_eligible": status == "CONFIRMED_VIOLATION",
    }


def coverage(rows: list[dict]) -> dict:
    """Against the run's full inventory: how many checks reached each V11 status, and independent measurement share."""
    by: dict[str, int] = {}
    for r in rows:
        by[r["check_status"]] = by.get(r["check_status"], 0) + 1
    applicable = [r for r in rows if r["check_status"] != "NOT_APPLICABLE"]
    measured = [r for r in applicable if r["evidence_category"] == "GEOMETRIC_MEASUREMENT"]
    numeric = [r for r in applicable if r["permitted_value"] is not None]
    return {"checks": len(rows), "applicable": len(applicable), "by_status": by,
            "decided": sum(1 for r in applicable if r["check_status"] in ("PASS", "CONFIRMED_VIOLATION", "DECLARATION_MISMATCH", "DOCUMENT_INCONSISTENCY")),
            "independent_measurement": {"numeric_checks": len(numeric), "measured": len(measured)}}
