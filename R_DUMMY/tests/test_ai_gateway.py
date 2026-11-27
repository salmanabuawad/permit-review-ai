"""AI gateway policy enforcement: residency, approval, fallback, manual review."""
import copy

import yaml

from app.ai.gateway import AIGateway
from app.config import settings

BASE = yaml.safe_load((settings.knowledge_dir / "ai_policy.yaml").read_text(encoding="utf-8"))


def gw(mutate=None, impl=None):
    pol = copy.deepcopy(BASE)
    if mutate:
        mutate(pol)
    return AIGateway(policy=pol, implementations=impl or {})


def test_case_documents_never_go_to_cloud_even_if_approved():
    def m(p):
        p["providers"]["cloud_llm_il"].update(approved=True, enabled=True)
        p["policies"].append({"task": "Classification", "data_class": "PII", "mode": "CLOUD",
                              "providers": ["cloud_llm_il"]})
    called = []
    g = gw(m, {"cloud_llm_il": lambda t, p, c: called.append(1) or {"label": "x"}})
    res = g.route("Classification", "PII", {"text": "ת.ז."})
    assert res.outcome == "MANUAL_REVIEW" and not called
    assert "אסור" in res.trail[0]["skipped"]


def test_unapproved_provider_skipped():
    g = gw()
    assert "לא אושר" in g.check_provider("cloud_llm_il", "Vision", "CASE_DOCUMENT")


def test_fallback_to_next_allowed_provider():
    def m(p):
        p["providers"]["local_ollama"]["enabled"] = True
    def boom(*a):
        raise RuntimeError("down")
    res = gw(m, {"local_ollama": boom}).route("Classification", "CASE_DOCUMENT",
                                             {"filename": "x.pdf", "text": "מפת מדידה מודד מוסמך"})
    assert res.outcome == "FALLBACK" and res.provider_id == "local_keyword"
    assert res.output["label"] == "survey_map"


def test_all_providers_fail_gives_manual_review():
    res = gw().route("Vision", "CASE_DOCUMENT", {})
    assert res.outcome == "MANUAL_REVIEW"


def test_no_policy_blocks():
    assert gw().route("Layout", "CASE_DOCUMENT", {}).outcome == "BLOCKED_BY_POLICY"


def test_cloud_without_no_training_commitment_refused():
    def m(p):
        p["providers"]["cloud_llm_il"].update(approved=True, enabled=True, no_training_on_data=False)
    assert "אימון" in gw(m).check_provider("cloud_llm_il", "Classification", "PUBLIC_REGULATION")


def test_logger_called_for_every_outcome():
    seen = []
    gw().route("Vision", "CASE_DOCUMENT", {}, log=seen.append)
    gw().route("ReportDraft", "CASE_DOCUMENT", {"findings": []}, log=seen.append)
    assert [r.outcome for r in seen] == ["MANUAL_REVIEW", "FALLBACK"]
