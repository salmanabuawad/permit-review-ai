"""The run's AI summary is reused when its exact prompt and provider are unchanged, regenerated otherwise."""
from sqlalchemy import select

from app import services
from app.ai.gateway import AIResult
from app.db import SessionLocal
from app.models import InferenceCost, PermitCase
from app.seed import seed


class FakeGateway:
    def __init__(self, outcome="OK"):
        self.calls, self.outcome = 0, outcome

    def policy_for(self, task, data_class):
        return {"providers": ["local_relay"]}

    def providers(self):
        return {"local_relay": {"model": "m-1"}}

    def route(self, task, data_class, payload, log=None):
        self.calls += 1
        r = AIResult(task, self.outcome, "local_relay", "m-1", {"text": f"summary {self.calls}", "citations": []},
                     latency_ms=25000, tokens_in=5000, tokens_out=300)
        log and log(r)
        return r


def test_summary_reused_only_for_identical_prompt():
    seed(reset=True, samples=True)
    with SessionLocal() as s:
        case = s.scalars(select(PermitCase)).first()
        gw = FakeGateway()
        log = services.gateway_logger(s, case.tenant_id, case.id, "u-reviewer")
        payload = {"findings": [{"rule_id": "R1", "status": "FAIL"}], "passages": []}
        a, hit_a = services.cached_report_draft(s, gw, case, payload, log)
        b, hit_b = services.cached_report_draft(s, gw, case, payload, log)
        assert (hit_a, hit_b) == (False, True) and gw.calls == 1 and b.output == a.output
        changed = {"findings": [{"rule_id": "R1", "status": "PASS"}], "passages": []}
        c, hit_c = services.cached_report_draft(s, gw, case, changed, log)
        assert not hit_c and gw.calls == 2
        outcomes = [r.outcome for r in s.scalars(select(InferenceCost).where(InferenceCost.case_id == case.id))]
        assert outcomes.count("CACHE_HIT") == 1


def test_fallback_is_not_cached_and_model_change_misses():
    seed(reset=True, samples=True)
    with SessionLocal() as s:
        case = s.scalars(select(PermitCase)).first()
        payload = {"findings": [], "passages": []}
        fb = FakeGateway("FALLBACK")
        services.cached_report_draft(s, fb, case, payload, None)
        services.cached_report_draft(s, fb, case, payload, None)
        assert fb.calls == 2                                       # a template fallback is retried
        gw = FakeGateway()
        services.cached_report_draft(s, gw, case, payload, None)
        gw2 = FakeGateway()
        gw2.providers = lambda: {"local_relay": {"model": "m-2"}}  # another model: no reuse
        _, hit = services.cached_report_draft(s, gw2, case, payload, None)
        assert not hit and gw2.calls == 1
