"""AI Gateway: pluggable providers per task with policy enforcement.

route(task, data_class, payload) walks the policy's provider order and only calls a provider
that is (a) enabled, (b) approved, (c) supports the task and (d) whose location is allowed
for the data class. If none succeeds the outcome is MANUAL_REVIEW. Every call — including
blocked ones — is logged to inference_costs with latency and cost for the dashboard.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from ..config import settings

TASKS = ["OCR", "Layout", "Vision", "Parsing", "Retrieval", "Classification", "ReportDraft"]


@dataclass
class AIResult:
    task: str
    outcome: str                        # OK | FALLBACK | MANUAL_REVIEW | BLOCKED_BY_POLICY
    provider_id: str | None
    model_version: str | None
    output: Any = None
    latency_ms: int = 0
    cost_ils: float = 0.0
    trail: list[dict] = field(default_factory=list)   # why each provider was used/skipped


class ProviderError(RuntimeError):
    pass


# ----------------------------------------------------------------- provider implementations

DOC_KEYWORDS = {
    "application_form": [r"בקשה\s+להיתר", r"טופס\s+בקשה"],
    "survey_map": [r"מפת\s+מדידה", r"מודד\s+מוסמך"],
    "permit_info": [r"מידע\s+להיתר"],
    "area_table": [r"טבלת\s+שטחים", r"שטח\s+עיקרי"],
    "existing_building_photos": [r"תמונ(ה|ות)\s+(של\s+)?(ה)?בניין", r"צילום"],
    "building_master_plan": [r"תכנית\s+כוללת", r"תוספות\s+עתידיות"],
    "ownership_docs": [r"נסח\s+טאבו", r"נסח\s+רישום"],
    "consents": [r"הסכמ(ה|ות)\s+בעלי", r"הסכמת\s+השכנים"],
    "architectural_plan": [r"תכנית\s+הגשה", r"גרמושק"],
}


def _kw_classify(payload: dict) -> dict:
    text = (payload.get("filename", "") + "\n" + payload.get("text", ""))[:20000]
    scores = {k: sum(len(re.findall(p, text)) for p in pats) for k, pats in DOC_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return {"label": None, "confidence": 0.0, "scores": scores}
    total = sum(scores.values())
    return {"label": best, "confidence": round(scores[best] / total, 2), "scores": scores}


def _template_report(payload: dict) -> dict:
    f = payload.get("findings", [])
    cnt = {s: sum(1 for x in f if x["status"] == s) for s in ("PASS", "FAIL", "UNCERTAIN", "NA")}
    lines = [f"סיכום אוטומטי (טיוטה, המלצה בלבד): נבדקו {len(f)} כללים.",
             f"עומד: {cnt['PASS']}; לא עומד: {cnt['FAIL']}; דורש בדיקה: {cnt['UNCERTAIN']}; לא חל: {cnt['NA']}."]
    fails = [x for x in f if x["status"] == "FAIL"]
    if fails:
        lines.append("אי-התאמות עיקריות: " + "; ".join(x["title_he"] for x in fails[:5]) + ".")
    lines.append("כל ממצא מבוסס על מנוע הכללים ואסמכתאות; ההחלטה בסמכות הבודק המוסמך.")
    return {"text": "\n".join(lines)}


def _ollama(task: str, model: str, payload: dict) -> dict:
    prompt = {
        "Classification": "סווג את סוג המסמך לאחת הקטגוריות: " + ", ".join(DOC_KEYWORDS) +
                          ". החזר JSON {\"label\":...,\"confidence\":0..1}. טקסט:\n" + payload.get("text", "")[:4000],
        "ReportDraft": "נסח סיכום קצר בעברית לממצאים הבאים בלבד, ללא הוספת עובדות:\n" +
                       json.dumps(payload.get("findings", [])[:30], ensure_ascii=False),
    }[task]
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "format": "json" if task == "Classification" else ""}).encode()
    req = urllib.request.Request(settings.ollama_url + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read())["response"]
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"ollama: {exc}") from exc
    if task == "Classification":
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise ProviderError("ollama returned non-JSON") from exc
    return {"text": out}


def _bm25(payload: dict) -> dict:
    from ..knowledge import search
    return {"hits": search(payload["query"], k=payload.get("k", 5))}


IMPLEMENTATIONS: dict[str, Callable[[str, dict, dict], dict]] = {
    "local_keyword": lambda task, p, cfg: _kw_classify(p),
    "local_template": lambda task, p, cfg: _template_report(p),
    "local_bm25": lambda task, p, cfg: _bm25(p),
    "local_ollama": lambda task, p, cfg: _ollama(task, cfg["model_version"], p),
}


# ----------------------------------------------------------------- gateway

class AIGateway:
    def __init__(self, policy: dict | None = None, overrides: list[dict] | None = None,
                 implementations: dict | None = None):
        self.policy = policy or yaml.safe_load(
            (settings.knowledge_dir / "ai_policy.yaml").read_text(encoding="utf-8"))
        self.overrides = overrides or []
        self.impl = {**IMPLEMENTATIONS, **(implementations or {})}

    def providers(self) -> dict:
        return self.policy["providers"]

    def policy_for(self, task: str, data_class: str) -> dict | None:
        for p in self.overrides + self.policy["policies"]:
            if p["task"] == task and p["data_class"] == data_class:
                return p
        return None

    def check_provider(self, pid: str, task: str, data_class: str) -> str | None:
        """Return a reason string if the provider may NOT be used, else None."""
        cfg = self.providers().get(pid)
        if not cfg:
            return "ספק לא מוגדר"
        if not cfg.get("approved"):
            return "ספק לא אושר ע\"י הרשות"
        if cfg.get("enabled", True) is False:
            return "ספק מושבת"
        if task not in cfg.get("tasks", []):
            return "הספק אינו תומך במשימה"
        allowed = self.policy["data_classes"].get(data_class, {}).get("allowed_locations", [])
        if cfg.get("location") not in allowed:
            return f"מיקום עיבוד {cfg.get('location')} אסור לסוג מידע {data_class}"
        if cfg.get("kind") == "CLOUD" and not cfg.get("no_training_on_data"):
            return "ספק ענן ללא התחייבות לאי-אימון על הנתונים"
        return None

    def route(self, task: str, data_class: str, payload: dict, log: Callable[[AIResult], None] | None = None) -> AIResult:
        pol = self.policy_for(task, data_class)
        if not pol:
            res = AIResult(task, "BLOCKED_BY_POLICY", None, None,
                           trail=[{"reason": "אין מדיניות מוגדרת למשימה/סוג מידע"}])
            log and log(res)
            return res
        trail, first_ok = [], True
        for pid in pol["providers"]:
            reason = self.check_provider(pid, task, data_class)
            if reason:
                trail.append({"provider": pid, "skipped": reason})
                first_ok = False
                continue
            cfg = self.providers()[pid]
            impl = self.impl.get(pid)
            if impl is None:
                trail.append({"provider": pid, "skipped": "אין מימוש"})
                first_ok = False
                continue
            t0 = time.perf_counter()
            try:
                out = impl(task, payload, cfg)
            except Exception as exc:  # noqa: BLE001
                trail.append({"provider": pid, "error": str(exc)[:200]})
                first_ok = False
                continue
            ms = int((time.perf_counter() - t0) * 1000)
            res = AIResult(task, "OK" if first_ok else "FALLBACK", pid, cfg.get("model_version"), out, ms,
                           float(cfg.get("cost_per_unit_ils", 0.0)), trail + [{"provider": pid, "used": True}])
            log and log(res)
            return res
        res = AIResult(task, "MANUAL_REVIEW", None, None, trail=trail)
        log and log(res)
        return res
