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
  BBP_APP_URL=https://<app host>              (DWFX conversion; default: the relay URL without /llm-relay)
  BBP_CONVERT_PYTHON=<python with PyMuPDF>    (default: the repository's .venv/bin/python)
  BBP_DWFX_CONVERSION=0                       turns the DWFX converter off
The agent also converts DWFX drawings for the app (Converter below): drawings are rendered on this PC, not the server.
Run:  python3 bbp_ai_agent.py   (systemd --user unit bbp-ai-agent). Standard library only.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

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


class Converter:
    """Converts DWFX drawings for the app on this PC (agent/dwfx_convert.py, run with a Python that has PyMuPDF).

    Pulls work from the app API (/api/agent/conversions/*) with the relay token: next -> source -> result. The file
    lives in a temporary folder only while it is converted. A failure is reported back, so the case shows why."""

    def __init__(self, app_url: str, token: str, python: str, stop: threading.Event, timeout_s: float = 900.0):
        self.app = app_url.rstrip("/")
        self.auth = {"Authorization": f"Bearer {token}"}
        self.python = python
        self.stop = stop
        self.timeout_s = timeout_s
        self.script = str(Path(__file__).with_name("dwfx_convert.py"))

    def _call(self, path: str, data=None, method="POST", headers: dict | None = None, timeout: float = 120.0):
        req = urllib.request.Request(f"{self.app}/api/agent/conversions{path}", data=data, method=method,
                                     headers={**self.auth, **(headers or {})})
        return urllib.request.urlopen(req, timeout=timeout)

    def once(self) -> bool:
        """Converts one waiting file; False when there was none."""
        with self._call("/next", data=b"") as r:
            if r.status == 204:
                return False
            job = json.loads(r.read())
        fid = job["file_id"]
        with tempfile.TemporaryDirectory(prefix="bbp-dwfx-") as tmp:
            src, dst = Path(tmp) / "in.dwfx", Path(tmp) / "out.pdf"
            with self._call(f"/{fid}/source", method="GET", timeout=600) as r, src.open("wb") as f:
                shutil.copyfileobj(r, f)
            t0 = time.monotonic()
            try:
                p = subprocess.run([self.python, self.script, str(src), str(dst)], capture_output=True, text=True,
                                   timeout=self.timeout_s)
                info = json.loads((p.stdout or "{}").strip().splitlines()[-1] or "{}") if p.stdout.strip() else {}
                error = info.get("error") or (None if p.returncode == 0 and dst.exists() else
                                              (p.stderr.strip().splitlines() or ["conversion failed"])[-1][:300])
            except subprocess.TimeoutExpired:
                info, error = {}, f"ההמרה חרגה מ-{int(self.timeout_s)} שניות"
            info["seconds"] = round(time.monotonic() - t0, 1)
            head = {"X-Conversion-Status": "failed" if error else "ok",
                    "X-Conversion-Info": urllib.parse.quote(json.dumps(info, ensure_ascii=False)),
                    "Content-Type": "text/plain; charset=utf-8" if error else "application/pdf"}
            body = error.encode() if error else dst.read_bytes()
            with self._call(f"/{fid}/result", data=body, headers=head, timeout=600) as r:
                log.info("dwfx %s (%s): %s in %.1fs -> %d", fid, job.get("filename"), "failed: " + error if error
                         else "converted", info["seconds"], r.status)
        return True

    def run(self, interval: float = 10.0) -> None:
        backoff = interval
        while not self.stop.is_set():
            try:
                busy = self.once()
                backoff = interval
            except urllib.error.HTTPError as e:
                log.warning("dwfx converter: app answered %d %s", e.code, e.read()[:200].decode(errors="replace"))
                busy, backoff = False, min(backoff * 2, 300)
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                log.warning("dwfx converter: %s", e)
                busy, backoff = False, min(backoff * 2, 300)
            if not busy:
                self.stop.wait(backoff)


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
    app_url = os.environ.get("BBP_APP_URL") or relay.rstrip("/").removesuffix("/llm-relay")
    python = os.environ.get("BBP_CONVERT_PYTHON") or str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python")
    if os.environ.get("BBP_DWFX_CONVERSION", "1") != "0" and Path(python).exists():
        conv = Converter(app_url, token, python, agent.stop)
        threading.Thread(target=conv.run, daemon=True).start()
        log.info("dwfx converter: %s with %s", app_url, python)
    else:
        log.info("dwfx converter: off (BBP_DWFX_CONVERSION=0 or no Python with PyMuPDF at %s)", python)
    agent.run()


if __name__ == "__main__":
    main()
