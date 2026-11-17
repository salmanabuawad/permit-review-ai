"""Commit a reviewed import preview to the database — idempotent and fault-tolerant.

* An application whose number already exists for the tenant is not created again: status
  "duplicate", or "updated" when new documents (by sha256) were attached to the existing case.
* Each application is committed inside its own savepoint; a failure is recorded and the
  remaining applications continue.
* Every document gets a processing job (created / updated / duplicate / metadata / skipped /
  unassigned / failed); extracted values, source references, comments and the committee
  decision are stored as separate entities with exact provenance.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, services
from ..ingest.files import IntakeError
from ..models import (CaseFile, CommitteeDecision, DocumentClassification, ExtractedField, ImportBatch, Municipality,
                      PermitCase, PlanningComment, ProcessingJob, SourceReference)

CASE_FIELDS = {"address": "address", "gush": "gush", "helka": "helka", "building_file_number": "building_file_number",
               "application_type": "application_type"}


def _src_row(s: Session, tenant: str, src: dict | None, file_id: str | None) -> int | None:
    if not src:
        return None
    r = SourceReference(tenant_id=tenant, file_id=file_id, file_name=src.get("file") or "", file_sha256=src.get("file_sha256"),
                        page=src.get("page"), original_page=src.get("original_page"), quote=src.get("quote"),
                        method=src.get("method") or "", confidence=float(src.get("confidence") or 0),
                        provider_id=src.get("provider") or "local_rules")
    s.add(r)
    s.flush()
    return r.id


def commit_preview(s: Session, tenant: str, user: str, batch: ImportBatch, preview: dict, blobs_dir: Path,
                   decisions: list[dict], run_checks: bool, permit_types: set[str]) -> dict:
    apps = {a["key"]: a for a in preview["applications"]}
    docs_by_ref = {d["ref"]: d for d in preview["documents"]}
    tenant_row = s.get(Municipality, tenant)
    results, counts = [], Counter()
    stamp = dt.datetime.now().strftime("%Y%m%d")

    for n, req in enumerate(decisions, 1):
        app = apps.get(req["key"])
        if app is None:
            continue
        if not req.get("include", True):
            counts["skipped"] += 1
            results.append({"application_number": app["application_number"], "status": "skipped", "message": "הוחרג ע\"י המשתמש"})
            continue
        fields = req.get("fields") or {}
        number = (fields.get("application_number") or app["application_number"] or "").strip()
        try:
            with s.begin_nested():
                out = _commit_one(s, tenant, user, batch, app, req, fields, number, blobs_dir, tenant_row,
                                  permit_types, stamp, n, run_checks)
            counts[out["status"]] += 1
            results.append(out)
        except Exception as exc:  # noqa: BLE001 — record and continue with the next application
            counts["failed"] += 1
            results.append({"application_number": number or None, "status": "failed", "message": str(exc)[:300]})
            s.add(ProcessingJob(tenant_id=tenant, batch_id=batch.id, file_name=", ".join(d["name"] for d in app["documents"])[:400],
                                stage="committed", status="failed", message=str(exc)[:1000],
                                application_numbers=[number] if number else []))

    for d in preview["documents"]:                      # documents that never reach a case
        if d["status"] in ("metadata", "skipped", "unassigned", "failed"):
            counts[f"documents_{d['status']}"] += 1
            s.add(ProcessingJob(tenant_id=tenant, batch_id=batch.id, file_name=d["name"], sha256=d["sha256"],
                                doc_class=(d.get("classification") or {}).get("doc_class"), stage="committed",
                                status=d["status"], message="; ".join(d.get("messages") or [])[:1000]))
    summary = {"created": counts["created"], "updated": counts["updated"], "duplicate": counts["duplicate"],
               "skipped": counts["skipped"], "failed": counts["failed"],
               "metadata_files": counts["documents_metadata"], "skipped_files": counts["documents_skipped"],
               "unassigned_files": counts["documents_unassigned"], "failed_files": counts["documents_failed"],
               "planning_items": len(preview.get("planning_items") or [])}
    batch.summary = summary
    batch.status = "committed" if not counts["failed"] else ("partial" if counts["created"] + counts["updated"] else "failed")
    batch.committed_at = dt.datetime.now(dt.timezone.utc)
    audit.record(s, tenant, user, "import.commit", "import_batch", batch.id, {"summary": summary, "token": batch.token})
    return {"summary": summary, "results": results, "batch_id": batch.id, "status": batch.status}


def _commit_one(s, tenant, user, batch, app, req, fields, number, blobs_dir, tenant_row, permit_types, stamp, n,
                run_checks) -> dict:
    existing = s.scalars(select(PermitCase).where(PermitCase.tenant_id == tenant,
                                                  PermitCase.case_number == number)).first() if number else None
    doc_choice = {d["ref"]: d for d in (req.get("documents") or [])}
    chosen_docs = [d for d in app["documents"] if doc_choice.get(d["ref"], {}).get("include", True)]

    if existing:
        case, created = existing, False
    else:
        ptype = fields.get("permit_type") or (app["fields"].get("permit_type") or {}).get("value") or "other"
        if ptype not in permit_types:
            raise ValueError(f"סוג בקשה לא מוכר: {ptype}")
        val = lambda k: fields.get(k) if k in fields else (app["fields"].get(k) or {}).get("value")  # noqa: E731
        title = (val("description") or "").strip()[:300] or f"בקשה {number}"
        case = PermitCase(tenant_id=tenant, is_demo=bool(tenant_row and tenant_row.is_demo), sla_due=services.sla_default(),
                          case_number=number or f"IMP-{stamp}-{batch.token[-4:]}-{n:02d}", title=title,
                          permit_type=ptype, source="import", import_batch_id=batch.id,
                          applicable_plans=[], declared={})
        for f, col in CASE_FIELDS.items():
            v = val(f)
            if v not in (None, ""):
                setattr(case, col, str(v))
        s.add(case)
        s.flush()
        created = True
        audit.record(s, tenant, user, "case.create", "permit_case", case.id,
                     {"case_number": case.case_number, "source": "import", "batch": batch.id,
                      "field_sources": {k: (v or {}).get("source") for k, v in app["fields"].items()},
                      "edited_fields": sorted(k for k, v in fields.items()
                                              if str(v) != str((app["fields"].get(k) or {}).get("value")))})

    existing_hashes = {f.sha256 for f in case.files}
    attached, dup_docs, file_ids = 0, 0, {}
    for d in chosen_docs:
        if d["sha256"] in existing_hashes:
            dup_docs += 1
            s.add(ProcessingJob(tenant_id=tenant, batch_id=batch.id, file_name=d["name"], sha256=d["sha256"],
                                doc_class=d.get("doc_class"), stage="committed", status="duplicate", case_id=case.id,
                                message="מסמך זהה כבר מצורף לתיק", application_numbers=[case.case_number]))
            continue
        doc_type = doc_choice.get(d["ref"], {}).get("doc_type") or d.get("doc_type") or "other"
        if doc_type not in services.DOC_TYPES_HE:
            doc_type = "other"
        try:
            # table detection costs ~1.7 s per page and the intake pipeline already read these pages
            cf = services.ingest_file(s, case, d["name"], (blobs_dir / d["ref"]).read_bytes(), doc_type, user,
                                      extract_tables=d.get("doc_class") not in ("committee_protocol", "permit_application"))
        except IntakeError as e:
            s.add(ProcessingJob(tenant_id=tenant, batch_id=batch.id, file_name=d["name"], sha256=d["sha256"],
                                doc_class=d.get("doc_class"), stage="committed", status="failed", case_id=case.id,
                                message=str(e), application_numbers=[case.case_number]))
            continue
        cf.doc_class, cf.origin = d.get("doc_class"), d.get("origin")
        file_ids[d["ref"]] = cf.id
        job = ProcessingJob(tenant_id=tenant, batch_id=batch.id, file_name=d["name"], sha256=d["sha256"],
                            doc_class=d.get("doc_class"), stage="committed", status="created" if created else "updated",
                            case_id=case.id, application_numbers=[case.case_number])
        s.add(job)
        s.flush()
        cls = _doc_classification(d)
        if cls:
            s.add(DocumentClassification(tenant_id=tenant, file_id=cf.id, job_id=job.id, doc_class=cls["doc_class"],
                                         confidence=cls["confidence"], method=cls["method"], signals=cls.get("signals") or [],
                                         provider_id=cls.get("provider") or "local_rules",
                                         model_version=cls.get("model_version") or "rules-1.0"))
        attached += 1
        existing_hashes.add(d["sha256"])

    if created:     # extracted data is stored once, with the case that was created from it
        main_file = next(iter(file_ids.values()), None)
        for f, data in app["fields"].items():
            final = fields.get(f, data.get("value"))
            edited = str(final) != str(data.get("value"))
            sid = _src_row(s, tenant, data.get("source"), main_file)
            s.add(ExtractedField(tenant_id=tenant, case_id=case.id, field=f, value={"v": final},
                                 original_value={"v": data.get("value")} if edited else None,
                                 confidence=float(data.get("confidence") or 0), status="edited" if edited else "auto",
                                 source_ref_id=sid, batch_id=batch.id))
        for f in ("application_number", "permit_type", "description"):
            if f in fields and f not in app["fields"] and fields[f]:
                s.add(ExtractedField(tenant_id=tenant, case_id=case.id, field=f, value={"v": fields[f]}, confidence=1.0,
                                     status="edited", batch_id=batch.id))
        for a in app["areas"]:
            sid = _src_row(s, tenant, a.get("source"), main_file)
            s.add(ExtractedField(tenant_id=tenant, case_id=case.id, field="area",
                                 value={"v": {k: a[k] for k in ("floor", "status", "label", "value_m2")}},
                                 confidence=float(a["source"]["confidence"]), status="auto", source_ref_id=sid,
                                 batch_id=batch.id))
        for c in app["comments"]:
            sid = _src_row(s, tenant, c.get("source"), main_file)
            s.add(PlanningComment(tenant_id=tenant, case_id=case.id, department=c["department"],
                                  department_he=c["department_he"], item_no=c.get("item_no"), text=c["text"],
                                  source_ref_id=sid))
        if app.get("decision"):
            dd = app["decision"]
            sid = _src_row(s, tenant, dd.get("source"), main_file)
            s.add(CommitteeDecision(tenant_id=tenant, case_id=case.id, meeting_number=dd.get("meeting_number"),
                                    meeting_date=dd.get("meeting_date"), item_number=dd.get("item_number"),
                                    outcome=dd["outcome"], text=dd["text"], conditions=dd.get("conditions") or [],
                                    source_ref_id=sid))
        s.flush()
        s.refresh(case)
        if run_checks and case.files:
            services.run_checks(s, case, user)
        status, msg = "created", "נוצר תיק עם מסמך אחד" if attached == 1 else f"נוצר תיק עם {attached} מסמכים"
    elif attached:
        status, msg = "updated", "התיק קיים — צורף מסמך חדש אחד" if attached == 1 else f"התיק קיים — צורפו {attached} מסמכים חדשים"
    else:
        status, msg = "duplicate", "התיק והמסמכים כבר קיימים — לא נוצרה רשומה כפולה"
    return {"application_number": case.case_number, "case_id": case.id, "status": status, "message": msg,
            "documents_attached": attached, "documents_duplicate": dup_docs}


def _doc_classification(d: dict) -> dict | None:
    return d.get("classification") or ({"doc_class": d["doc_class"], "confidence": 0.9, "method": "סיווג בעת הניתוח"}
                                       if d.get("doc_class") else None)
