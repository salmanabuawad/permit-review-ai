"""LLM relay (as on muniflow.kortexd.com): the API calls the relay, the AI PC's agent pulls the jobs and serves them
from its local model server."""
from __future__ import annotations

import dataclasses
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.ai import gateway
from app.ai import relay as relay_mod
from app.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
from bbp_ai_agent import Agent, allowed  # noqa: E402

TOKEN = "relay-test-token"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app) -> tuple[uvicorn.Server, str]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    return server, f"http://127.0.0.1:{port}"


fake_model = FastAPI()
seen: list[dict] = []


@fake_model.post("/v1/chat/completions")
def _chat(body: dict):
    seen.append(body)
    if body["model"] != "ministral-3-8b-iq4xs":
        return JSONResponse({"error": {"message": f"model '{body['model']}' not found"}}, status_code=404)
    prompt = body["messages"][0]["content"]
    content = (json.dumps({"label": "survey_map", "confidence": 0.9}) if "סווג" in prompt
               else json.dumps({"gush": {"value": "6195", "page": 1, "quote": "גוש 6195"}}) if "חלץ" in prompt
               else "סיכום")
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}


@pytest.fixture(scope="module")
def servers():
    mp = pytest.MonkeyPatch()
    mp.setattr(relay_mod, "settings", dataclasses.replace(
        settings, llm_relay_token=TOKEN, llm_relay_pickup_timeout_s=2, llm_relay_response_timeout_s=10,
        llm_relay_poll_interval_s=0.2))
    relay_srv, relay_url = _serve(relay_mod.app)
    model_srv, model_url = _serve(fake_model)
    yield relay_url, model_url
    relay_srv.should_exit = model_srv.should_exit = True
    mp.undo()


@pytest.fixture()
def api(servers, monkeypatch):
    """The API side: BBP_LLM_BASE_URL points at the relay; a fresh relay state per test."""
    relay_url, _ = servers
    monkeypatch.setattr(relay_mod, "relay", relay_mod.Relay())
    monkeypatch.setattr(gateway, "settings", dataclasses.replace(settings, llm_base_url=relay_url + "/v1",
                                                                  llm_timeout_s=10))
    return relay_url


@pytest.fixture()
def agent(servers, api):
    relay_url, model_url = servers
    a = Agent(relay_url, model_url, TOKEN, concurrency=2, local_timeout_s=10)
    t = threading.Thread(target=a.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 5
    while not relay_mod.relay.last_seen and time.monotonic() < deadline:
        time.sleep(0.02)
    yield a
    a.stop.set()
    t.join(5)


def _gw():
    policy = gateway.AIGateway().policy
    policy["providers"]["local_ollama"]["enabled"] = True
    for p in policy["policies"]:
        if p["task"] == "Extraction" and p["data_class"] == "CASE_DOCUMENT":
            p["providers"] = ["local_ollama", "local_rules"]
    return gateway.AIGateway(policy)


def _post(url, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="POST", headers=headers or {}), timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_agent_endpoints_need_the_token(api):
    assert _post(api + "/agent/next") == 401
    assert _post(api + "/agent/next", {"Authorization": "Bearer wrong"}) == 401
    assert _post(api + "/agent/next", {"Authorization": f"Bearer {TOKEN}"}) == 204


def test_agent_only_forwards_model_calls():
    assert allowed("POST", "v1/chat/completions") and allowed("GET", "/v1/models")
    assert not allowed("POST", "api/pull") and not allowed("DELETE", "api/delete")
    assert not allowed("POST", "v1/chat/completions/../../api/pull")


def test_no_agent_falls_back_at_once(api):
    t0 = time.monotonic()
    res = _gw().route("Classification", "CASE_DOCUMENT", {"filename": "a.pdf", "text": "מפת מדידה"})
    assert time.monotonic() - t0 < 1
    assert res.outcome == "FALLBACK" and res.provider_id == "local_keyword"
    assert "503" in res.trail[0]["error"]


def test_classification_runs_on_the_ai_pc(agent):
    res = _gw().route("Classification", "CASE_DOCUMENT", {"filename": "a.pdf", "text": "מפת מדידה"})
    assert res.outcome == "OK" and res.provider_id == "local_ollama"
    assert res.output == {"label": "survey_map", "confidence": 0.9}
    assert seen[-1]["response_format"] == {"type": "json_object"} and seen[-1]["model"] == "ministral-3-8b-iq4xs"
    assert relay_mod.relay.served >= 1 and not relay_mod.relay.jobs


def test_extraction_runs_on_the_ai_pc(agent):
    payload = {"file": "p.pdf", "sha": "x", "pages": [(1, "גוש 6195 חלקה 12")]}
    res = _gw().route("Extraction", "CASE_DOCUMENT", payload)
    assert res.provider_id == "local_ollama"
    assert res.output["gush"]["value"] == "6195" and res.output["gush"]["source"]["provider"].endswith("ministral-3-8b-iq4xs")


def test_model_error_comes_back_and_falls_back(agent):
    policy = _gw().policy
    policy["providers"]["local_ollama"]["model_version"] = "not-installed"
    res = gateway.AIGateway(policy).route("Classification", "CASE_DOCUMENT", {"filename": "a.pdf", "text": "מפת מדידה"})
    assert res.outcome == "FALLBACK" and "404" in res.trail[0]["error"]


def test_drawing_reader_frees_the_gpu_before_reading(monkeypatch):
    """A resident text model on a small GPU made the image model fail to load (every sheet → 500). The reader unloads
    the other loaded models first; a server without the router API is tolerated."""
    import bbp_ai_agent as AG
    calls = []

    class Resp:
        def __init__(self, body=b"{}"):
            self.body = body

        def read(self):
            return self.body

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        calls.append((url, None if isinstance(req, str) else req.data))
        if url.endswith("/v1/models"):
            return Resp(json.dumps({"data": [{"id": "text-8b", "status": {"value": "loaded"}},
                                             {"id": "vision", "status": {"value": "unloaded"}},
                                             {"id": "other", "status": {"value": "unloaded"}}]}).encode())
        return Resp()
    monkeypatch.setattr(AG.urllib.request, "urlopen", fake)
    r = AG.DrawingReader("http://app", "t", sys.executable, threading.Event(), "vision", "http://llm/v1/chat/completions")
    r._free_gpu()
    assert calls[1] == ("http://llm/models/unload", b'{"model": "text-8b"}') and len(calls) == 2

    def down(req, timeout=None):
        raise urllib.error.URLError("no router")
    monkeypatch.setattr(AG.urllib.request, "urlopen", down)
    r._free_gpu()                                            # no exception


def test_document_classification_covers_every_type_and_rejects_others():
    from app.ai import gateway as G
    from app.services import DOC_TYPES_HE
    assert set(G.DOC_TYPE_DESCRIPTIONS) == set(DOC_TYPES_HE)
    kw = G._kw_classify({"filename": "גוש 2832 חלקה 27.pdf", "text": "נסח רישום מקרקעין"})
    assert kw["label"] == "ownership_docs"
    assert G._kw_classify({"filename": "חישוב שטחים ומס יחידות דיור.pdf", "text": ""})["label"] == "area_table"
    assert G._kw_classify({"filename": "חברת החשמל.pdf", "text": ""})["label"] == "electric_company_approval"
