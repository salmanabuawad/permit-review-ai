"""LLM relay: the language model runs on an AI PC that pulls its jobs from this server — the same design as
muniflow.kortexd.com (muniflow.ai.relay).

The AI PC has no inbound connection: its agent (agent/bbp_ai_agent.py) calls this relay over outbound HTTPS, takes
one request at a time, runs it on its own inference server (llama.cpp router or Ollama) and streams the response back.

Consumers (the API) on this host:   POST /v1/chat/completions, GET /v1/models    OpenAI-compatible, loopback only
                                    (BBP_LLM_BASE_URL=http://127.0.0.1:18112/v1)
Agent (through nginx /llm-relay/):  POST /agent/next                 the next job (204 = none); the agent pulls again
                                                                     after X-Relay-Poll-Interval seconds
                                    POST /agent/jobs/{id}/response   streamed response body, X-Relay-Status header
Health:                             GET  /health

No agent connected = HTTP 503 at once, so the AI gateway falls back to its non-LLM provider (keyword classifier,
rule extractor, report template). Jobs live only in this process's memory — case text is never written to disk
here — so run it as ONE process (systemd bbp-llm-relay, 127.0.0.1:18112).

Run: uvicorn app.ai.relay:app --app-dir backend --host 127.0.0.1 --port 18112 --workers 1
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import time
import uuid
from dataclasses import dataclass, field

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import ClientDisconnect

from ..config import settings

log = logging.getLogger("bbp.llm_relay")

MAX_BODY = 4 * 1024 * 1024
_BROKEN = object()  # the agent's upload broke off: abort the consumer's response instead of returning it truncated


@dataclass
class Job:
    method: str
    path: str
    body: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    picked: asyncio.Event = field(default_factory=asyncio.Event)
    head: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    chunks: asyncio.Queue = field(default_factory=asyncio.Queue)
    canceled: bool = False


class Relay:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.jobs: dict[str, Job] = {}
        self.waiting = 0          # agent pulls in progress
        self.last_seen = 0.0      # monotonic time of the agent's last call
        self.served = 0
        self.failed = 0

    def agent_online(self) -> bool:
        # three missed pulls (plus slack for a slow connection) = the agent is gone
        return (self.waiting > 0 or bool(self.jobs)
                or time.monotonic() - self.last_seen < 3 * settings.llm_relay_poll_interval_s + 5)


relay = Relay()
app = FastAPI(title="BBP LLM relay", docs_url=None, redoc_url=None, openapi_url=None)


def _unavailable(message: str, status: int = 503) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": "relay_unavailable"}}, status_code=status)


# ------------------------------------------------------------------ consumers (loopback)
async def _forward(method: str, path: str, request: Request):
    if not relay.agent_online():
        return _unavailable("no inference agent connected")
    body = await request.body()
    if len(body) > MAX_BODY:
        return _unavailable("request too large", 413)
    job = Job(method, path, body.decode("utf-8", errors="replace"))
    relay.queue.put_nowait(job)
    try:
        await asyncio.wait_for(job.picked.wait(), settings.llm_relay_pickup_timeout_s)
        status, ctype = await asyncio.wait_for(job.head, settings.llm_relay_response_timeout_s)
    except TimeoutError:
        job.canceled = True
        relay.jobs.pop(job.id, None)
        relay.failed += 1
        return _unavailable("inference agent did not answer in time", 504 if job.picked.is_set() else 503)

    async def stream():
        try:
            while True:
                chunk = await asyncio.wait_for(job.chunks.get(), settings.llm_relay_response_timeout_s)
                if chunk is None:
                    relay.served += 1
                    return
                if chunk is _BROKEN:
                    raise RuntimeError("inference agent connection broke off")
                yield chunk
        except (TimeoutError, RuntimeError):
            relay.failed += 1
            raise
        finally:
            job.canceled = True
            relay.jobs.pop(job.id, None)

    return StreamingResponse(stream(), status_code=status, media_type=ctype)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _forward("POST", "v1/chat/completions", request)


@app.get("/v1/models")
async def models(request: Request):
    return await _forward("GET", "v1/models", request)


@app.get("/health")
def health():
    seen = time.monotonic() - relay.last_seen if relay.last_seen else None
    return {"ok": relay.agent_online(), "agent_last_seen_s": round(seen, 1) if seen is not None else None,
            "agent_polls_open": relay.waiting, "queued": relay.queue.qsize(), "active": len(relay.jobs),
            "served": relay.served, "failed": relay.failed, "poll_interval_s": settings.llm_relay_poll_interval_s}


# ------------------------------------------------------------------ agent (public through nginx, token-protected)
def agent_auth(authorization: str | None = Header(default=None)) -> None:
    expected = settings.llm_relay_token
    token = (authorization or "")[7:] if (authorization or "").lower().startswith("bearer ") else ""
    if not expected:
        raise HTTPException(503, "relay token not configured")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "unauthorized")


@app.post("/agent/next", dependencies=[Depends(agent_auth)])
async def next_job(wait: float = Query(0, ge=0, le=55)):
    headers = {"X-Relay-Poll-Interval": f"{settings.llm_relay_poll_interval_s:g}"}
    relay.waiting += 1
    relay.last_seen = time.monotonic()
    deadline = relay.last_seen + wait
    try:
        while True:
            try:
                left = deadline - time.monotonic()
                job = relay.queue.get_nowait() if left <= 0 else await asyncio.wait_for(relay.queue.get(), left)
            except (asyncio.QueueEmpty, TimeoutError):
                break
            if job.canceled:
                continue
            relay.jobs[job.id] = job
            job.picked.set()
            return JSONResponse({"id": job.id, "method": job.method, "path": job.path, "body": job.body},
                                headers=headers)
        return Response(status_code=204, headers=headers)
    finally:
        relay.waiting -= 1
        relay.last_seen = time.monotonic()


@app.post("/agent/jobs/{job_id}/response", dependencies=[Depends(agent_auth)])
async def job_response(job_id: str, request: Request, x_relay_status: int = Header(200),
                       x_relay_content_type: str = Header("application/json")):
    job = relay.jobs.get(job_id)
    if job is None or job.canceled:
        raise HTTPException(410, "job is no longer waiting")
    relay.last_seen = time.monotonic()
    if not job.head.done():
        job.head.set_result((x_relay_status, x_relay_content_type))
    try:
        async for chunk in request.stream():
            if job.canceled:
                raise HTTPException(410, "consumer went away")
            if chunk:
                job.chunks.put_nowait(chunk)
    except ClientDisconnect:
        job.chunks.put_nowait(_BROKEN)
        log.warning("agent upload for job %s broke off", job_id)
        return Response(status_code=499)
    job.chunks.put_nowait(None)
    relay.last_seen = time.monotonic()
    return {"ok": True}
