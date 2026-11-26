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
    __table_args__ = (UniqueConstraint("tenant_id", "case_number", name="uq_case_number_per_tenant"),)
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
    building_file_number: Mapped[str | None] = mapped_column(String(40))
    application_type: Mapped[str | None] = mapped_column(String(120))   # as written in the source document
    source: Mapped[str] = mapped_column(String(20), default="manual")   # manual | import
    import_batch_id: Mapped[str | None] = mapped_column(String(32), index=True)
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
    # Document life cycle (tender spec §12.3): ACTIVE | ARCHIVED (kept, excluded from checks) | DELETED (bytes purged)
    lifecycle: Mapped[str] = mapped_column(String(12), default="ACTIVE")
    doc_class: Mapped[str | None] = mapped_column(String(40))           # committee_protocol | permit_application | ...
    origin: Mapped[dict | None] = mapped_column(JSON)                   # {file, sha256, pages} when cut from a larger document
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
    job_id: Mapped[int | None] = mapped_column(Integer, index=True)    # processing job, for intake executions
    input_sha256: Mapped[str | None] = mapped_column(String(64))
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


# ------------------------------------------------------------------ document intake (import)

class ImportBatch(Base):
    """One upload analysed (and possibly committed). Original files are kept under storage_path."""
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    committed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="analyzed")   # analyzed | committed | partial | failed
    source_files: Mapped[list] = mapped_column(JSON, default=list)        # [{name, sha256, size}]
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    storage_path: Mapped[str] = mapped_column(String(600))


class ProcessingJob(Base):
    """Per-document processing record of a batch (classification, extraction, import outcome)."""
    __tablename__ = "processing_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str | None] = mapped_column(String(64))
    doc_class: Mapped[str | None] = mapped_column(String(40))
    stage: Mapped[str] = mapped_column(String(30))     # analyzed | committed
    status: Mapped[str] = mapped_column(String(20))    # created | updated | duplicate | metadata | skipped | unassigned | failed
    message: Mapped[str | None] = mapped_column(Text)
    application_numbers: Mapped[list] = mapped_column(JSON, default=list)
    case_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


class DocumentClassification(Base):
    __tablename__ = "document_classifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("case_files.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    doc_class: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(200))
    signals: Mapped[list] = mapped_column(JSON, default=list)
    provider_id: Mapped[str] = mapped_column(String(60), default="local_rules")
    model_version: Mapped[str] = mapped_column(String(60), default="rules-1.0")
    at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


class SourceReference(Base):
    """Exact provenance of an extracted value: file, page, page in the original protocol, quote."""
    __tablename__ = "source_references"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("case_files.id", ondelete="SET NULL"), index=True)
    file_name: Mapped[str] = mapped_column(String(400))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    page: Mapped[int | None] = mapped_column(Integer)
    original_page: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(300))
    confidence: Mapped[float] = mapped_column(Float)
    provider_id: Mapped[str] = mapped_column(String(60), default="local_rules")


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("permit_cases.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(60))
    value: Mapped[dict] = mapped_column(JSON)                     # {"v": value}
    original_value: Mapped[dict | None] = mapped_column(JSON)     # as extracted, when a person edited it
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))               # auto | edited | confirmed
    source_ref_id: Mapped[int | None] = mapped_column(ForeignKey("source_references.id"))
    batch_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


class PlanningComment(Base):
    __tablename__ = "planning_comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("permit_cases.id", ondelete="CASCADE"), index=True)
    department: Mapped[str] = mapped_column(String(60))
    department_he: Mapped[str] = mapped_column(String(120))
    item_no: Mapped[str | None] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    source_ref_id: Mapped[int | None] = mapped_column(ForeignKey("source_references.id"))


class CommitteeDecision(Base):
    __tablename__ = "committee_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("permit_cases.id", ondelete="CASCADE"), index=True)
    meeting_number: Mapped[str | None] = mapped_column(String(20))
    meeting_date: Mapped[str | None] = mapped_column(String(10))
    item_number: Mapped[str | None] = mapped_column(String(10))
    outcome: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    source_ref_id: Mapped[int | None] = mapped_column(ForeignKey("source_references.id"))


# ------------------------------------------------------------------ source monitor (crawl official rule sources)

class SourceCrawl(Base):
    """One crawl of the official rule sources (manual button, CLI or timer)."""
    __tablename__ = "source_crawls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    triggered_by: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="running")     # running | done | failed
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceDocument(Base):
    """A page or document at an official URL (from the source register, or linked from a register page)."""
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("tenant_id", "url", name="uq_source_documents_tenant_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    kind: Mapped[str] = mapped_column(String(20))                    # page | document | manual
    source_id: Mapped[str | None] = mapped_column(String(60))        # register id (knowledge/sources.yaml)
    title: Mapped[str | None] = mapped_column(String(400))
    discovered_from: Mapped[str | None] = mapped_column(String(1000))
    first_seen: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    last_checked: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    fetch_status: Mapped[str | None] = mapped_column(String(20))     # ok | not_modified | blocked | unreachable | error | too_large | bad_type | manual
    http_status: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    change_state: Mapped[str | None] = mapped_column(String(20))     # new | changed | unchanged
    changed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(40))
    sha256: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str | None] = mapped_column(String(120))
    size: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str | None] = mapped_column(String(600))
    etag: Mapped[str | None] = mapped_column(String(200))
    last_modified: Mapped[str | None] = mapped_column(String(100))
    links: Mapped[list] = mapped_column(JSON, default=list)           # pages: document links found


class SourceSnapshot(Base):
    """Each distinct version (by SHA-256) of a source document that was fetched or uploaded."""
    __tablename__ = "source_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), index=True)
    crawl_id: Mapped[str | None] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str | None] = mapped_column(String(600))
    origin: Mapped[str] = mapped_column(String(20))                  # crawl | upload
    uploaded_by: Mapped[str | None] = mapped_column(String(40))
    fetched_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    text_chars: Mapped[int] = mapped_column(Integer, default=0)


class RuleDraft(Base):
    """A candidate rule clause found in a source document — a suggestion for a rule author, never an active rule."""
    __tablename__ = "rule_drafts"
    __table_args__ = (UniqueConstraint("tenant_id", "document_id", "key", name="uq_rule_drafts_doc_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("source_snapshots.id"))
    key: Mapped[str] = mapped_column(String(40))                     # sha1 of the normalised clause text
    page: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(30))                    # numeric_limit | required_document | prohibition
    topics: Mapped[list] = mapped_column(JSON, default=list)
    text_he: Mapped[str] = mapped_column(Text)
    values: Mapped[list] = mapped_column(JSON, default=list)          # [{value, unit, op}]
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | for_authoring | dismissed | superseded
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(40))
    decided_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


# ------------------------------------------------------------------ rule authoring

class RuleDefinition(Base):
    """A rule created or edited in the rules screen. Layered over the YAML catalogue (knowledge/rules):
    a row with the id of a file rule replaces it, `deleted` hides it, and a row with a new id adds a rule.
    Every save bumps the version, so an earlier professional approval never carries over to edited text.
    The full before/after of each change is in the audit log."""
    __tablename__ = "rule_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_id", name="uq_rule_definitions_tenant_rule"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_by: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


class ReviewAttestation(Base):
    """A reviewer's signed statement about one check run (V9: a real authenticated review record, not a flag in JSON).

    `digest` is the SHA-256 of the run's canonical content (inputs, rule-set hash, every finding's status and reviewer
    decision); `signature` is an HMAC of (run id, digest, user, role, decision, time) with the server's attestation
    key, which never leaves the app server. An attestation is valid only while the run still has that digest and is
    the case's latest run — a new run or a changed finding makes it STALE, a wrong signature makes it INVALID."""
    __tablename__ = "review_attestations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    run_version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(40))          # REVIEWED | APPROVED_FOR_REPORT | REJECTED_RUN
    note: Mapped[str] = mapped_column(Text, default="")
    digest: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(String(64))
    at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


class DerivationCache(Base):
    """Derived data keyed by input SHA-256 + algorithm and version (+ jurisdiction and application revision for
    case-level results). Changing a file, an algorithm version or the rule set changes the key; `invalidate` removes
    a file's derivatives and every case-level result that depended on it."""
    __tablename__ = "derivation_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(10))              # document | case
    algorithm: Mapped[str] = mapped_column(String(80))
    algorithm_version: Mapped[str] = mapped_column(String(40))
    input_sha256: Mapped[str] = mapped_column(String(64), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(40), default="")
    revision: Mapped[str] = mapped_column(String(80), default="")
    depends_on: Mapped[list] = mapped_column(JSON, default=list)   # sha256 of every file a case-level result used
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)


class AuthorityMembership(Base):
    """The login account is distinct from the actor in each authority."""
    __tablename__ = 'authority_memberships'
    account_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('municipalities.id'), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True, nullable=False)


class CandidatePassage(Base):
    """Searchable unverified source text, never part of active rules or trusted retrieval."""
    __tablename__ = 'candidate_passages'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('municipalities.id'), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey('source_documents.id'), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey('source_snapshots.id'))
    page: Mapped[int] = mapped_column(Integer)
    text_he: Mapped[str] = mapped_column(Text)


class LearningRecord(Base):
    """A decided case the administrator loaded to learn from: the committee's decision against the engine's findings.
    What it teaches goes to the knowledge base as precedent and unverified passages at once; missing checks become
    rule drafts that take effect only after professional approval."""
    __tablename__ = "learning_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("municipalities.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("permit_cases.id", ondelete="CASCADE"), index=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("committee_decisions.id", ondelete="CASCADE"))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")     # pending | done | failed
    outcome: Mapped[str] = mapped_column(String(40))
    reasons: Mapped[list] = mapped_column(JSON, default=list)              # [{no, text_he, topics}]
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=_now)
    processed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
