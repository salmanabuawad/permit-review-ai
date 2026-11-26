"""API: health, metadata, AI settings, integrations, dashboard and audit."""
from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


# ------------------------------------------------------------------ meta / auth

@router.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "env": settings.environment,
            "integrations_enabled": settings.integrations_enabled}


@router.get("/api/meta")
def meta():
    return {"permit_types": PERMIT_TYPES, "tracks": TRACKS, "stages": STAGES, "zones": ZONES,
            "doc_types": services.DOC_TYPES_HE, "case_statuses": CASE_STATUSES, "roles": ROLES}


@router.get("/api/ai")
def ai_settings(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    gw = _gateway_for(s, p.tenant_id)
    pols = []
    seen = set()
    for pol in gw.overrides + gw.policy["policies"]:
        key = (pol["task"], pol["data_class"])
        if key in seen:
            continue
        seen.add(key)
        pols.append({**pol, "provider_checks": {pid: gw.check_provider(pid, pol["task"], pol["data_class"])
                                                for pid in pol["providers"]}})
    return {"providers": gw.providers(), "data_classes": gw.policy["data_classes"], "policies": pols,
            "provider_settings": services.ai_provider_settings(s, p.tenant_id)}


@router.get("/api/ai/llm")
def ai_llm_status(p: Principal = Depends(require("case.read"))):
    """Where the language model runs and whether it answers: the AI PC through the LLM relay, or a local server."""
    base = settings.llm_base_url.rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    out: dict = {"base_url": base, "via_relay": False, "connected": None, "models": [], "error": None}
    try:
        h = _http_json(root + "/health", 3)
        if isinstance(h, dict) and "agent_polls_open" in h:
            out.update(via_relay=True, connected=bool(h.get("ok")), relay=h)
    except Exception:  # noqa: BLE001 — not a relay (e.g. Ollama has no /health)
        pass
    if out["connected"] is False:
        out["error"] = "מחשב ה-AI אינו מחובר"
        return out
    try:
        out["models"] = sorted(m["id"] for m in _http_json(base + "/models", 10).get("data", []))
        out["connected"] = True
    except Exception as e:  # noqa: BLE001
        out["connected"], out["error"] = False, f"{type(e).__name__}: {str(e)[:160]}"
    return out


@router.put("/api/ai/providers/{pid}")
def set_provider(pid: str, body: ProviderIn, p: Principal = Depends(require("ai.configure")),
                 s: Session = Depends(get_session)):
    import re
    base = AIGateway().providers().get(pid)
    if base is None:
        raise HTTPException(404, "ספק לא מוגדר")
    if body.enabled and not base.get("approved"):
        raise HTTPException(409, "הספק לא אושר ע\"י הרשות — לא ניתן להפעיל")
    if body.model_version is not None and not re.fullmatch(r"[A-Za-z0-9._:/@+-]{1,120}", body.model_version):
        raise HTTPException(422, "שם מודל לא תקין")
    tenant = s.get(Municipality, p.tenant_id)
    cfg = dict(tenant.settings or {})
    ai = dict(cfg.get("ai") or {})
    providers = dict(ai.get("providers") or {})
    before = dict(providers.get(pid) or {})
    after = {**before, **{k: v for k, v in body.model_dump().items() if v is not None}}
    if after.get("model_version") == base.get("model_version"):
        after.pop("model_version")                    # same as the catalogue: no override
    if after.get("enabled") == base.get("enabled", True):
        after.pop("enabled", None)
    providers[pid] = after
    if not after:
        providers.pop(pid)
    ai["providers"] = providers
    cfg["ai"] = ai
    tenant.settings = cfg                             # reassign: JSON column change tracking
    audit.record(s, p.tenant_id, p.id, "ai.provider.update", "ai_provider", pid, {"before": before, "after": after})
    s.commit()
    return {"ok": True, "provider": services.gateway_for(s, p.tenant_id).providers()[pid]}


@router.post("/api/ai/test")
def ai_test(body: AITestIn, p: Principal = Depends(require("ai.configure")), s: Session = Depends(get_session)):
    """One real call through the tenant's gateway with a fixed sample (no case data)."""
    if body.task not in AI_TEST_PAYLOADS:
        raise HTTPException(422, "משימה לא נתמכת בבדיקה")
    res = _gateway_for(s, p.tenant_id).route(body.task, "CASE_DOCUMENT", AI_TEST_PAYLOADS[body.task],
                                             log=services.gateway_logger(s, p.tenant_id, None, p.id))
    s.commit()
    return {"task": res.task, "outcome": res.outcome, "provider": res.provider_id, "model": res.model_version,
            "latency_ms": res.latency_ms, "output": res.output, "trail": res.trail}


@router.put("/api/ai/policy")
def set_policy(body: PolicyIn, p: Principal = Depends(require("ai.configure")), s: Session = Depends(get_session)):
    gw = _gateway_for(s, p.tenant_id)
    if body.mode not in ("LOCAL", "CLOUD", "HYBRID"):
        raise HTTPException(422)
    blocked = {pid: gw.check_provider(pid, body.task, body.data_class) for pid in body.providers}
    if body.mode == "LOCAL" and any(gw.providers().get(pid, {}).get("kind") == "CLOUD" for pid in body.providers):
        raise HTTPException(422, "מצב LOCAL אינו יכול לכלול ספק ענן")
    s.add(AIPolicyRow(tenant_id=p.tenant_id, task=body.task, data_class=body.data_class, mode=body.mode,
                      provider_order=body.providers, approved_by=p.id, approved_at=dt.datetime.now(dt.timezone.utc)))
    audit.record(s, p.tenant_id, p.id, "ai.policy.update", "ai_policy", f"{body.task}/{body.data_class}",
                 {**body.model_dump(), "provider_checks": blocked})
    s.commit()
    return {"ok": True, "provider_checks": blocked}


@router.get("/api/integrations")
def integrations():
    data = yaml.safe_load((settings.knowledge_dir / "integrations.yaml").read_text(encoding="utf-8"))
    return [{**i, "enabled": False, "connected": False} for i in data["integrations"]]


# ------------------------------------------------------------------ dashboard / audit

@router.get("/api/dashboard")
def dashboard(p: Principal = Depends(require("dashboard.read")), s: Session = Depends(get_session)):
    t = p.tenant_id
    by_status = dict(s.execute(select(PermitCase.status, func.count()).where(PermitCase.tenant_id == t, PermitCase.kind != "design")
                               .group_by(PermitCase.status)).all())
    by_reviewer = dict(s.execute(select(PermitCase.assigned_to, func.count()).where(PermitCase.tenant_id == t, PermitCase.kind != "design")
                                 .group_by(PermitCase.assigned_to)).all())
    now = dt.datetime.now(dt.timezone.utc)
    overdue = 0
    for c in s.scalars(select(PermitCase).where(PermitCase.tenant_id == t, PermitCase.kind != "design")):
        due = c.sla_due.replace(tzinfo=dt.timezone.utc) if c.sla_due and c.sla_due.tzinfo is None else c.sla_due
        if due and due < now and c.status not in ("REVIEWER_APPROVED", "CLOSED"):
            overdue += 1
    costs = s.execute(select(InferenceCost.task, InferenceCost.outcome, func.count(), func.sum(InferenceCost.cost_ils),
                             func.avg(InferenceCost.latency_ms)).where(InferenceCost.tenant_id == t)
                      .group_by(InferenceCost.task, InferenceCost.outcome)).all()
    cost_per_case = s.execute(select(InferenceCost.case_id, func.sum(InferenceCost.cost_ils))
                              .where(InferenceCost.tenant_id == t, InferenceCost.case_id.is_not(None))
                              .group_by(InferenceCost.case_id)).all()
    findings = dict(s.execute(select(Finding.status, func.count()).where(Finding.tenant_id == t)
                              .group_by(Finding.status)).all())
    durations = [r for (r,) in s.execute(select(CheckRun.duration_ms).where(CheckRun.tenant_id == t))]
    return {
        "cases_by_status": by_status, "cases_by_reviewer": {k or "unassigned": v for k, v in by_reviewer.items()},
        "sla_overdue": overdue, "findings_by_status": findings,
        "ai_usage": [{"task": a, "outcome": b, "calls": c, "cost_ils": round(d or 0, 4), "avg_latency_ms": round(e or 0)}
                     for a, b, c, d, e in costs],
        "cost_per_case": {k: round(v or 0, 4) for k, v in cost_per_case},
        "run_duration_ms": {"count": len(durations), "max": max(durations, default=0),
                            "avg": round(sum(durations) / len(durations)) if durations else 0},
        "stages": metrics.stage_stats(s, t),
        **metrics.cost_breakdown(s, t),
        "kpi_note_he": "מדדי הקבלה של המכרז (95%/90%/85%) יימדדו מול ground truth של בודקים על 100 תיקי אמת — טרם נמדדו.",
    }


@router.get("/api/audit")
def audit_list(limit: int = 200, p: Principal = Depends(require("audit.read")), s: Session = Depends(get_session)):
    evs = s.scalars(select(AuditEvent).where(AuditEvent.tenant_id == p.tenant_id)
                    .order_by(AuditEvent.id.desc()).limit(min(limit, 1000)))
    ok, bad = audit.verify_chain(s, p.tenant_id)
    return {"chain_ok": ok, "first_bad_id": bad,
            "events": [{"id": e.id, "at": e.at.isoformat(), "actor": e.actor, "action": e.action, "entity": e.entity,
                        "entity_id": e.entity_id, "detail": e.detail, "hash": e.hash[:16]} for e in evs]}


# ------------------------------------------------------------------ model registry, prompts, routing (Permit360 1.7)

@router.get("/api/ai/registry")
def ai_registry(p: Principal = Depends(require("ai.configure"))):
    """Local models (source, licence, hash, status, validated tasks), prompt versions and the routing table."""
    from ..ai import registry as R
    return {"hardware": R.models().get("hardware", {}), "models": R.models().get("models", []),
            "prompts": list(R.prompts().values()),
            "routes": [{"task": t, **R.decide(t)} for t in R.ROUTES], "triggers": list(R.TRIGGERS)}
