"""The case summary draws on the knowledge passages of the case's own municipality, and cites them."""
from types import SimpleNamespace

import pytest

from app import knowledge as K, services
from app.ai import gateway as G


def test_search_is_scoped_to_the_municipality():
    where = lambda h: K.load_sources()[h["source_id"]].get("jurisdiction")  # noqa: E731
    ha = K.search("בריכת שחייה גדר תוספת בנייה חדרי גג", k=20, tenant_id="hof-ashkelon")
    assert ha and {where(h) for h in ha} <= {"hof-ashkelon", "national"}              # never Bnei Brak's
    bb = K.search("בריכת שחייה גדר תוספת בנייה חדרי גג", k=20, tenant_id="bnei-brak")
    assert bb and "hof-ashkelon" not in {where(h) for h in bb}                         # national ones are shared
    assert "hof-ashkelon" in {where(h) for h in K.search("בריכת שחייה גדר", k=10)}     # no tenant: no filter


def _result(status, title, expl):
    return SimpleNamespace(status=status, as_dict=lambda: {"status": status, "title_he": title, "explanation_he": expl})


def test_case_passages_follow_open_findings():
    case = SimpleNamespace(tenant_id="hof-ashkelon")
    results = [_result("PASS", "גדר בריכה", "עומד"),
               _result("UNCERTAIN", "גובה מחסן ושטחו", "לא נמצא שטח המחסן ליחידת דיור"),
               _result("FAIL", "בריכת שחייה — גדר ומרחק", "הגדר סביב הבריכה נמוכה מהנדרש")]
    ids = [p["id"] for p in services.case_passages(case, results)]
    assert ids[0].startswith("P-HA-POOL") and "P-HA-633-5" in ids                  # FAIL first, PASS ignored
    bb = services.case_passages(SimpleNamespace(tenant_id="bnei-brak"), results[2:])
    assert not any(K.load_sources()[p["source_id"]].get("jurisdiction") == "hof-ashkelon" for p in bb)


PASSAGES = [{"id": "P-HA-POOL-1", "source_title_he": "מדיניות בריכות", "page": 1, "section": "סעיפים 1–6",
             "text_he": "גדר בגובה 1.1 מ' לפחות במרחק 1 מ' משפת הבריכה."}]
FINDINGS = [{"status": "FAIL", "title_he": "גדר בריכה", "explanation_he": "נמדד 0.9 מ'"}]


@pytest.mark.parametrize("answer,ok,cited", [
    ("נבדק 1 כלל. הגדר לא עומדת: לפי המדיניות נדרשת גדר בגובה 1.1 מ' [P-HA-POOL-1]. הסיכום הוא המלצה בלבד.", True, ["P-HA-POOL-1"]),
    ("נבדק 1 כלל. ראו גם [P-HA-XXX-9] והנחיה אחרת.", True, []),                   # unknown id: removed, not shown
    ("נבדק 1 כלל. לפי המדיניות (P-HA-POOL-1) נדרשת גדר בגובה 1.1 מ'.", True, ["P-HA-POOL-1"]),  # round brackets too
    ("נבדק 1 כלל. נדרשת גדר בגובה 1.5 מ' [P-HA-POOL-1].", False, None),          # 1.5 is in no finding or passage
])
def test_summary_citations_and_grounding(monkeypatch, answer, ok, cited):
    monkeypatch.setattr(G, "llm_chat", lambda model, prompt, json_mode=False: answer)
    payload = {"findings": FINDINGS, "passages": PASSAGES}
    if not ok:
        with pytest.raises(G.ProviderError):
            G._ollama("ReportDraft", "m", payload)
        return
    out = G._ollama("ReportDraft", "m", payload)
    assert out["citations"] == cited and "P-HA-XXX-9" not in out["text"]


def test_prompt_without_passages_is_unchanged():
    prompt, grounding = G.report_prompt({"findings": FINDINGS})
    assert "קטעי ידע" not in prompt and grounding in prompt


def test_template_lists_passages():
    out = G._template_report({"findings": FINDINGS, "passages": PASSAGES})
    assert "[P-HA-POOL-1]" in out["text"] and out["citations"] == ["P-HA-POOL-1"]
