"""Model registry, prompt registry and task routing (Permit360 1.7).

* Models: `knowledge/ai_models.yaml` — every local model on disk with source, licence, SHA-256, quantisation, host,
  status (IN_USE / CANDIDATE) and `validated_for` (empty until the Hebrew planning benchmark passes; being installed
  is not validation).
* Prompts: each prompt's version is the SHA-256 of its exact text, so any wording change is a new version; the version
  goes into every AI result's trail and into cache keys (the summary cache keys on the full prompt text).
* Routing: each task type has a default executor. Deterministic work (numbers, geometry, comparisons, report layout)
  never goes to a model. Escalation to a stronger model happens only on objective triggers — never on a model's own
  confidence — and only to a model approved for that task; with none approved the item stays UNRESOLVED.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

import yaml

from ..config import settings


@lru_cache(maxsize=1)
def models() -> dict:
    p = settings.knowledge_dir / "ai_models.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {"models": [], "hardware": {}}


def prompts() -> dict[str, dict]:
    from . import gateway as G
    texts = {"report_draft": G.REPORT_PROMPT, "report_kb": G.KB_PROMPT, "extraction": G.EXTRACTION_PROMPT, "assistant": G.ASSISTANT_PROMPT}
    return {pid: {"id": pid, "version": hashlib.sha256(t.encode("utf-8")).hexdigest()[:12], "chars": len(t)}
            for pid, t in texts.items()}


def prompt_version(pid: str) -> str | None:
    return (prompts().get(pid) or {}).get("version")


TASK_PROMPT = {"ReportDraft": "report_draft", "Extraction": "extraction", "Assistant": "assistant"}

# task → executor, model role, reason. V11 §37 task list; deterministic first.
ROUTES = {
    "TEXT_EXTRACTION": ("deterministic", None, "PDF / Office parsers; no model"),
    "NUMERIC_VALIDATION": ("deterministic", None, "rule engine and units; never a model"),
    "GEOMETRY": ("deterministic", None, "CAD / drawing geometry algorithms"),
    "REPORT_LAYOUT": ("deterministic", None, "templates; the model only writes the optional narrative"),
    "DOCUMENT_CLASSIFICATION": ("rules_then_model", "Classification", "keyword rules first; local model when they do not decide"),
    "SEMANTIC_EMBEDDING": ("model", "SemanticEmbedding", "local multilingual embedding model on the server CPU"),
    "RETRIEVAL_RERANKING": ("deterministic", None, "reciprocal rank fusion; no reranker model validated yet"),
    "REGULATORY_EXTRACTION": ("model", "Extraction", "local LLM with schema validation"),
    "COMPONENT_IDENTIFICATION": ("rules_then_model", "Classification", "terminology ontology first"),
    "VISION_ANALYSIS": ("model", "VisionDrawing", "local vision model on drawing close-ups"),
    "REPORT_LANGUAGE": ("model", "ReportDraft", "local LLM; numbers it writes must appear in the facts"),
    "REGULATORY_REASONING": ("escalate_only", None, "needs a model validated for reasoning; none yet → UNRESOLVED"),
    "CONFLICT_ANALYSIS": ("escalate_only", None, "conflicts go to a professional; a model may only summarise"),
    "RELIEF_ANALYSIS": ("escalate_only", None, "discretionary; professional decision"),
    "SECONDARY_VERIFICATION": ("escalate_only", None, "second model only when a validated one exists"),
}

TRIGGERS = ("missing_evidence", "schema_invalid", "numbers_not_in_source", "exception_may_apply",
            "inconsistent_rules", "material_defect_unverified", "complex_justification")


def in_use_for(role: str) -> list[dict]:
    return [m for m in models().get("models", []) if role in (m.get("in_use_for") or [])]


def validated_for(role: str) -> list[dict]:
    return [m for m in models().get("models", []) if role in (m.get("validated_for") or [])]


def decide(task: str, triggers: list[str] | None = None) -> dict:
    """Which executor handles the task, and whether objective triggers call for escalation (and to what)."""
    executor, role, why = ROUTES.get(task, ("escalate_only", None, "unknown task"))
    bad = [t for t in (triggers or []) if t not in TRIGGERS]
    if bad:
        raise ValueError(f"unknown triggers: {bad}")
    out = {"task": task, "executor": executor, "role": role, "reason": why,
           "models": [m["file"] for m in in_use_for(role)] if role else [], "escalate": False, "outcome": None}
    if executor == "deterministic":
        out["outcome"] = "DETERMINISTIC"
        return out
    if triggers or executor == "escalate_only":
        stronger = validated_for(role or task)
        out["escalate"] = True
        out["escalate_to"] = [m["file"] for m in stronger]
        out["outcome"] = "ESCALATE" if stronger else "UNRESOLVED"
        out["reason"] += f"; triggers: {', '.join(triggers or []) or 'task requires validated reasoning'}"
    else:
        out["outcome"] = "MODEL" if out["models"] else "UNRESOLVED"
    return out
