"""ORM model for the POC.

This is the operational subset of the full ERD in docs/03_srs_architecture.md.
The production PostgreSQL/PostGIS DDL lives in db/postgres_schema.sql; here
geometry is stored as WKT text so the POC runs on SQLite.
Every row that holds municipal data carries tenant_id (tenant isolation).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC in Python (SQLite drops tzinfo; PostgreSQL keeps it)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Municipality(Base):
    __tablename__ = "municipalities"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # e.g. "bnei-brak", "demo"
    name_he: Mapped[str] = mapped_column(String(200))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"))
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40))   # see security.ROLES
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)


class PermitCase(Base):
    __tablename__ = "permit_cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    case_number: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # permit_type: addition_extension | addition_sukkah | addition_balcony | roof_room_addition
    permit_type: Mapped[str] = mapped_column(String(60))
    # licensing track; "policy_2026_roof_rights" = plan to add rights under the 13.1.2026 policy
    track: Mapped[str] = mapped_column(String(60), default="regular_permit")
    stage: Mapped[str] = mapped_column(String(40), default="permit_request")
    gush: Mapped[str | None] = mapped_column(String(20))
    helka: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(300))
    zone: Mapped[str | None] = mapped_column(String(40))         # e.g. "residential_B"
    applicable_plans: Mapped[list] = mapped_column(JSON, default=list)
    declared: Mapped[dict] = mapped_column(JSON, default=dict)    # applicant-declared facts (forms)
    status: Mapped[str] = mapped_column(String(40), default="INTAKE")
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    sla_due: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    locked_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now, onupdate=_now)

    files: Mapped[list["CaseFile"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    runs: Mapped[list["CheckRun"]] = relationship(back_populates="case", cascade="all, delete-orphan",
                                                  order_by="CheckRun.version")


class CaseFile(Base):
    """One uploaded file version. Re-uploading the same content is detected by sha256."""
    __tablename__ = "case_files"
    __table_args__ = (UniqueConstraint("case_id", "sha256", name="uq_case_file_hash"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("permit_cases.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(60))           # declared by uploader
    suggested_doc_type: Mapped[str | None] = mapped_column(String(60))
    filename: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(10))                # pdf | dxf | dwg | xlsx
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(String(32))
    storage_path: Mapped[str] = mapped_column(String(600))
    ingest_status: Mapped[str] = mapped_column(String(40), default="PENDING")  # OK | NEEDS_OCR | NEEDS_CONVERSION | ERROR
    ingest_report: Mapped[dict] = mapped_column(JSON, default=dict)
    av_status: Mapped[str] = mapped_column(String(30), default="NOT_SCANNED")   # NOT_SCANNED | CLEAN | INFECTED
    signature_status: Mapped[str] = mapped_column(String(30), default="NOT_CHECKED")
    uploaded_by: Mapped[str | None] = mapped_column(String(40))
    uploaded_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)

    case: Mapped[PermitCase] = relationship(back_populates="files")


class CadEntity(Base):
    __tablename__ = "cad_entities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("case_files.id"), index=True)
    layer: Mapped[str] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(60))         # semantic role from layer convention
    dxftype: Mapped[str] = mapped_column(String(30))
    wkt_m: Mapped[str] = mapped_column(Text)                     # geometry in metres (local drawing CRS)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_handle: Mapped[str | None] = mapped_column(String(40))
    via_block: Mapped[str | None] = mapped_column(String(200))


class CheckRun(Base):
    """One execution of the check pipeline over a case — versioned for re-run/provenance."""
    __tablename__ = "check_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("permit_cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    ruleset_hash: Mapped[str] = mapped_column(String(64))
    input_hashes: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    measurements: Mapped[dict] = mapped_column(JSON, default=dict)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    case: Mapped[PermitCase] = relationship(back_populates="runs")
    findings: Mapped[list["Finding"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("check_runs.id"), index=True)
    report: Mapped[str] = mapped_column(String(30))              # completeness | rights | reviewer
    rule_id: Mapped[str] = mapped_column(String(80))
    rule_version: Mapped[str] = mapped_column(String(20))
    computed_result: Mapped[str] = mapped_column(String(12))     # PASS | FAIL | UNCERTAIN | NA
    status: Mapped[str] = mapped_column(String(12))              # after approval-state gating
    severity: Mapped[str] = mapped_column(String(12))
    title_he: Mapped[str] = mapped_column(String(400))
    explanation_he: Mapped[str] = mapped_column(Text)
    fix_hint_he: Mapped[str | None] = mapped_column(Text)
    measured_value: Mapped[float | None] = mapped_column(Float)
    measured_uncertainty: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    operator: Mapped[str | None] = mapped_column(String(4))
    units: Mapped[str | None] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    overlay_wkt: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    reviewer_decision: Mapped[str | None] = mapped_column(String(20))   # CONFIRMED | OVERRIDDEN | null
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str | None] = mapped_column(String(40))

    run: Mapped[CheckRun] = relationship(back_populates="findings")


class AuditEvent(Base):
    """Append-only, hash-chained audit trail (tamper-evident)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    actor: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class InferenceCost(Base):
    __tablename__ = "inference_costs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str | None] = mapped_column(String(32), index=True)
    user_id: Mapped[str | None] = mapped_column(String(40))
    task: Mapped[str] = mapped_column(String(40))
    provider_id: Mapped[str] = mapped_column(String(60))
    model_version: Mapped[str] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(30))             # OK | FALLBACK | MANUAL_REVIEW | BLOCKED_BY_POLICY
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[float] = mapped_column(Float, default=0)       # pages / tokens / calls
    cost_ils: Mapped[float] = mapped_column(Float, default=0.0)
    at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


class RuleApproval(Base):
    """Professional approval of a specific rule version for a tenant. Only an approval
    recorded here (by a user with the rule_approver permission) makes a rule binding."""
    __tablename__ = "rule_approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    rule_id: Mapped[str] = mapped_column(String(80))
    rule_version: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(20))            # APPROVED | REVOKED
    approved_by: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)
    at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


class AIPolicyRow(Base):
    """Tenant-level overrides of knowledge/ai_policy.yaml, editable by an authorised admin."""
    __tablename__ = "ai_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    task: Mapped[str] = mapped_column(String(40))
    data_class: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(10))                # LOCAL | CLOUD | HYBRID
    provider_order: Mapped[list] = mapped_column(JSON, default=list)
    approved_by: Mapped[str | None] = mapped_column(String(40))
    approved_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
