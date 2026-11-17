"""LLM relay agent for the permit-review app: runs on the AI PC and serves the server's model calls from the local
model — the same design as muniflow.kortexd.com's relay agent (muniflow.ai.relay_agent).

Every connection is outbound: the agent pulls the relay (backend/app/ai/relay.py, on the server behind nginx
/llm-relay/) for a job, runs it on the local OpenAI-compatible server and streams the response back. When there is no
job it pulls again after the interval the relay sends with every answer (X-Relay-Poll-Interval). Only the calls in
ALLOWED are served: the relay cannot make this PC do anything else. Case text is held in memory only during a call.

Local inference server: the llama.cpp router on :8081 that already serves muniflow on this PC (default), or Ollama
(http://127.0.0.1:11434, which also speaks /v1). The model name the server asks for (knowledge/ai_policy.yaml,
local_ollama.model_version) must be one that server has.

Settings (environment, e.g. ~/.config/bbp-ai-agent.env):
  BBP_LLM_RELAY_URL=https://<app host>/llm-relay
  BBP_LLM_RELAY_TOKEN=<same value as BBP_LLM_RELAY_TOKEN in /etc/bbp.env on the server>
  BBP_LLM_RELAY_LOCAL=http://127.0.0.1:8081
  BBP_LLM_RELAY_CONCURRENCY=2
Run:  python3 bbp_ai_agent.py   (systemd --user unit bbp-ai-agent). Standard library only.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("bbp.llm_relay_agent")

ALLOWED = {("POST", "v1/chat/completions"), ("GET", "v1/models")}
CHUNK = 64 * 1024


def allowed(method: str, path: str) -> bool:
    return (method.upper(), path.split("?", 1)[0].strip("/")) in ALLOWED and ".." not in path


def _interval(header: str | None, current: float) -> float:
    try:
        return min(max(float(header), 0.2), 60.0) if header else current
    except ValueError:
        return current


class Agent:
    def __init__(self, relay: str, local: str, token: str, concurrency: int = 2, local_timeout_s: float = 300.0):
        self.relay = relay.rstrip("/")
        self.local = local.rstrip("/")
        self.auth = {"Authorization": f"Bearer {token}"}
        self.concurrency = concurrency
        self.local_timeout_s = local_timeout_s
        self.stop = threading.Event()

    # ---------------------------------------------------------------- relay calls
    def _relay(self, path: str, data=None, headers: dict | None = None, timeout: float = 70.0):
        req = urllib.request.Request(f"{self.relay}{path}", data=data, method="POST",
                                     headers={**self.auth, **(headers or {})})
        return urllib.request.urlopen(req, timeout=timeout)

    def _reply(self, job_id: str, status: int, body, content_type: str = "application/json") -> int:
        """Upload the response; `body` is bytes or an iterable of chunks (sent chunked, i.e. streamed)."""
        try:
            with self._relay(f"/agent/jobs/{job_id}/response", data=body, timeout=self.local_timeout_s + 10,
                             headers={"X-Relay-Status": str(status), "X-Relay-Content-Type": content_type}) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code          # 410: the server stopped waiting for this job
        except (urllib.error.URLError, OSError) as e:
            log.warning("job %s: could not upload the response: %s", job_id, e)
            return 0

    # ---------------------------------------------------------------- work
    def serve(self, job: dict) -> int:
        """Runs one job and returns the HTTP status it was answered with."""
        method, path = job["method"], job["path"]
        if not allowed(method, path):
            log.warning("refused job %s: %s %s", job["id"], method, path)
            self._reply(job["id"], 403, b'{"error":{"message":"not allowed by the relay agent"}}')
            return 403
        req = urllib.request.Request(f"{self.local}/{path.lstrip('/')}", method=method,
                                     data=(job.get("body") or "").encode() or None,
                                     headers={"Content-Type": "application/json"})
        try:
            lr = urllib.request.urlopen(req, timeout=self.local_timeout_s)
        except urllib.error.HTTPError as e:     # the model server's own error (e.g. unknown model) goes back as is
            lr = e
        except (urllib.error.URLError, OSError) as e:
            log.warning("job %s: local inference server unreachable: %s", job["id"], e)
            self._reply(job["id"], 502, b'{"error":{"message":"local inference server unreachable"}}')
            return 502
        status = lr.status if hasattr(lr, "status") else lr.code
        with lr:
            relay_status = self._reply(job["id"], status, iter(lambda: lr.read(CHUNK), b""),
                                       lr.headers.get("Content-Type", "application/json"))
        log.info("%s %s %s -> %d (relay %d)", method, path, _model(job) or "", status, relay_status)
        return status

    def worker(self, n: int) -> None:
        backoff, interval = 1.0, 1.0
        while not self.stop.is_set():
            try:
                r = self._relay("/agent/next")
            except urllib.error.HTTPError as e:
                log.warning("worker %d: relay answered %d %s", n, e.code, e.read()[:200].decode(errors="replace"))
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 60)
                continue
            except (urllib.error.URLError, OSError) as e:
                log.warning("worker %d: relay unreachable (%s), retrying in %.0fs", n, e, backoff)
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 60)
                continue
            backoff = 1.0
            with r:
                interval = _interval(r.headers.get("X-Relay-Poll-Interval"), interval)
                job = json.loads(r.read()) if r.status == 200 else None
            if job is None:          # 204: no work
                self.stop.wait(interval)
                continue
            self.serve(job)

    def run(self) -> None:
        threads = [threading.Thread(target=self.worker, args=(i,), daemon=True) for i in range(self.concurrency)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


def _model(job: dict) -> str | None:
    try:
        body = json.loads(job.get("body") or "{}")
    except ValueError:
        return None
    return body.get("model") if isinstance(body, dict) and isinstance(body.get("model"), str) else None


def main() -> None:
    relay = os.environ.get("BBP_LLM_RELAY_URL", "")
    token = os.environ.get("BBP_LLM_RELAY_TOKEN", "")
    local = os.environ.get("BBP_LLM_RELAY_LOCAL", "http://127.0.0.1:8081")
    if not relay or not token:
        raise SystemExit("BBP_LLM_RELAY_URL and BBP_LLM_RELAY_TOKEN must be set")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = Agent(relay, local, token, int(os.environ.get("BBP_LLM_RELAY_CONCURRENCY", "2")),
                  float(os.environ.get("BBP_LLM_RELAY_LOCAL_TIMEOUT", "300")))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: agent.stop.set())
    log.info("relay agent: %s -> %s (%d workers)", agent.relay, agent.local, agent.concurrency)
    agent.run()


if __name__ == "__main__":
    main()
