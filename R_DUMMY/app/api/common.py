"""Shared imports, schemas and helpers of the HTTP API (moved verbatim from app/main.py)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__, audit, batch_import, metrics, services
from ..ai.gateway import AIGateway
from ..config import settings
from ..db import SessionLocal, get_session, run_migrations
from ..ingest.files import IntakeError
from ..ingest.pdf import render_page_png
from ..knowledge import load_sources, sources_for_tenant
from ..models import (AIPolicyRow, AuditEvent, CadEntity, CaseFile, CheckRun, CommitteeDecision, ExtractedField,
                     Finding, ImportBatch, InferenceCost, Municipality, PlanningComment, SourceReference,
                     PermitCase, RuleApproval, RuleDefinition, RuleDraft, SourceCrawl, SourceDocument, User)
from ..reports import build_report
from ..rules.engine import (AUTHOR_REVIEW_STATES, CHECK_FIELDS, CONDITION_OPS, LEGAL_LEVEL_RANK, OPERATORS, REPORTS,
                           SEVERITIES, bump_version, validate_rule)
from ..source_monitor import service as source_service
from ..security import PERMISSIONS, ROLES, Principal, current_user, require, login_account
from .. import authority_onboarding as authorities
from .. import users as usermgmt


_OPEN_API = ("/api/health", "/api/auth/", "/api/agent/")   # agent endpoints check their own token


class LoginIn(BaseModel):
    username: str
    password: str


def _typing_worker(interval_s: float = 20.0) -> None:
    """Types imported documents with the local AI and re-runs their request's checks. Durable: whatever an app restart
    interrupted (or an import / a conversion / the reviewer marked) is picked up on the next pass."""
    import time
    from ..db import SessionLocal
    while True:
        try:
            with SessionLocal() as s:
                todo = [(c.id, c.tenant_id) for c in s.scalars(select(PermitCase).where(PermitCase.source == "import"))
                        if services.untyped_files(c)]
                # a prioritized request that is not ready yet gets the local model to itself
                pri = services.priority_case_ids(s)
                for m in s.scalars(select(Municipality)):          # priorities end when the request is ready
                    keep = [cid for cid in (m.settings or {}).get("priority_cases") or []
                            if (c := s.get(PermitCase, cid)) is not None and not services.processing_status(c)["ready"]]
                    if keep != ((m.settings or {}).get("priority_cases") or []):
                        m.settings = {**(m.settings or {}), "priority_cases": keep}
                        s.commit()
                        pri = services.priority_case_ids(s)
                if pri:
                    todo = [x for x in todo if x[0] in pri]
            for cid, tenant in todo:
                with SessionLocal() as s2:
                    c = s2.get(PermitCase, cid)
                    if c is None:
                        continue
                    try:
                        services.classify_case_files(s2, c, "ai-typing", only=services.untyped_files(c), commit_each=True)
                        services.run_checks(s2, c, "ai-typing")
                        s2.commit()
                    except Exception as e:  # noqa: BLE001 — recorded; retried on the next pass
                        s2.rollback()
                        audit.record(s2, tenant, "ai-typing", "file.classify", "permit_case", cid, {"error": str(e)[:300]})
                        s2.commit()
            with SessionLocal() as s3:                         # decided cases: learn once the review is ready
                from .. import learning
                learning.process_pending(s3)
        except Exception:  # noqa: BLE001 — the worker never dies
            pass
        time.sleep(interval_s)


PERMIT_TYPES = {
    "addition_extension": "תוספת בנייה — הרחבת דירה/אגף",
    "addition_balcony": "תוספת מרפסת",
    "addition_sukkah": "מרפסת סוכה",
    "roof_room_addition": "תוספת חדרי גג",
    "new_building": "בנייה חדשה / הריסה ובנייה",
    "permit_changes": "שינויים להיתר קיים",
    "parcel_unification": "איחוד וחלוקת חלקות",
    "other": "אחר",
}
TRACKS = {
    "regular_permit": "בקשה להיתר (מסלול רגיל)",
    "policy_2026_roof_rights": "תכנית לתוספת זכויות — מדיניות 13.1.2026",
}
STAGES = {"permit_request": "בקשה להיתר", "plan_review": "בדיקת תכנית"}
ZONES = {"residential_A": "מגורים א׳", "residential_B": "מגורים ב׳", "residential_B1": "מגורים ב׳1",
         "residential_C": "מגורים ג׳"}
CASE_STATUSES = {"INTAKE": "קליטה", "IN_REVIEW": "בבדיקה", "RETURNED_FOR_COMPLETION": "הוחזר להשלמות",
                 "WAITING_EXTERNAL": "ממתין לגורם חוץ",
                 "REVIEWER_APPROVED": "אושר ע\"י בודק", "CLOSED": "סגור"}


def get_case(s: Session, p: Principal, case_id: str) -> PermitCase:
    c = s.get(PermitCase, case_id)
    if not c or c.tenant_id != p.tenant_id:          # tenant isolation
        raise HTTPException(404, "תיק לא נמצא")
    if c.kind == "design" and c.owner_id != p.id and p.role != "sysadmin":   # a design is its architect's
        raise HTTPException(404, "תיק לא נמצא")
    return c


def case_dict(c: PermitCase, with_files=True) -> dict:
    last = c.runs[-1] if c.runs else None
    d = {"id": c.id, "case_number": c.case_number, "title": c.title, "is_demo": c.is_demo,
         "permit_type": c.permit_type, "track": c.track, "stage": c.stage, "gush": c.gush, "helka": c.helka,
         "address": c.address, "zone": c.zone, "applicable_plans": c.applicable_plans, "declared": c.declared,
         "status": c.status, "assigned_to": c.assigned_to, "sla_due": c.sla_due.isoformat() if c.sla_due else None,
         "locked_version": c.locked_version, "created_at": c.created_at.isoformat(),
         "last_run": None if not last else {"id": last.id, "version": last.version, "summary": last.summary,
                                            "at": last.started_at.isoformat(), "duration_ms": last.duration_ms,
                                            "locked": last.locked},
         "processing": services.processing_status(c), "kind": c.kind or "application", "owner_id": c.owner_id,
         "committee_id": c.committee_id}
    if with_files:
        d["files"] = [{"id": f.id, "filename": f.filename, "doc_type": f.doc_type, "kind": f.kind,
                       "suggested_doc_type": f.suggested_doc_type, "sha256": f.sha256, "size_bytes": f.size_bytes,
                       "version": f.version, "ingest_status": f.ingest_status, "ingest_report": f.ingest_report,
                       "av_status": f.av_status, "signature_status": f.signature_status, "lifecycle": f.lifecycle,
                       "uploaded_at": f.uploaded_at.isoformat()} for f in sorted(c.files, key=lambda f: f.uploaded_at)]
    return d


class AuthorityIn(BaseModel):
    id: str | None = None
    name_he: str


# ------------------------------------------------------------------ cases

class CaseIn(BaseModel):
    case_number: str
    title: str
    permit_type: str
    track: str = "regular_permit"
    stage: str = "permit_request"
    gush: str | None = None
    helka: str | None = None
    address: str | None = None
    zone: str | None = None
    applicable_plans: list[str] = []
    declared: dict = {}


class DeclaredIn(BaseModel):
    declared: dict | None = None
    zone: str | None = None
    applicable_plans: list[str] | None = None
    track: str | None = None
    stage: str | None = None


def _file(s: Session, p: Principal, file_id: str, allow_deleted: bool = False) -> CaseFile:
    f = s.get(CaseFile, file_id)
    if not f or f.tenant_id != p.tenant_id:
        raise HTTPException(404, "קובץ לא נמצא")
    if f.lifecycle == "DELETED" and not allow_deleted:
        raise HTTPException(410, "הקובץ נמחק במחיקה מבוקרת")
    return f


class LifecycleIn(BaseModel):
    state: str      # ACTIVE | ARCHIVED | DELETED
    note: str


# ---- DWFX conversion on the AI PC. The agent (agent/bbp_ai_agent.py) pulls work over outbound HTTPS with the relay
# token, converts on that PC (agent/dwfx_convert.py) and posts the PDF back: drawings are never rendered here.

def _agent(authorization: str = Header("")) -> None:
    import hmac
    token = settings.llm_relay_token
    if not token or not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "agent token required")


def _pending_dwfx(s: Session, file_id: str) -> CaseFile:
    f = s.get(CaseFile, file_id)
    if f is None or f.kind != "dwfx" or f.ingest_status != "PENDING_CONVERSION":
        raise HTTPException(410, "no conversion pending for this file")
    return f


# ---- reading a converted DWFX plan with the local image model (agent/drawing_reader.py on the AI PC)

def _readable_dwfx(s: Session, file_id: str) -> CaseFile:
    f = s.get(CaseFile, file_id)
    if f is None or f.kind != "dwfx" or ((f.ingest_report or {}).get("drawing_read") or {}).get("state") != "reading":
        raise HTTPException(410, "no drawing read pending for this file")
    return f


class RecheckIn(BaseModel):
    case_ids: list[str] | None = None      # None = every case of the tenant


RECHECK_MAX = 500


def _run(s: Session, p: Principal, run_id: str) -> CheckRun:
    r = s.get(CheckRun, run_id)
    if not r or r.tenant_id != p.tenant_id:
        raise HTTPException(404, "הרצה לא נמצאה")
    return r


class AttestIn(BaseModel):
    decision: str
    note: str = ""


class DecisionIn(BaseModel):
    decision: str     # CONFIRMED | OVERRIDDEN
    note: str
    category: str | None = None             # feedback category when overriding (feedback.CATEGORIES)
    corrected_status: str | None = None     # what the result should have been (PASS / FAIL / UNCERTAIN / NA)
    corrected_value: float | None = None


class StatusIn(BaseModel):
    status: str
    note: str = ""
    assigned_to: str | None = None


# ------------------------------------------------------------------ document intake (import)

IMPORT_TTL_HOURS = 24
TOKEN_RE = __import__("re").compile(r"^[0-9]{14}-[0-9a-f]{8}$")
REF_RE = __import__("re").compile(r"^[0-9a-f]{12}$")


def _import_dir(tenant: str, token: str | None = None) -> Path:
    base = settings.storage_dir / "_import" / tenant
    return base / token if token else base


def _cleanup_imports(tenant: str) -> None:
    """Uncommitted staging areas expire after IMPORT_TTL_HOURS."""
    import shutil
    base = _import_dir(tenant)
    if not base.exists():
        return
    cutoff = dt.datetime.now().timestamp() - IMPORT_TTL_HOURS * 3600
    for d in base.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


class ImportDocIn(BaseModel):
    ref: str
    include: bool = True
    doc_type: str | None = None


class ImportAppIn(BaseModel):
    key: str
    include: bool = True
    fields: dict = {}
    documents: list[ImportDocIn] = []


class ImportCommitIn(BaseModel):
    token: str
    applications: list[ImportAppIn]
    run_checks: bool = True


class ApproveIn(BaseModel):
    decision: str = "APPROVED"     # APPROVED | REVOKED
    note: str


# ---- rule authoring (create / update / delete / restore). Approval stays a separate step (rule.approve).

COMPUTED_RULE_KEYS = {"origin", "file_version", "yaml_review_state", "reviewer", "sources_resolved", "deleted"}


class RuleIn(BaseModel):
    rule: dict
    note: str = ""


def _rule_def(s: Session, tenant: str, rule_id: str) -> RuleDefinition | None:
    return s.scalars(select(RuleDefinition).where(RuleDefinition.tenant_id == tenant,
                                                  RuleDefinition.rule_id == rule_id)).first()


def _clean_rule(raw: dict) -> dict:
    """The rule as authored: no computed/display keys, no empty top-level fields."""
    plain = json.loads(json.dumps(raw, default=str, ensure_ascii=False))     # YAML dates -> "YYYY-MM-DD"
    return {k: v for k, v in plain.items() if k not in COMPUTED_RULE_KEYS and v not in (None, "", [], {})}


def _check_rule(s: Session, p: Principal, data: dict) -> None:
    tenant = s.get(Municipality, p.tenant_id)
    errs = validate_rule(data, allow_demo=bool(tenant and tenant.is_demo))
    if errs:
        raise HTTPException(422, "; ".join(errs))


def _note(body_note: str) -> str:
    if len(body_note.strip()) < 3:
        raise HTTPException(422, "נדרש נימוק לשינוי (נרשם ביומן הביקורת)")
    return body_note.strip()


# ------------------------------------------------------------------ source monitor (crawl official rule sources)

def _src_doc(s: Session, p: Principal, doc_id: int) -> SourceDocument:
    d = s.get(SourceDocument, doc_id)
    if not d or d.tenant_id != p.tenant_id:
        raise HTTPException(404, "מסמך מקור לא נמצא")
    return d


def _src_doc_dict(d: SourceDocument, drafts: dict) -> dict:
    return {"id": d.id, "url": d.url, "kind": d.kind, "source_id": d.source_id, "title": d.title,
            "discovered_from": d.discovered_from, "first_seen": d.first_seen.isoformat(),
            "last_checked": d.last_checked.isoformat() if d.last_checked else None,
            "fetch_status": d.fetch_status, "http_status": d.http_status, "message": d.message,
            "change_state": d.change_state, "changed_at": d.changed_at.isoformat() if d.changed_at else None,
            "acknowledged": d.acknowledged, "sha256": d.sha256, "content_type": d.content_type, "size": d.size,
            "page_count": d.page_count, "has_file": bool(d.storage_path), "links": len(d.links or []),
            "drafts": drafts.get(d.id, {})}


def _crawl_dict(c: SourceCrawl | None) -> dict | None:
    if not c:
        return None
    return {"id": c.id, "status": c.status, "triggered_by": c.triggered_by, "started_at": c.started_at.isoformat(),
            "finished_at": c.finished_at.isoformat() if c.finished_at else None, "summary": c.summary or {},
            "resumable": c.status in ("failed", "partial") and c.checkpoint is not None,
            "remaining": len((c.checkpoint or {}).get("queue") or []) if c.checkpoint else 0}


class ScheduleIn(BaseModel):
    schedule: str


class DraftDecisionIn(BaseModel):
    status: str            # open | for_authoring | dismissed
    note: str | None = None


LEVEL_BY_CATEGORY = {"LAW": "STATUTE", "REGULATION": "REGULATION", "STATUTORY_PLAN": "STATUTORY_PLAN",
                     "LOCAL_POLICY": "MUNICIPAL_POLICY", "GOV_GUIDANCE": "REGULATION"}


# ------------------------------------------------------------------ AI settings

def _gateway_for(s: Session, tenant: str) -> AIGateway:
    return services.gateway_for(s, tenant)


def _http_json(url: str, timeout: float):
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


class ProviderIn(BaseModel):
    enabled: bool | None = None
    model_version: str | None = None


class AITestIn(BaseModel):
    task: str = "Classification"


AI_TEST_PAYLOADS = {
    "Classification": {"filename": "test.pdf", "text": "מפת מדידה מצבית ערוכה וחתומה על ידי מודד מוסמך, גוש 6195 חלקה 12"},
    "ReportDraft": {"findings": [
        {"status": "FAIL", "title_he": "נסיגת חדר גג מחזית ≥ 2.5 מ׳", "explanation_he": "נמדד: 2.49 מ׳; נדרש ≥ 2.50 מ׳."},
        {"status": "PASS", "title_he": "מספר קומות לפי אזור", "explanation_he": "נתון בתיק: 4.00 קומות; נדרש ≤ 5.00."}]},
}


class PolicyIn(BaseModel):
    task: str
    data_class: str
    mode: str
    providers: list[str]


# ------------------------------------------------------------------ verified regulatory scope and parcel plan discovery
from .. import regulatory as reg  # noqa: E402
from .. import plan_discovery  # noqa: E402
from ..models import RegulatoryEntry  # noqa: E402


# ------------------------------------------------------------------ user management (the authority's administrator)

class UserIn(BaseModel):
    username: str
    display_name: str
    role: str
    password: str


class MemberIn(BaseModel):
    username: str
    role: str


class UserPatch(BaseModel):
    role: str | None = None
    display_name: str | None = None


class ActiveIn(BaseModel):
    active: bool


class ResetIn(BaseModel):
    password: str
    username: str | None = None          # only when the user has no login yet


class PasswordIn(BaseModel):
    current: str
    new: str


def _users_call(s: Session, fn, *args):
    try:
        out = fn(s, *args)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    except (ValueError, PermissionError) as e:
        raise HTTPException(422, str(e)) from e
    s.commit()
    return out


# ------------------------------------------------------------------ national register of planning committees

class CommitteePatch(BaseModel):
    committee_code: str | None = None
    engineering_url: str | None = None
    request_search_url: str | None = None
    vendor: str | None = None


def _platform_admin(account: User = Depends(login_account)) -> User:
    if not authorities.can_create(account):
        raise HTTPException(403, "רק מנהל פלטפורמה מעדכן את מאגר הוועדות")
    return account


class ProbeIn(BaseModel):
    ids: list[str] | None = None          # none: every committee


__all__ = ['annotations', 'dt', 'json', 'Path', 'yaml', 'Depends', 'FastAPI', 'File', 'Form', 'Header', 'HTTPException', 'Request', 'UploadFile', 'CORSMiddleware', 'FileResponse', 'JSONResponse', 'Response', 'BaseModel', 'shapely_wkt', 'mapping', 'func', 'select', 'Session', '__version__', 'audit', 'batch_import', 'metrics', 'services', 'AIGateway', 'settings', 'SessionLocal', 'get_session', 'run_migrations', 'IntakeError', 'render_page_png', 'load_sources', 'sources_for_tenant', 'AIPolicyRow', 'AuditEvent', 'CadEntity', 'CaseFile', 'CheckRun', 'CommitteeDecision', 'ExtractedField', 'Finding', 'ImportBatch', 'InferenceCost', 'Municipality', 'PlanningComment', 'SourceReference', 'PermitCase', 'RuleApproval', 'RuleDefinition', 'RuleDraft', 'SourceCrawl', 'SourceDocument', 'User', 'build_report', 'AUTHOR_REVIEW_STATES', 'CHECK_FIELDS', 'CONDITION_OPS', 'LEGAL_LEVEL_RANK', 'OPERATORS', 'REPORTS', 'SEVERITIES', 'bump_version', 'validate_rule', 'source_service', 'PERMISSIONS', 'ROLES', 'Principal', 'current_user', 'require', 'login_account', 'authorities', 'usermgmt', '_OPEN_API', 'LoginIn', '_typing_worker', 'PERMIT_TYPES', 'TRACKS', 'STAGES', 'ZONES', 'CASE_STATUSES', 'get_case', 'case_dict', 'AuthorityIn', 'CaseIn', 'DeclaredIn', '_file', 'LifecycleIn', '_agent', '_pending_dwfx', '_readable_dwfx', 'RecheckIn', 'RECHECK_MAX', '_run', 'AttestIn', 'DecisionIn', 'StatusIn', 'IMPORT_TTL_HOURS', 'TOKEN_RE', 'REF_RE', '_import_dir', '_cleanup_imports', 'ImportDocIn', 'ImportAppIn', 'ImportCommitIn', 'ApproveIn', 'COMPUTED_RULE_KEYS', 'RuleIn', '_rule_def', '_clean_rule', '_check_rule', '_note', '_src_doc', '_src_doc_dict', '_crawl_dict', 'ScheduleIn', 'DraftDecisionIn', 'LEVEL_BY_CATEGORY', '_gateway_for', '_http_json', 'ProviderIn', 'AITestIn', 'AI_TEST_PAYLOADS', 'PolicyIn', 'reg', 'plan_discovery', 'RegulatoryEntry', 'UserIn', 'MemberIn', 'UserPatch', 'ActiveIn', 'ResetIn', 'PasswordIn', '_users_call', 'CommitteePatch', '_platform_admin', 'ProbeIn']
