"""Facts derived from the request text and declared form data for completeness rules.

Explicit declared values always win over text inference. A fact is left unset when there is
nothing to infer it from, so the rule engine reports it as unknown instead of guessing.
"""
from __future__ import annotations

import re

DISABLED_UNIT_RX = re.compile(r"דיר(?:ת|ות)\s*נכ(?:ה|ים)")
LEGALIZATION_RX = re.compile(r"מצב\s*קיים|הכשר(?:ת|ה)\b|לגליזציה|בני(?:י)?ה\s*קיימת\s*ללא\s*היתר")


def _as_int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def derive_completeness_facts(title: str | None, application_type: str | None, declared: dict | None) -> dict:
    declared = declared or {}
    text = " ".join(t for t in (title, application_type, declared.get("description")) if t)
    out: dict = {}

    if "disabled_unit" in declared:
        out["disabled_unit_requested"] = bool(declared["disabled_unit"])
    elif text:
        out["disabled_unit_requested"] = bool(DISABLED_UNIT_RX.search(text))

    if "legalization_existing" in declared:
        out["legalization_existing"] = bool(declared["legalization_existing"])
    elif text:
        out["legalization_existing"] = bool(LEGALIZATION_RX.search(text))

    signed, total = _as_int(declared.get("owners_signed")), _as_int(declared.get("owners_total"))
    if signed is not None and total and total > 0 and 0 <= signed <= total:
        out["owner_signatures_pct"] = round(100.0 * signed / total, 2)
        out["owner_signatures_incomplete"] = signed < total
    return out
