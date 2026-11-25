"""Every finding is one of: missing, conflict, invalid (not met), open (undecided), OK or not applicable."""
from types import SimpleNamespace

from app.services import issue_type


def rule(kind, **raw):
    return SimpleNamespace(check={"kind": kind}, raw=raw)


def res(rule_id, computed, status=None, flags=()):
    return SimpleNamespace(rule_id=rule_id, computed_result=computed, status=status or computed, flags=list(flags))


def test_issue_types():
    assert issue_type(rule("doc_required"), res("QA-REQ-SURVEY", "FAIL")) == "MISSING"
    assert issue_type(rule("condition"), res("HA-633-COND-HFC", "FAIL", "UNCERTAIN")) == "MISSING"
    assert issue_type(rule("compare"), res("HA-633-HEIGHT", "FAIL")) == "INVALID"
    assert issue_type(rule("compare"), res("HA-633-HEIGHT", "UNCERTAIN", flags=["INCOMPLETE"])) == "OPEN"
    assert issue_type(rule("consistency"), res("QA-AREA-CAD-VS-TABLE", "FAIL")) == "CONFLICT"
    assert issue_type(rule("list_empty"), res("QA-APPROVAL-PARCEL-MISMATCH", "FAIL")) == "CONFLICT"
    assert issue_type(rule("list_empty"), res("QA-LICENCE-EXPIRED", "FAIL")) == "INVALID"
    assert issue_type(rule("list_empty"), res("QA-DOC-PLACEHOLDER", "FAIL")) == "MISSING"
    assert issue_type(None, res("CONFLICT:declared.units", "UNCERTAIN", "UNCERTAIN", ["SOURCE_CONFLICT"])) == "CONFLICT"
    assert issue_type(rule("qualitative", issue_type="CONFLICT"), res("X", "FAIL")) == "CONFLICT"
    assert issue_type(rule("compare"), res("X", "PASS")) == "OK" and issue_type(rule("compare"), res("X", "NA")) == "NA"
