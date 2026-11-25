"""Facts derived from the request text and declared form data for completeness rules.

Explicit declared values always win over text inference. A fact is left unset when there is
nothing to infer it from, so the rule engine reports it as unknown instead of guessing.
"""
from __future__ import annotations

import re

from .doc_signals import ISSUER_HE

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


# Which body an approval of this document type must come from (see doc_signals.ISSUERS).
EXPECTED_ISSUER = {"electric_company_approval": "iec", "antiquities_approval": "iaa"}


def derive_document_facts(files: list[dict], case_gush: str | None, reference_date: str | None) -> dict:
    """Case facts from per-file content signals.

    `files`: [{"filename", "doc_type", "doc_label_he", "signals"}] for the case's active files. Files
    uploaded before signals existed have no "signals" and are skipped. Each list fact is set only when
    at least one file could be checked for it, so "nothing to check" stays unknown (rule NA), not PASS.
    """
    with_sig = [f for f in files if isinstance(f.get("signals"), dict)]
    out: dict = {}
    if not with_sig:
        return out

    def name(f: dict) -> str:
        label = f.get("doc_label_he") or f.get("doc_type") or ""
        return f"{f['filename']} ({label})" if label else f["filename"]

    out["placeholder_docs"] = [name(f) for f in with_sig if f["signals"].get("placeholder")]
    texty = [f for f in with_sig if f["signals"].get("has_text") and not f["signals"].get("placeholder")]

    gush = str(case_gush).strip() if case_gush else ""
    if gush and any(f["signals"].get("blocks") for f in texty):
        out["foreign_parcel_docs"] = [f"{name(f)}: גוש {', '.join(f['signals']['blocks'])}" for f in texty
                                      if f["signals"].get("blocks") and gush not in f["signals"]["blocks"]]

    typed = [f for f in texty if f.get("doc_type") in EXPECTED_ISSUER]
    if typed:
        out["issuer_mismatch_docs"] = []
        for f in typed:
            want, found = EXPECTED_ISSUER[f["doc_type"]], f["signals"].get("issuers") or []
            if want not in found:
                others = ", ".join(ISSUER_HE[i] for i in found) or "לא זוהה גורם"
                out["issuer_mismatch_docs"].append(f"{name(f)}: אינו מזכיר את {ISSUER_HE[want]} (מוזכר: {others})")

    iaa = [f for f in texty if "iaa" in (f["signals"].get("issuers") or [])]
    if iaa:
        out["antiquities_demand_docs"] = [name(f) for f in iaa if f["signals"].get("iaa_demand")]

    licences = [f for f in texty if f["signals"].get("license_valid_until")]
    if licences and reference_date:
        receipts = [f["signals"]["fee_receipt_date"] for f in with_sig if f["signals"].get("fee_receipt_date")]
        out["expired_licence_docs"] = []
        for f in licences:
            until = f["signals"]["license_valid_until"]
            renewed = any(r > until for r in receipts)   # a later annual-fee receipt renews the licence
            if until < reference_date and not renewed:
                out["expired_licence_docs"].append(f"{name(f)}: בתוקף עד {until}")
    return out
