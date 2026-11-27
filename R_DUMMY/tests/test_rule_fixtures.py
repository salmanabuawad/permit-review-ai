"""Every rule's own fixtures (`tests:` in the catalogue) pass, and an edit that breaks them cannot be saved."""
from pathlib import Path

import pytest

from app.config import settings
from app.rules.engine import load_rules, run_rule_tests, validate_rule

RULES = load_rules(sorted((settings.knowledge_dir / "rules").glob("*.yaml")))


@pytest.mark.parametrize("rule", [r for r in RULES if r.raw.get("tests")], ids=lambda r: r.id)
def test_catalogue_rule_fixtures(rule):
    assert run_rule_tests(rule.raw) == []


def test_some_rules_carry_fixtures():
    assert sum(1 for r in RULES if r.raw.get("tests")) >= 5


def test_edit_that_breaks_fixtures_is_refused():
    rule = next(r for r in RULES if r.id == "HA-633-UNITS-CELL")
    as_edited = {**rule.raw, "review_state": "SOURCE_VERIFIED"}       # what the rules screen submits
    assert validate_rule(as_edited) == []
    errs = validate_rule({**as_edited, "check": {**as_edited["check"], "threshold": 90}})
    assert any("צפוי PASS" in e for e in errs)
    assert validate_rule({**as_edited, "tests": [{"facts": {}, "expect": "MAYBE"}]})
