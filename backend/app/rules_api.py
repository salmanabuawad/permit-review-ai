"""Rules API — create, replace, patch and delete rules over HTTP (curl-friendly, JSON or YAML).

Rules in knowledge/rules/*.yaml are the baseline. A rule written through this API is stored per tenant in
`managed_rules` and overrides the file rule with the same id; DELETE hides a rule (file or API) without
losing it, and every change is kept in `rule_revisions` and the audit log.

Safety: the API can never mark a rule professionally approved — that only happens through
POST /api/rules/{id}/approval by a city engineer / department manager, and every change creates a new
version, so an earlier approval no longer applies to the changed rule.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .db import get_session
from .knowledge import load_sources
from .models import ManagedRule, Municipality, RuleRevision
from .rules.engine import LEGAL_LEVEL_RANK, Rule, evaluate_rule
from .security import Principal, require

router = APIRouter()

MAX_BODY = 1_000_000
API_REVIEW_STATES = {"DRAFT", "SOURCE_MISSING", "SOURCE_LOCATED", "SOURCE_VERIFIED", "DESIGN_ASSUMPTION", "RETIRED"}
OPERATORS = {">=", "<=", ">", "<", "=="}
COND_OPS = {"eq", "ne", "in", "not_in", "true", "false", "contains", "exists"}
INTERNAL_KEYS = {"managed", "yaml_review_state", "reviewer", "sources_resolved", "approval"}


# ------------------------------------------------------------------ validation

class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Condition(_Open):
    fact: str = Field(min_length=1)
    op: Any = "eq"
    value: Any = None
    label_he: str | None = None

    @field_validator("op")
    @classmethod
    def _op(cls, v):
        if v is True or v is False:                       # YAML 1.1 bare true/false
            v = "true" if v else "false"
        if v not in COND_OPS:
            raise ValueError(f"op must be one of {sorted(COND_OPS)}")
        return v


class Applicability(_Open):
    all: list[Condition] | None = None
    any: list[Condition] | None = None


class Citation(_Open):
    source_id: str
    section: str | None = None
    page: int | str | None = None
    quote_he: str | None = None

    @field_validator("source_id")
    @classmethod
    def _registered(cls, v):
        if v not in load_sources():
            raise ValueError(f"source_id '{v}' is not in the source register (knowledge/sources.yaml)")
        return v


class Check(_Open):
    kind: Literal["compare", "doc_required", "cad_roles", "any_present", "declared_bool", "consistency",
                  "qualitative", "condition"]

    @model_validator(mode="after")
    def _per_kind(self):
        d = self.model_dump()
        need = {"compare": ["operand", "operator"], "doc_required": ["doc_type"], "any_present": ["items"],
                "declared_bool": ["fact"], "consistency": ["operand_a", "operand_b", "max_rel_diff"]}.get(self.kind, [])
        missing = [k for k in need if d.get(k) in (None, "", [])]
        if missing:
            raise ValueError(f"check.kind={self.kind} requires: {', '.join(missing)}")
        if self.kind == "compare":
            if d["operator"] not in OPERATORS:
                raise ValueError(f"check.operator must be one of {sorted(OPERATORS)}")
            if "threshold" in d and d["threshold"] is not None and not isinstance(d["threshold"], (int, float)):
                raise ValueError("check.threshold must be a number (or null when the source value is missing)")
            tb = d.get("threshold_by")
            if tb is not None and (not isinstance(tb, dict) or not tb.get("fact") or not isinstance(tb.get("map"), dict)):
                raise ValueError("check.threshold_by needs 'fact' and a 'map' of value → threshold")
        if self.kind == "consistency" and not isinstance(d["max_rel_diff"], (int, float)):
            raise ValueError("check.max_rel_diff must be a number (e.g. 0.05 for 5%)")
        if self.kind == "any_present" and not all(isinstance(i, dict) and (i.get("doc_type") or i.get("cad_role"))
                                                  for i in d["items"]):
            raise ValueError("check.items: each item needs doc_type or cad_role")
        return self


class RuleBody(_Open):
    id: str
    version: str | None = None
    title_he: str = Field(min_length=3)
    legal_level: str
    report: Literal["completeness", "rights", "reviewer"]
    severity: Literal["high", "medium", "low"] = "medium"
    review_state: str = "DRAFT"
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    permit_types: list[str] = []
    stages: list[str] = []
    applicability: Applicability | None = None
    check: Check
    sources: list[Citation] = []

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.\-]{2,79}", v):
            raise ValueError("id: 3–80 chars, upper-case letters, digits, '-', '_' or '.' (e.g. BB-SG-30-6)")
        return v

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, v):
        return None if v is None else str(v)

    @field_validator("legal_level")
    @classmethod
    def _level(cls, v):
        if v not in LEGAL_LEVEL_RANK:
            raise ValueError(f"legal_level must be one of {list(LEGAL_LEVEL_RANK)}")
        return v


def _errors(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc']) or 'body'}: {err['msg']}" for err in e.errors()]


def validate_rule(raw: Any, tenant_is_demo: bool, permit_types: set[str]) -> dict:
    """Validate a rule body; returns the cleaned dict (as it will be stored) or raises HTTP 422."""
    if not isinstance(raw, dict):
        raise HTTPException(422, {"errors": ["body must be one rule object (JSON or YAML)"]})
    raw = {k: v for k, v in raw.items() if k not in INTERNAL_KEYS}
    try:
        body = RuleBody.model_validate(raw)
    except ValidationError as e:
        raise HTTPException(422, {"errors": _errors(e)}) from e
    errs = []
    if body.review_state == "PROFESSIONALLY_APPROVED":
        errs.append("review_state: PROFESSIONALLY_APPROVED cannot be set through the API — "
                    "use POST /api/rules/{id}/approval (city engineer / department manager)")
    elif body.review_state == "DEMO_FIXTURE" or body.legal_level == "DEMO":
        if not tenant_is_demo:
            errs.append("DEMO rules are allowed only in the demo tenant")
    elif body.review_state not in API_REVIEW_STATES:
        errs.append(f"review_state must be one of {sorted(API_REVIEW_STATES)}")
    if body.review_state in ("SOURCE_LOCATED", "SOURCE_VERIFIED") and not body.sources:
        errs.append(f"review_state {body.review_state} requires at least one entry in sources")
    unknown_pt = [p for p in body.permit_types if p not in permit_types]
    if unknown_pt:
        errs.append(f"permit_types: unknown {unknown_pt}; allowed {sorted(permit_types)}")
    if body.valid_from and body.valid_to and body.valid_to < body.valid_from:
        errs.append("valid_to is before valid_from")
    if errs:
        raise HTTPException(422, {"errors": errs})
    out = json.loads(body.model_dump_json(exclude_none=True))
    for k in ("valid_from", "valid_to"):
        if k in out:
            out[k] = str(out[k])
    # smoke-run the engine on empty facts so a structurally broken rule is rejected now, not during a check
    probe = {k: v for k, v in out.items() if k not in ("permit_types", "stages", "applicability", "spatial_scope")}
    try:
        evaluate_rule(Rule(probe), {"case": {}}, load_sources(), tenant_is_demo=True)
    except Exception as e:                                       # noqa: BLE001
        raise HTTPException(422, {"errors": [f"the rule engine cannot evaluate this rule: {type(e).__name__}: {e}"]}) from e
    return out


# ------------------------------------------------------------------ merge with the YAML baseline

def apply_managed(s: Session, tenant_id: str, rules: list[Rule]) -> list[Rule]:
    """Overlay this tenant's API-managed rules on the file rules (replace by id, append new, hide deleted)."""
    managed = {m.rule_id: m for m in s.scalars(select(ManagedRule).where(ManagedRule.tenant_id == tenant_id))}
    if not managed:
        return rules
    out = []
    for r in rules:
        m = managed.pop(r.id, None)
        if m is None:
            out.append(r)
        elif m.status == "active":
            out.append(_managed_rule(m))
    out += [_managed_rule(m) for m in managed.values() if m.status == "active"]
    return out


def _managed_rule(m: ManagedRule) -> Rule:
    raw = dict(m.body)
    raw["version"] = m.version
    raw["managed"] = {"origin": "api" if m.base == "api" else "api_override", "updated_by": m.updated_by,
                      "updated_at": m.updated_at.isoformat()}
    return Rule(raw)


def _bump(v: str) -> str:
    parts = v.split(".")
    if parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return v + ".1"


# ------------------------------------------------------------------ helpers

def _tenant_ctx(s: Session, p: Principal) -> tuple[bool, set[str]]:
    from .main import PERMIT_TYPES                                 # late import: main imports this module
    t = s.get(Municipality, p.tenant_id)
    return bool(t and t.is_demo), set(PERMIT_TYPES)


async def _read_body(request: Request) -> Any:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "body larger than 1 MB")
    if not raw.strip():
        raise HTTPException(422, {"errors": ["empty body"]})
    ct = request.headers.get("content-type", "")
    try:
        if "yaml" in ct or "x-yaml" in ct:
            return yaml.safe_load(raw.decode("utf-8"))
        if "json" in ct:
            return json.loads(raw)
        try:                                                      # curl -d without a content type
            return json.loads(raw)
        except json.JSONDecodeError:
            return yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(422, {"errors": [f"cannot parse body as JSON or YAML: {e}"]}) from e


def _current(s: Session, p: Principal) -> dict[str, Rule]:
    from .services import rules_for_tenant
    return {r.id: r for r in rules_for_tenant(s, p.tenant_id)}


def _file_ids(p: Principal) -> set[str]:
    from .services import file_rules_for_tenant
    return {r.id for r in file_rules_for_tenant(p.tenant_id)}


def _plain(r: Rule) -> dict:
    """The rule as stored (its own review_state), with any approval reported separately — safe to edit and PUT back."""
    raw = {k: v for k, v in r.raw.items() if k not in ("sources_resolved", "yaml_review_state", "reviewer")}
    raw["review_state"] = r.raw.get("yaml_review_state", r.raw.get("review_state"))
    if r.raw.get("review_state") == "PROFESSIONALLY_APPROVED":
        raw["approval"] = {"state": "PROFESSIONALLY_APPROVED", "approved_by": r.raw.get("reviewer"),
                           "version": str(r.raw.get("version"))}
    return raw


def _out(r: Rule, fmt: str) -> Response:
    raw = _plain(r)
    if fmt == "yaml":
        return Response(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=120),
                        media_type="application/yaml; charset=utf-8")
    return Response(json.dumps(raw, ensure_ascii=False, default=str), media_type="application/json")


def _save(s: Session, p: Principal, rule_id: str, body: dict, action: str, note: str | None,
          prev_version: str | None) -> ManagedRule:
    m = s.scalars(select(ManagedRule).where(ManagedRule.tenant_id == p.tenant_id, ManagedRule.rule_id == rule_id)).first()
    asked = body.get("version")
    if prev_version is None:
        version = asked or "1"
    else:
        version = asked if asked and asked != prev_version else _bump(prev_version)
    body = {**body, "version": version}
    now = dt.datetime.now(dt.timezone.utc)
    if m is None:
        m = ManagedRule(tenant_id=p.tenant_id, rule_id=rule_id, created_by=p.id,
                        base="yaml" if rule_id in _file_ids(p) else "api")
        s.add(m)
    m.version, m.status, m.body, m.updated_by, m.updated_at = version, "active", body, p.id, now
    s.add(RuleRevision(tenant_id=p.tenant_id, rule_id=rule_id, version=version, action=action, body=body,
                       note=note, actor=p.id))
    audit.record(s, p.tenant_id, p.id, f"rule.api.{action}", "rule", rule_id,
                 {"version": version, "previous_version": prev_version, "note": note})
    s.flush()
    return m


# ------------------------------------------------------------------ endpoints

@router.get("/api/rules/export")
def export_rules(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """All rules in effect for this tenant, as one YAML file (same shape as knowledge/rules/*.yaml)."""
    rules = [_plain(r) for r in _current(s, p).values()]
    text = yaml.safe_dump({"jurisdiction": p.tenant_id, "rules": rules}, allow_unicode=True, sort_keys=False, width=120)
    return Response(text, media_type="application/yaml; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="rules-{p.tenant_id}.yaml"'})


@router.get("/api/rules/{rule_id}")
def get_rule(rule_id: str, format: str = "json", p: Principal = Depends(require("case.read")),
             s: Session = Depends(get_session)):
    r = _current(s, p).get(rule_id)
    if not r:
        raise HTTPException(404, "rule not found")
    return _out(r, format)


@router.get("/api/rules/{rule_id}/history")
def rule_history(rule_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    rows = s.scalars(select(RuleRevision).where(RuleRevision.tenant_id == p.tenant_id, RuleRevision.rule_id == rule_id)
                     .order_by(RuleRevision.id))
    return [{"version": r.version, "action": r.action, "actor": r.actor, "at": r.at.isoformat(), "note": r.note,
             "body": r.body} for r in rows]


@router.post("/api/rules", status_code=201)
async def create_rule(request: Request, note: str | None = None, p: Principal = Depends(require("rule.manage")),
                      s: Session = Depends(get_session)):
    """Create one rule, or several at once with a body of the form {rules: [...]} (all-or-nothing)."""
    data = await _read_body(request)
    items = data["rules"] if isinstance(data, dict) and isinstance(data.get("rules"), list) else [data]
    demo, pts = _tenant_ctx(s, p)
    current = _current(s, p)
    deleted = {m.rule_id: m for m in s.scalars(select(ManagedRule).where(
        ManagedRule.tenant_id == p.tenant_id, ManagedRule.status == "deleted"))}
    cleaned, errors, seen = [], [], set()
    for i, raw in enumerate(items):
        try:
            body = validate_rule(raw, demo, pts)
        except HTTPException as e:
            errors += [f"rules[{i}] {x}" if len(items) > 1 else x for x in e.detail["errors"]]
            continue
        if body["id"] in current or body["id"] in seen:
            errors.append(f"{body['id']}: a rule with this id already exists — use PUT or PATCH /api/rules/{body['id']}")
            continue
        seen.add(body["id"])
        cleaned.append(body)
    if errors:
        raise HTTPException(409 if all("already exists" in x for x in errors) else 422, {"errors": errors})
    out = []
    for body in cleaned:
        prev = deleted.get(body["id"])
        m = _save(s, p, body["id"], body, "restore" if prev else "create", note, prev.version if prev else None)
        out.append({"id": m.rule_id, "version": m.version})
    s.commit()
    return out[0] if len(items) == 1 and not (isinstance(data, dict) and "rules" in data) else {"created": out}


@router.put("/api/rules/{rule_id}")
async def replace_rule(rule_id: str, request: Request, note: str | None = None,
                       p: Principal = Depends(require("rule.manage")), s: Session = Depends(get_session)):
    data = await _read_body(request)
    if isinstance(data, dict):
        if data.get("id") not in (None, rule_id):
            raise HTTPException(422, {"errors": [f"body id '{data.get('id')}' does not match the URL id '{rule_id}'"]})
        data = {**data, "id": rule_id}
    return _update(s, p, rule_id, data, note)


@router.patch("/api/rules/{rule_id}")
async def patch_rule(rule_id: str, request: Request, note: str | None = None,
                     p: Principal = Depends(require("rule.manage")), s: Session = Depends(get_session)):
    """Change some top-level fields (e.g. title_he, check, sources); fields not sent stay as they are."""
    data = await _read_body(request)
    if not isinstance(data, dict):
        raise HTTPException(422, {"errors": ["PATCH body must be an object of fields to change"]})
    if data.get("id") not in (None, rule_id):
        raise HTTPException(422, {"errors": ["the id of a rule cannot be changed"]})
    r = _current(s, p).get(rule_id)
    if not r:
        raise HTTPException(404, "rule not found")
    base = {k: v for k, v in r.raw.items() if k not in INTERNAL_KEYS}
    base["review_state"] = r.raw.get("yaml_review_state", base.get("review_state"))   # never inherit the approval
    merged = {**base, **{k: v for k, v in data.items() if v is not None}}
    for k, v in data.items():
        if v is None:
            merged.pop(k, None)                                     # explicit null removes an optional field
    if "version" not in data:
        merged.pop("version", None)
    return _update(s, p, rule_id, merged, note)


def _update(s: Session, p: Principal, rule_id: str, data: Any, note: str | None) -> dict:
    r = _current(s, p).get(rule_id)
    if not r:
        raise HTTPException(404, "rule not found — create it with POST /api/rules")
    demo, pts = _tenant_ctx(s, p)
    body = validate_rule(data, demo, pts)
    prev = str(r.raw.get("version", "0"))
    if body.get("version") == prev:
        body.pop("version")
    m = _save(s, p, rule_id, body, "update", note, prev)
    s.commit()
    return {"id": m.rule_id, "version": m.version, "previous_version": prev,
            "note_he": "גרסה חדשה — אישור קודם אינו חל עליה; נדרש אישור מחדש כדי שהכלל יהיה מחייב"}


@router.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: str, note: str | None = None, p: Principal = Depends(require("rule.manage")),
                s: Session = Depends(get_session)):
    """Hide a rule from all future checks. Past runs keep their findings; the rule can be re-created with POST."""
    r = _current(s, p).get(rule_id)
    if not r:
        raise HTTPException(404, "rule not found")
    body = {k: v for k, v in r.raw.items() if k not in INTERNAL_KEYS}
    m = _save(s, p, rule_id, body, "delete", note, None)
    m.version = str(r.raw.get("version", "0"))
    m.status = "deleted"
    s.commit()
    return {"id": rule_id, "deleted": True, "version": m.version}
