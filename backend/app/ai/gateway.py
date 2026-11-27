"""AI Gateway: pluggable providers per task with policy enforcement.

route(task, data_class, payload) walks the policy's provider order and only calls a provider
that is (a) enabled, (b) approved, (c) supports the task and (d) whose location is allowed
for the data class. If none succeeds the outcome is MANUAL_REVIEW. Every call — including
blocked ones — is logged to inference_costs with latency and cost for the dashboard.
"""
from __future__ import annotations

import copy
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml

from ..config import settings

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
    tokens_in: int = 0                  # as reported by the model server's `usage` (0 = not reported / no model)
    tokens_out: int = 0


class ProviderError(RuntimeError):
    pass


# ----------------------------------------------------------------- provider implementations

DOC_KEYWORDS = {
    "application_form": [r"בקשה\s+להיתר", r"טופס\s+בקשה", r"פרטי\s+הבקשה", r"permitRequest"],
    "survey_map": [r"מפת\s+מדידה", r"מודד\s+מוסמך", r"מפה\s+מצבית", r"תכנית\s+מדידה"],
    "permit_info": [r"מידע\s+להיתר", r"תיק\s+(ה)?מידע"],
    "area_table": [r"טבלת\s+שטחים", r"חישוב\s+שטחים", r"שטח\s+עיקרי"],
    "existing_building_photos": [r"תמונ(ה|ות)\s+(של\s+)?(ה)?בניין", r"צילום"],
    "building_master_plan": [r"תכנית\s+כוללת", r"תוספות\s+עתידיות"],
    "ownership_docs": [r"נסח\s+טאבו", r"נסח\s+רישום", r"נסח\s+מקרקעין", r"גוש\s+\d+\s+חלקה\s+\d+", r"חוזה\s+(חכירה|שכירות)",
                       r"הסכם\s+משבצת", r"רמ\"?י", r"מורשי\s+חתימה", r"תעודת\s+רישום"],
    "consents": [r"הסכמ(ה|ות)\s+בעלי", r"הסכמת\s+השכנים"],
    "architectural_plan": [r"תכנית\s+הגשה", r"גרמושק", r"PERMIT", r"hagasha"],
    "sections_elevations": [r"חתך", r"חזית\s+(צפונית|דרומית|מזרחית|מערבית|קדמית|אחורית)"],
    "electric_company_approval": [r"חברת\s+(ה)?חשמל", r"חח\"?י"],
    "antiquities_approval": [r"רשות\s+העתיקות", r"עתיקות"],
    "professional_license": [r"רי?שיון\s+מקצועי", r"תעודת\s+רישום\s+(ב)?אדריכל", r"פנקס\s+המהנדסים"],
    "planning_regulation": [r"הוראות\s+התכנית", r"תקנון", r"מידע\s+תכנוני", r"נספח\s+בינוי"],
    "committee_protocol": [r"פרוטוקול\s+(ישיבת|ועדת)", r"החלטות\s+ועדת", r"ישיבה\s+מספר"],
}
DOC_TYPE_DESCRIPTIONS = {
    "application_form": "טופס הבקשה להיתר (רישוי זמין) והצהרות המבקש / עורך הבקשה",
    "survey_map": "מפת מדידה / מפה מצבית של מודד מוסמך",
    "permit_info": "תיק מידע להיתר",
    "architectural_plan": "תכנית ההגשה (גרמושקה) — קומות, חתכים, חזיתות",
    "area_table": "חישוב שטחים / טבלת שטחים",
    "existing_building_photos": "צילומי מצב קיים",
    "building_master_plan": "תכנית כוללת / בינוי לבניין",
    "ownership_docs": "מסמכי זכויות בקרקע: נסח, חוזה חכירה / משבצת, אישור רמ\"י, מורשי חתימה",
    "consents": "הסכמות בעלי זכויות / שכנים",
    "sections_elevations": "חתכים וחזיתות כמסמך נפרד",
    "committee_protocol": "פרוטוקול או החלטת ועדה",
    "disabled_committee_approval": "אישור ועדת נכים",
    "inspection_report": "דו\"ח פיקוח",
    "electric_company_approval": "אישור חברת החשמל",
    "antiquities_approval": "אישור רשות העתיקות",
    "professional_license": "רישיון / תעודת רישום של עורך הבקשה או מתכנן",
    "reg36_notice_proof": "אסמכתא להודעה לבעלים (תקנה 36)",
    "planning_regulation": "מסמך תכנוני: הוראות תכנית, נספח בינוי, מידע תכנוני",
    "other": "אחר — אישור גורם, קבלה, מינוי, הצהרת מתכנן שלד וכד'",
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
    passages = payload.get("passages") or []
    if passages:   # no model: list the passages retrieved for the open findings, without paraphrasing them
        lines.append("קטעי ידע רלוונטיים לבדיקה: " + "; ".join(
            f"{p.get('section')} ({p.get('source_title_he')}) [{p['id']}]" for p in passages[:4]) + ".")
    lines.append("כל ממצא מבוסס על מנוע הכללים ואסמכתאות; ההחלטה בסמכות הבודק המוסמך.")
    return {"text": "\n".join(lines), "citations": [p["id"] for p in passages[:4]]}


def llm_chat(model: str, prompt: str, json_mode: bool = False) -> str:
    """One OpenAI-compatible chat completion at BBP_LLM_BASE_URL: local Ollama's /v1, or the LLM relay whose agent
    runs it on the AI PC. Errors (HTTP 503 = no agent connected, 504 = no answer in time) propagate to the caller."""
    body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, "temperature": 0}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(settings.llm_base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=settings.llm_timeout_s) as r:
        data = json.loads(r.read())
    u = data.get("usage") or {}
    acc = _USAGE.get()
    if acc is not None:
        acc.append((int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)))
    return data["choices"][0]["message"]["content"]


DRAWING_TYPES = {
    "survey_map": "מפת מדידה של מודד מוסמך: גבולות מגרש וחלקות, מספרי חלקות, נקודות גובה (רומים), רשת קואורדינטות, "
                  "עצים ומבנים קיימים, חותמת מודד — בלי חלוקת חדרים",
    "architectural_plan": "תכנית הגשה / גרמושקה: תכניות קומה עם חדרים, קירות ומידות, טבלאות שטחים, דף תנאים וחתימות",
    "sections_elevations": "חתכים וחזיתות של בניין בלבד",
}


def vision_drawing_type(png: bytes, filename: str, model: str) -> dict:
    """The local vision model types a drawing sheet that has no text layer. {"label", "confidence"} or raises."""
    import base64
    prompt = ("לפניך גיליון ראשון של קובץ שרטוט מתוך בקשה להיתר בנייה (שם הקובץ: " + filename + "). "
              "קבע את סוג המסמך לאחת האפשרויות:\n" + "\n".join(f"{k}: {v}" for k, v in DRAWING_TYPES.items()) +
              "\nהחזר JSON בלבד: {\"label\": <קוד>, \"confidence\": 0..1}.")
    body = {"model": model, "stream": False, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}
    req = urllib.request.Request(settings.llm_base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=settings.llm_timeout_s) as r:
        out = json.loads(json.loads(r.read())["choices"][0]["message"]["content"])
    if not isinstance(out, dict) or out.get("label") not in DRAWING_TYPES:
        raise ValueError(f"label outside the drawing types: {str(out)[:80]}")
    return out


# token usage of the model calls made inside one route() (a list per context: threads and requests do not mix)
import contextvars  # noqa: E402
_USAGE: contextvars.ContextVar[list | None] = contextvars.ContextVar("llm_usage", default=None)


STATUS_HE = {"PASS": "עומד", "FAIL": "לא עומד", "UNCERTAIN": "דורש בדיקה", "NA": "לא חל"}
REPORT_PROMPT = (
    "אתה מנסח טיוטת סיכום לבודק תכניות. כתוב 3–6 משפטים בעברית על סמך הממצאים שבהמשך בלבד.\n"
    "כללים: השתמש בשמות הכללים ובהסברים כפי שהם. אל תוסיף סיבות, פרשנות, מספרים, סעיפים או שמות שאינם "
    "מופיעים בממצאים. פתח במניין התוצאות, פרט את הממצאים 'לא עומד' ו'דורש בדיקה', וסיים במשפט: "
    "\"הסיכום הוא המלצה בלבד; ההחלטה בסמכות הבודק המוסמך.\" כתוב טקסט רגיל, ללא Markdown (ללא ** או #). "
    "הכללים הם 'כללים', לא 'תכניות'.\nממצאים (JSON):\n")


KB_PROMPT = (
    "\nקטעי ידע מהתכניות, מהחקיקה ומהנחיות הוועדה שחלים על התיק (JSON). חריג לכללים שלמעלה: מותר להוסיף עד שני "
    "משפטים שמקשרים ממצא 'לא עומד' או 'דורש בדיקה' לקטע רלוונטי — רק במה שכתוב בקטע, כולל מספריו — ומיד אחרי "
    "המשפט לציין את מזהה הקטע בסוגריים מרובעים, למשל [P-HA-633-5]. אל תצטט קטע שאינו קשור לממצא; אם אין קטע "
    "רלוונטי, אל תזכיר קטעים כלל.\nקטעים (JSON):\n")
CITATION = re.compile(r"\s*[\[(](P-[A-Za-z0-9.-]+)[\])]")    # [P-HA-633-5]; local models also write (P-HA-633-5)


def _report_passages(payload: dict) -> list[dict]:
    return [{"מזהה": p["id"], "מקור": p.get("source_title_he"), "עמוד": p.get("page"), "סעיף": p.get("section"),
             **({"מעמד": "טקסט מאתר הוועדה — לא מאומת; רקע בלבד"} if p.get("verification") == "UNVERIFIED_COMMITTEE" else {}),
             "תוכן": p.get("text_he")} for p in payload.get("passages") or []]


def report_prompt(payload: dict) -> tuple[str, str]:
    """(prompt, grounding text): the findings, plus the case's knowledge passages when there are any. Every number
    in the draft must appear in the grounding text."""
    facts = json.dumps(_report_facts(payload.get("findings", [])), ensure_ascii=False)
    passages = _report_passages(payload)
    if not passages:
        return REPORT_PROMPT + facts, facts
    kb = json.dumps(passages, ensure_ascii=False)
    return REPORT_PROMPT + facts + KB_PROMPT + kb, facts + kb


def _keep_known_citations(text: str, payload: dict) -> tuple[str, list[str]]:
    """Citations of passages that were given stay; any other bracketed id is removed (never shown as a source)."""
    known = {p["id"] for p in payload.get("passages") or []}
    used: list[str] = []

    def keep(m):
        if m.group(1) in known:
            used.append(m.group(1)) if m.group(1) not in used else None
            return f" [{m.group(1)}]"
        return ""
    return CITATION.sub(keep, text), used


def _report_facts(findings: list[dict]) -> dict:
    """What the model may say: counts, and the non-NA findings with the engine's own explanation."""
    counts = {STATUS_HE[k]: sum(1 for f in findings if f.get("status") == k) for k in STATUS_HE}
    order = {"FAIL": 0, "UNCERTAIN": 1, "PASS": 2}
    items = sorted((f for f in findings if f.get("status") in order), key=lambda f: order[f["status"]])
    return {"נבדקו": len(findings), "תוצאות": counts,
            "ממצאים": [{"כלל": f.get("title_he"), "תוצאה": STATUS_HE[f["status"]], "הסבר": f.get("explanation_he")}
                       for f in items[:25]]}


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _ungrounded_numbers(text: str, facts: str) -> list[str]:
    known = {float(n.replace(",", ".")) for n in _NUM.findall(facts)}
    return [n for n in _NUM.findall(text) if not any(abs(float(n.replace(",", ".")) - k) < 1e-6 for k in known)]


def _ollama(task: str, model: str, payload: dict) -> dict:
    prompt = {
        "Classification": "סווג מסמך מתוך תיק בקשה להיתר בנייה לאחד מסוגי המסמכים הבאים (קוד: תיאור):\n" +
                          "\n".join(f"{k}: {v}" for k, v in DOC_TYPE_DESCRIPTIONS.items()) +
                          "\nהחזר JSON בלבד: {\"label\": <קוד>, \"confidence\": 0..1}.\nשם הקובץ: " +
                          payload.get("filename", "") + "\nטקסט:\n" + payload.get("text", "")[:4000],
        "ReportDraft": report_prompt(payload)[0],
    }[task]
    try:
        out = llm_chat(model, prompt, json_mode=task == "Classification")
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"llm: {exc}") from exc
    if task == "ReportDraft":
        grounding = report_prompt(payload)[1]
        text, cited = _keep_known_citations(re.sub(r"\*\*|__|^#+\s*", "", out, flags=re.M).strip(), payload)
        stray = _ungrounded_numbers(CITATION.sub("", text), grounding)
        if stray:   # a number neither the findings nor the passages contain = an invented fact -> template instead
            raise ProviderError("טיוטת הדוח כללה נתונים שאינם בממצאים או בקטעי הידע: " + ", ".join(stray[:5]))
        return {"text": text, "citations": cited}   # plain text: the report is not Markdown
    if task == "Classification":
        try:
            res = json.loads(out)
        except json.JSONDecodeError as exc:
            raise ProviderError("ollama returned non-JSON") from exc
        if not isinstance(res, dict) or res.get("label") not in DOC_TYPE_DESCRIPTIONS:
            raise ProviderError(f"label outside the document types: {str(res)[:80]}")
        return res
    return {"text": out}


def _bm25(payload: dict) -> dict:
    from ..knowledge import search
    return {"hits": search(payload["query"], k=payload.get("k", 5), tenant_id=payload.get("tenant_id"))}


def _rules_extract(payload: dict) -> dict:
    from ..intake.pipeline import rules_extract
    return rules_extract(payload)


EXTRACTION_PROMPT = (
    "חלץ מהטקסט הבא (פריט בקשה להיתר מתוך פרוטוקול ועדה או טופס בקשה) JSON בלבד לפי המפתחות: "
    "application_number, building_file_number, address, gush, helka, zone, application_type, description, "
    "applicable_plans, deviations, comments:[{department_he,item_no,text}], decision:{text}. "
    "לכל שדה החזר {\"value\":..., \"page\":מספר עמוד, \"quote\":ציטוט מדויק}. אסור להמציא: שדה שאינו "
    "מופיע בטקסט — null. אל תחלץ שם מבקש, עורך או מספר זהות.\n"
)


def _ollama_extract(model: str, payload: dict) -> dict:
    """LLM extraction via the local language model (Ollama, or the AI PC through the relay). Output is mapped to ApplicationExtraction; the
    pipeline then validates it with Pydantic and drops anything not grounded in the text."""
    text = "\n".join(f"[עמוד {p}]\n{t}" for p, t in payload["pages"])[:12000]
    try:
        raw = json.loads(llm_chat(model, EXTRACTION_PROMPT + text, json_mode=True))
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"llm extraction: {exc}") from exc
    return llm_to_extraction(raw, payload, f"ollama:{model}")


def llm_to_extraction(raw: dict, payload: dict, provider: str) -> dict:
    out: dict = {"pages": [p for p, _ in payload["pages"]], "comments": [], "areas": [], "warnings": []}

    def src(item):
        return {"file": payload["file"], "file_sha256": payload.get("sha"), "page": (item or {}).get("page"),
                "quote": (item or {}).get("quote"), "method": "חילוץ AI — נדרש אימות", "confidence": 0.6,
                "provider": provider}
    for k in ("application_number", "building_file_number", "address", "gush", "helka", "zone", "application_type",
              "description", "applicable_plans", "deviations"):
        item = raw.get(k)
        val = item.get("value") if isinstance(item, dict) else item
        if val not in (None, "", []):
            out[k] = {"value": str(val), "source": src(item if isinstance(item, dict) else None)}
    for c in raw.get("comments") or []:
        if isinstance(c, dict) and c.get("text"):
            out["comments"].append({"department": "other", "department_he": c.get("department_he") or "לא צוין",
                                    "item_no": c.get("item_no"), "text": c["text"], "source": src(c)})
    dec = raw.get("decision")
    if isinstance(dec, dict) and dec.get("text"):
        from ..intake.protocol import classify_decision
        out["decision"] = {"outcome": classify_decision(dec["text"]), "text": dec["text"], "conditions": [],
                           "source": src(dec)}
    return out


def _ollama_dispatch(task: str, cfg: dict, payload: dict) -> dict:
    if task == "Extraction":
        return _ollama_extract(cfg["model_version"], payload)
    return _ollama(task, cfg["model_version"], payload)


IMPLEMENTATIONS: dict[str, Callable[[str, dict, dict], dict]] = {
    "local_rules": lambda task, p, cfg: _rules_extract(p),
    "local_keyword": lambda task, p, cfg: _kw_classify(p),
    "local_template": lambda task, p, cfg: _template_report(p),
    "local_bm25": lambda task, p, cfg: _bm25(p),
    "local_ollama": lambda task, p, cfg: _ollama_dispatch(task, cfg, p),
}


# ----------------------------------------------------------------- gateway

DETERMINISTIC_PROVIDERS = ("local_keyword", "local_template", "local_bm25", "local_rules")


def _prompt_ref(task: str, provider_id: str) -> dict:
    """The prompt id@version a model call used (prompt registry); deterministic providers use no prompt."""
    from .registry import TASK_PROMPT, prompt_version
    pid = TASK_PROMPT.get(task)
    return {"prompt": f"{pid}@{prompt_version(pid)}"} if pid and provider_id not in DETERMINISTIC_PROVIDERS else {}


class AIGateway:
    def __init__(self, policy: dict | None = None, overrides: list[dict] | None = None,
                 implementations: dict | None = None, provider_settings: dict | None = None, bulk: bool = False):
        """provider_settings: the tenant's {provider_id: {enabled, model_version}} (AI settings screen).
        bulk: an import/recheck of many items — providers marked `interactive_only` (the LLM, seconds per
        call) are skipped so the request stays within the server's time limit."""
        self.policy = copy.deepcopy(policy) if policy else yaml.safe_load(
            (settings.knowledge_dir / "ai_policy.yaml").read_text(encoding="utf-8"))
        for pid, ov in (provider_settings or {}).items():
            cfg = self.policy["providers"].get(pid)
            if cfg is None:
                continue
            if "enabled" in ov:
                cfg["enabled"] = bool(ov["enabled"])
            if ov.get("model_version"):
                cfg["model_version"] = str(ov["model_version"])
        self.bulk = bulk
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
        if self.bulk and cfg.get("interactive_only"):
            return "פעולה מרובת פריטים — הספק משמש רק בפעולה בודדת"
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
            tok = _USAGE.set([])
            try:
                out = impl(task, payload, cfg)
            except Exception as exc:  # noqa: BLE001
                trail.append({"provider": pid, "error": str(exc)[:200]})
                first_ok = False
                _USAGE.reset(tok)
                continue
            used = _USAGE.get() or []
            _USAGE.reset(tok)
            ms = int((time.perf_counter() - t0) * 1000)
            res = AIResult(task, "OK" if first_ok else "FALLBACK", pid, cfg.get("model_version"), out, ms,
                           float(cfg.get("cost_per_unit_ils", 0.0)), trail + [{"provider": pid, "used": True, **_prompt_ref(task, pid)}],
                           sum(a for a, _ in used), sum(b for _, b in used))
            log and log(res)
            return res
        res = AIResult(task, "MANUAL_REVIEW", None, None, trail=trail)
        log and log(res)
        return res
