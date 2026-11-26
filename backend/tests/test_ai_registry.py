"""Model registry, prompt versions and task routing: deterministic first, objective escalation only."""
import pytest
from fastapi.testclient import TestClient

from app.ai import gateway as G, registry as R
from app.main import app


def test_registry_has_provenance_and_nothing_validated_yet():
    ms = R.models()["models"]
    assert ms and all(m["sha256"] and m["license"] and m["status"] in ("IN_USE", "CANDIDATE") for m in ms)
    assert all(m["validated_for"] == [] for m in ms)            # installed is not validated
    assert R.in_use_for("ReportDraft") and R.in_use_for("SemanticEmbedding")


def test_prompt_versions_follow_text(monkeypatch):
    v = R.prompt_version("report_draft")
    assert len(v) == 12
    monkeypatch.setattr(G, "REPORT_PROMPT", G.REPORT_PROMPT + " ")
    assert R.prompt_version("report_draft") != v
    assert G._prompt_ref("ReportDraft", "local_ollama")["prompt"].startswith("report_draft@")
    assert G._prompt_ref("ReportDraft", "local_template") == {}


def test_routing():
    assert R.decide("NUMERIC_VALIDATION")["outcome"] == "DETERMINISTIC"
    assert R.decide("GEOMETRY")["executor"] == "deterministic"
    assert R.decide("REPORT_LANGUAGE")["outcome"] == "MODEL"
    d = R.decide("REPORT_LANGUAGE", ["numbers_not_in_source"])
    assert d["escalate"] and d["outcome"] == "UNRESOLVED"        # no model validated to escalate to
    assert R.decide("REGULATORY_REASONING")["outcome"] == "UNRESOLVED"
    with pytest.raises(ValueError):
        R.decide("REPORT_LANGUAGE", ["model_seems_unsure"])        # self-reported confidence is not a trigger


def test_registry_api():
    from app.seed import seed
    seed(reset=True, samples=True)
    c = TestClient(app)
    r = c.get("/api/ai/registry", headers={"X-User": "u-admin"})
    assert r.status_code == 200 and {x["task"] for x in r.json()["routes"]} >= {"GEOMETRY", "VISION_ANALYSIS"}
    assert c.get("/api/ai/registry", headers={"X-User": "u-reviewer"}).status_code == 403
