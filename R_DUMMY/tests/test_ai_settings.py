"""AI settings: provider on/off and model per tenant, bulk mode, test call, grounded report drafts."""
import pytest
from fastapi.testclient import TestClient

from app.ai import gateway
from app.ai.gateway import AIGateway, ProviderError, _ollama
from app.main import app
from app.seed import seed

H = lambda u: {"X-User": u}  # noqa: E731


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def test_provider_settings_change_the_gateway():
    gw = AIGateway(provider_settings={"local_ollama": {"enabled": False, "model_version": "gemma-4-e4b"}})
    assert gw.providers()["local_ollama"]["model_version"] == "gemma-4-e4b"
    assert gw.check_provider("local_ollama", "Classification", "CASE_DOCUMENT") == "ספק מושבת"
    assert AIGateway().providers()["local_ollama"]["model_version"] == "ministral-3-8b-iq4xs"   # catalogue untouched


def test_bulk_mode_skips_the_llm():
    assert AIGateway().check_provider("local_ollama", "Classification", "CASE_DOCUMENT") is None
    assert "מרובת" in AIGateway(bulk=True).check_provider("local_ollama", "Classification", "CASE_DOCUMENT")


def test_admin_sets_provider_and_it_is_audited(client):
    assert client.put("/api/ai/providers/local_ollama", headers=H("u-reviewer"), json={"enabled": False}).status_code == 403
    r = client.put("/api/ai/providers/local_ollama", headers=H("u-admin"), json={"enabled": False, "model_version": "qwen3.5-4b"})
    assert r.status_code == 200 and r.json()["provider"]["enabled"] is False
    d = client.get("/api/ai", headers=H("u-admin")).json()
    assert d["providers"]["local_ollama"]["model_version"] == "qwen3.5-4b"
    assert d["provider_settings"]["local_ollama"] == {"enabled": False, "model_version": "qwen3.5-4b"}
    t = client.post("/api/ai/test", headers=H("u-admin"), json={"task": "Classification"}).json()
    assert t["provider"] == "local_keyword" and t["output"]["label"] == "survey_map"     # LLM off -> keyword
    assert client.put("/api/ai/providers/cloud_llm_il", headers=H("u-admin"), json={"enabled": True}).status_code == 409
    assert client.put("/api/ai/providers/local_ollama", headers=H("u-admin"), json={"model_version": "a b"}).status_code == 422
    # back to the catalogue values: no override left
    client.put("/api/ai/providers/local_ollama", headers=H("u-admin"), json={"enabled": True, "model_version": "ministral-3-8b-iq4xs"})
    assert "local_ollama" not in client.get("/api/ai", headers=H("u-admin")).json()["provider_settings"]
    audit = client.get("/api/audit", headers=H("u-admin")).json()
    assert any(e["action"] == "ai.provider.update" for e in (audit if isinstance(audit, list) else audit.get("events", [])))


FINDINGS = [{"status": "FAIL", "title_he": "נסיגת חדר גג", "explanation_he": "נמדד: 2.49 מ׳; נדרש ≥ 2.50 מ׳."},
            {"status": "PASS", "title_he": "גובה", "explanation_he": "נתון בתיק: 4.00"}]


def test_report_draft_with_invented_numbers_falls_back(monkeypatch):
    monkeypatch.setattr(gateway, "llm_chat", lambda *a, **k: "נבדקו 2 כללים. הנסיגה 2.49 מ׳ קטנה מ־3 מ׳.")
    with pytest.raises(ProviderError, match="3"):
        _ollama("ReportDraft", "m", {"findings": FINDINGS})
    monkeypatch.setattr(gateway, "llm_chat", lambda *a, **k: "נבדקו 2 כללים: 1 לא עומד (נסיגת חדר גג, 2.49 מ׳) ו־1 עומד.")
    assert _ollama("ReportDraft", "m", {"findings": FINDINGS})["text"].startswith("נבדקו 2")
