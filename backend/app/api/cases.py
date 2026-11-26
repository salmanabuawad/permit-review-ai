"""API: cases, files, runs, findings, import and the AI-PC agent endpoints."""
from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


@router.get("/api/cases")
def list_cases(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    cs = s.scalars(select(PermitCase).where(PermitCase.tenant_id == p.tenant_id)
                   .order_by(PermitCase.created_at.desc()))
    return [case_dict(c, with_files=False) for c in cs]


@router.post("/api/cases")
def create_case(body: CaseIn, p: Principal = Depends(require("case.create")), s: Session = Depends(get_session)):
    if body.permit_type not in PERMIT_TYPES or body.track not in TRACKS:
        raise HTTPException(422, "סוג בקשה/מסלול לא מוכר")
    tenant = s.get(Municipality, p.tenant_id)
    c = PermitCase(tenant_id=p.tenant_id, is_demo=bool(tenant and tenant.is_demo), sla_due=services.sla_default(),
                   **body.model_dump())
    s.add(c)
    s.flush()
    audit.record(s, p.tenant_id, p.id, "case.create", "permit_case", c.id, body.model_dump())
    s.commit()
    return case_dict(c)


@router.get("/api/cases/{case_id}")
def get_case_api(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    return case_dict(get_case(s, p, case_id))


@router.patch("/api/cases/{case_id}")
def patch_case(case_id: str, body: DeclaredIn, p: Principal = Depends(require("case.upload")),
               s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    if c.locked_version is not None:
        raise HTTPException(409, "התיק נעול")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(c, k, {**c.declared, **v} if k == "declared" else v)
    audit.record(s, p.tenant_id, p.id, "case.update", "permit_case", c.id, changes)
    s.commit()
    return case_dict(c)


@router.post("/api/cases/{case_id}/files")
async def upload(case_id: str, file: UploadFile = File(...), doc_type: str = Form(...),
                 declared_units_m: float | None = Form(None), p: Principal = Depends(require("case.upload")),
                 s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    if c.locked_version is not None:
        raise HTTPException(409, "התיק נעול")
    if doc_type not in services.DOC_TYPES_HE:
        raise HTTPException(422, "סוג מסמך לא מוכר")
    data = await file.read()
    try:
        services.ingest_file(s, c, file.filename or "upload", data, doc_type, p.id, declared_units_m)
    except IntakeError as e:
        s.rollback()
        raise HTTPException(422, str(e)) from e
    s.commit()
    return case_dict(c)


@router.post("/api/files/{file_id}/lifecycle")
def file_lifecycle(file_id: str, body: LifecycleIn, p: Principal = Depends(current_user),
                   s: Session = Depends(get_session)):
    f = _file(s, p, file_id, allow_deleted=True)
    need = "file.delete" if body.state == "DELETED" else "case.upload"
    if not p.can(need):
        raise HTTPException(403, f"אין הרשאה: {need}")
    if len(body.note.strip()) < 3:
        raise HTTPException(422, "נדרש נימוק")
    try:
        services.set_file_lifecycle(s, f, body.state, p.id, body.note)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    s.commit()
    return case_dict(f.case)


@router.get("/api/files/{file_id}/page/{n}.png")
def page_png(file_id: str, n: int, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    f = _file(s, p, file_id)
    path = Path(f.storage_path) if f.kind == "pdf" else services.converted_pdf_path(f) if f.kind == "dwfx" else None
    if path is None:
        raise HTTPException(400, "לא PDF" if f.kind != "dwfx" else services.DWFX_PENDING_HE)
    return Response(render_page_png(path, n), media_type="image/png")


@router.post("/api/agent/drawings/next", dependencies=[Depends(_agent)])
def agent_next_drawing(s: Session = Depends(get_session)):
    f = services.claim_drawing_read(s)
    if f is None:
        return Response(status_code=204)
    s.commit()
    return {"file_id": f.id, "filename": f.filename, "sha256": f.sha256, "size_bytes": f.size_bytes}


@router.get("/api/agent/drawings/{file_id}/source", dependencies=[Depends(_agent)])
def agent_drawing_source(file_id: str, s: Session = Depends(get_session)):
    f = _readable_dwfx(s, file_id)
    return FileResponse(f.storage_path, media_type="application/octet-stream", filename=f"{f.id}.dwfx")


@router.post("/api/agent/drawings/{file_id}/result", dependencies=[Depends(_agent)])
async def agent_drawing_result(file_id: str, request: Request, s: Session = Depends(get_session)):
    """Body: the reader's JSON, or {"error": "..."}."""
    f = _readable_dwfx(s, file_id)
    try:
        data = json.loads(await request.body())
    except ValueError:
        data = {"error": "invalid JSON"}
    err = data.get("error") if isinstance(data, dict) else "invalid result"
    services.complete_drawing_read(s, f, None if err else data, err)
    s.commit()
    return {"file_id": f.id, "state": (f.ingest_report.get("drawing_read") or {}).get("state")}


@router.post("/api/agent/conversions/next", dependencies=[Depends(_agent)])
def agent_next_conversion(s: Session = Depends(get_session)):
    f = services.claim_dwfx_conversion(s)
    if f is None:
        return Response(status_code=204)
    s.commit()
    return {"file_id": f.id, "filename": f.filename, "sha256": f.sha256, "size_bytes": f.size_bytes, "kind": f.kind}


@router.get("/api/agent/conversions/{file_id}/source", dependencies=[Depends(_agent)])
def agent_conversion_source(file_id: str, s: Session = Depends(get_session)):
    f = _pending_dwfx(s, file_id)
    return FileResponse(f.storage_path, media_type="application/octet-stream", filename=f"{f.id}.dwfx")


@router.post("/api/agent/conversions/{file_id}/result", dependencies=[Depends(_agent)])
async def agent_conversion_result(file_id: str, request: Request,
                                  s: Session = Depends(get_session),
                                  x_conversion_status: str = Header("ok"), x_conversion_info: str = Header("{}")):
    """Body: the PDF (X-Conversion-Status: ok) or a UTF-8 error message (X-Conversion-Status: failed)."""
    import urllib.parse
    f = _pending_dwfx(s, file_id)
    body = await request.body()
    if len(body) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "PDF too large")
    try:
        info = json.loads(urllib.parse.unquote(x_conversion_info))
    except ValueError:
        info = {}
    ok = x_conversion_status == "ok"
    services.complete_dwfx_conversion(s, f, body if ok else None, info if isinstance(info, dict) else {},
                                      None if ok else (body.decode("utf-8", "replace")[:500] or "conversion failed"))
    s.commit()
    if f.ingest_status == "OK":                    # the sheets now have text / an image: type the file again
        f.ingest_report = {k: v for k, v in (f.ingest_report or {}).items() if k != "ai_typed"}
        s.commit()
    return {"file_id": f.id, "ingest_status": f.ingest_status}


@router.get("/api/files/{file_id}/download")
def download(file_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    f = _file(s, p, file_id)
    audit.record(s, p.tenant_id, p.id, "file.download", "case_file", f.id, {})
    s.commit()
    return FileResponse(f.storage_path, filename=f.filename)


@router.get("/api/cases/{case_id}/geometry")
def geometry(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    ids = [f.id for f in services.latest_files(s, c) if f.kind in ("dxf", "dwg") and f.ingest_status == "OK"]
    feats = []
    for e in s.scalars(select(CadEntity).where(CadEntity.file_id.in_(ids))) if ids else []:
        g = shapely_wkt.loads(e.wkt_m)
        feats.append({"type": "Feature", "geometry": mapping(g),
                      "properties": {"layer": e.layer, "role": e.role, "dxftype": e.dxftype,
                                     "handle": e.source_handle, "via_block": e.via_block}})
    return {"type": "FeatureCollection", "features": feats, "units": "m", "crs": "local drawing coordinates"}


@router.post("/api/cases/{case_id}/run")
def run(case_id: str, p: Principal = Depends(require("case.run")), s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    try:
        r = services.run_checks(s, c, p.id)
    except PermissionError as e:
        raise HTTPException(409, str(e)) from e
    s.commit()
    return {"run_id": r.id, "version": r.version, "duration_ms": r.duration_ms, "summary": r.summary}


@router.post("/api/cases/recheck")
def recheck(body: RecheckIn, p: Principal = Depends(require("case.run")), s: Session = Depends(get_session)):
    """Re-run the rule checks on many cases (e.g. after a rule was approved or changed).
    Locked cases and cases without documents are skipped with a reason; one failure does not stop the rest."""
    q = select(PermitCase).where(PermitCase.tenant_id == p.tenant_id)
    if body.case_ids is not None:
        if not body.case_ids:
            raise HTTPException(422, "לא נבחרו תיקים")
        q = q.where(PermitCase.id.in_(body.case_ids))
    cases = list(s.scalars(q.order_by(PermitCase.created_at)))
    if len(cases) > RECHECK_MAX:
        raise HTTPException(422, f"ניתן להריץ בדיקה חוזרת על עד {RECHECK_MAX} תיקים בפעם אחת")
    done, skipped, failed = [], [], []
    gw = services.gateway_for(s, p.tenant_id, bulk=True)     # many cases: no LLM wait per report draft
    for c in cases:
        if c.locked_version is not None:
            skipped.append({"case_id": c.id, "case_number": c.case_number, "reason": "התיק נעול לאחר אישור"})
            continue
        if not services.latest_files(s, c):
            skipped.append({"case_id": c.id, "case_number": c.case_number, "reason": "אין מסמכים בתיק"})
            continue
        try:
            with s.begin_nested():
                r = services.run_checks(s, c, p.id, gateway=gw)
            done.append({"case_id": c.id, "case_number": c.case_number, "version": r.version,
                         "counts": r.summary.get("counts")})
        except Exception as e:                       # noqa: BLE001 — report and continue with the next case
            failed.append({"case_id": c.id, "case_number": c.case_number, "reason": str(e)[:300]})
    audit.record(s, p.tenant_id, p.id, "case.recheck_bulk", "permit_case", "*",
                 {"requested": len(cases), "done": len(done), "skipped": len(skipped), "failed": len(failed),
                  "scope": "selected" if body.case_ids is not None else "all"})
    s.commit()
    return {"requested": len(cases), "done": done, "skipped": skipped, "failed": failed}


@router.get("/api/cases/{case_id}/runs")
def runs(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    return [{"id": r.id, "version": r.version, "at": r.started_at.isoformat(), "ruleset_hash": r.ruleset_hash,
             "duration_ms": r.duration_ms, "counts": r.summary.get("counts"), "locked": r.locked} for r in c.runs]


@router.get("/api/runs/{run_id}/report/{kind}")
def report(run_id: str, kind: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    if kind not in ("completeness", "rights", "reviewer"):
        raise HTTPException(404)
    r = _run(s, p, run_id)
    return build_report(s, r.case, r, kind)


@router.get("/api/runs/{run_id}/defects")
def defects_report(run_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """The external defects report's content (JSON): confirmed defects and documented discrepancies only."""
    from ..defects_report import build_defects
    r = _run(s, p, run_id)
    return build_defects(r.case, r)


@router.post("/api/runs/{run_id}/attestations")
def run_attest(run_id: str, body: AttestIn, p: Principal = Depends(require("finding.decide")),
               s: Session = Depends(get_session)):
    """A signed review record for this exact run (who, when, the run's digest). Never taken from client flags."""
    from .. import attestation
    r = _run(s, p, run_id)
    try:
        a = attestation.attest(s, r, p.id, p.role, body.decision, body.note)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    s.commit()
    return attestation.public_view(s, a)


@router.get("/api/runs/{run_id}/attestations")
def run_attestations(run_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from .. import attestation
    return attestation.run_attestations(s, _run(s, p, run_id))


@router.get("/api/runs/{run_id}/coverage")
def run_coverage(run_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """Required-check inventory per rule family for this run (what was completed, open, not implemented)."""
    r = _run(s, p, run_id)
    rev = (r.summary or {}).get("review") or {}
    return {"decision": rev.get("decision"), "coverage": rev.get("coverage"), "disclaimer_he": rev.get("disclaimer_he")}


@router.get("/api/runs/{run_id}/audit")
def run_audit(run_id: str, p: Principal = Depends(require("audit.read")), s: Session = Depends(get_session)):
    """Internal audit record: every outcome (internal and unresolved included), citations, evidence, coverage,
    metrics and attestations. Not the external report; requires audit.read."""
    from .. import attestation
    r = _run(s, p, run_id)
    summ = r.summary or {}
    return {"run": {"id": r.id, "version": r.version, "case_id": r.case_id, "ruleset_hash": r.ruleset_hash,
                    "input_hashes": r.input_hashes, "started_at": r.started_at.isoformat() if r.started_at else None,
                    "digest": attestation.run_digest(r)},
            "review": summ.get("review"), "metrics": summ.get("metrics"),
            "findings": [{"rule_id": f.rule_id, "rule_version": f.rule_version, "status": f.status,
                          "computed_result": f.computed_result, "severity": f.severity, "title_he": f.title_he,
                          "explanation_he": f.explanation_he, "measured_value": f.measured_value,
                          "measured_uncertainty": f.measured_uncertainty, "threshold": f.threshold,
                          "units": f.units, "flags": f.flags, "citations": f.citations, "evidence": f.evidence,
                          "reviewer_decision": f.reviewer_decision} for f in r.findings],
            "attestations": attestation.run_attestations(s, r)}


@router.get("/api/runs/{run_id}/metrics")
def run_metrics_view(run_id: str, p: Principal = Depends(require("dashboard.read")), s: Session = Depends(get_session)):
    r = _run(s, p, run_id)
    rev = (r.summary or {}).get("review") or {}
    cov = rev.get("coverage") or {}
    return {"metrics": (r.summary or {}).get("metrics"), "review_counts": rev.get("counts"),
            "open_required_checks": cov.get("open"), "full_compliance_possible": cov.get("full_compliance_possible")}


@router.post("/api/cases/{case_id}/priority")
def prioritize(case_id: str, p: Principal = Depends(require("case.run")), s: Session = Depends(get_session)):
    """Put this request first: its typing, conversions and drawing reads go before every other request's."""
    c = get_case(s, p, case_id)
    m = s.get(Municipality, c.tenant_id)
    pri = [x for x in ((m.settings or {}).get("priority_cases") or []) if x != c.id]
    m.settings = {**(m.settings or {}), "priority_cases": [c.id] + pri}
    audit.record(s, c.tenant_id, p.id, "case.priority", "permit_case", c.id, {})
    s.commit()
    return {"priority_cases": m.settings["priority_cases"]}


@router.post("/api/cases/{case_id}/classify-documents")
def classify_documents(case_id: str, p: Principal = Depends(require("case.run")),
                       s: Session = Depends(get_session)):
    """Re-type the request's documents with the local AI (keyword fallback), then re-run the checks. The typing worker
    does it: one model call per document takes seconds."""
    c = get_case(s, p, case_id)
    for f in c.files:                              # the report shows "not ready" until each document is typed again
        f.ingest_report = {k: v for k, v in (f.ingest_report or {}).items() if k != "ai_typed"}
    s.commit()                                     # the typing worker picks them up
    return {"queued": True, "documents": len(c.files)}


@router.get("/api/runs/{run_id}/defects.pdf")
def defects_file(run_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from urllib.parse import quote
    from ..defects_report import build_defects, render_defects_pdf
    r = _run(s, p, run_id)
    ps = services.processing_status(r.case)
    if not ps["ready"]:
        raise HTTPException(409, "הדוח עדיין לא מוכן — " + "; ".join(ps["pending"][:5]))
    rep = build_defects(r.case, r)
    data = render_defects_pdf(rep)
    audit.record(s, p.tenant_id, p.id, "report.export", "check_run", r.id, {"kind": "defects", "format": "pdf",
                                                                           "items": len(rep["items"])})
    s.commit()
    name = f"defects_{r.case.case_number}_v{r.version}.pdf"
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"})


@router.post("/api/findings/{finding_id}/decision")
def decide(finding_id: str, body: DecisionIn, p: Principal = Depends(require("finding.decide")),
           s: Session = Depends(get_session)):
    f = s.get(Finding, finding_id)
    if not f or f.tenant_id != p.tenant_id:
        raise HTTPException(404)
    if f.run.locked:
        raise HTTPException(409, "הגרסה נעולה")
    if body.decision not in ("CONFIRMED", "OVERRIDDEN"):
        raise HTTPException(422)
    if body.decision == "OVERRIDDEN" and len(body.note.strip()) < 5:
        raise HTTPException(422, "דחיית ממצא מחייבת נימוק")
    f.reviewer_decision, f.reviewer_note, f.reviewer_id = body.decision, body.note, p.id
    audit.record(s, p.tenant_id, p.id, f"finding.{body.decision.lower()}", "finding", f.id,
                 {"rule_id": f.rule_id, "status": f.status, "note": body.note})
    s.commit()
    return {"ok": True}


@router.post("/api/cases/{case_id}/workflow")
def workflow(case_id: str, body: StatusIn, p: Principal = Depends(current_user), s: Session = Depends(get_session)):
    c = get_case(s, p, case_id)
    if body.status == "LOCK":
        if not p.can("case.lock"):
            raise HTTPException(403)
        try:
            services.lock_case(s, c, p.id)
            from .. import attestation       # the lock is the reviewer's approval: record it as a signed attestation
            attestation.attest(s, c.runs[-1], p.id, p.role, "APPROVED_FOR_REPORT", body.note or "")
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
    elif body.status == "ASSIGN":
        if not p.can("case.assign"):
            raise HTTPException(403)
        u = s.get(User, body.assigned_to or "")
        if not u or u.tenant_id != p.tenant_id or u.role != "reviewer":
            raise HTTPException(422, "בודק לא תקין")
        c.assigned_to = u.id
        audit.record(s, p.tenant_id, p.id, "case.assign", "permit_case", c.id, {"to": u.id})
    elif body.status in ("RETURNED_FOR_COMPLETION", "IN_REVIEW", "WAITING_EXTERNAL", "CLOSED"):
        if not p.can("case.run"):
            raise HTTPException(403)
        if c.locked_version is not None and body.status != "CLOSED":
            raise HTTPException(409, "התיק נעול")
        c.status = body.status
        audit.record(s, p.tenant_id, p.id, "case.status", "permit_case", c.id, {"status": body.status, "note": body.note})
    else:
        raise HTTPException(422)
    s.commit()
    return case_dict(c)


@router.post("/api/import/analyze")
async def import_analyze(files: list[UploadFile] = File(...), p: Principal = Depends(require("case.create")),
                         s: Session = Depends(get_session)):
    """Classify the documents, find the applications and extract their data. Creates no cases."""
    import uuid
    from ..intake.pipeline import analyze_package
    _cleanup_imports(p.tenant_id)
    uploads, total = [], 0
    for f in files:
        data = await f.read()
        total += len(data)
        if total > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"סך הקבצים גדול מ־{settings.max_upload_mb}MB")
        uploads.append((f.filename or "upload", data))
    linked = None
    if settings.follow_request_links:          # download every attachment the request form links to
        from ..intake.attachments import expand
        uploads, linked = expand(uploads)
    gw = _gateway_for(s, p.tenant_id)
    log = services.gateway_logger(s, p.tenant_id, None, p.id)
    route = lambda task, dc, payload: gw.route(task, dc, payload, log=log)  # noqa: E731
    existing_numbers = {c for (c,) in s.execute(select(PermitCase.case_number).where(PermitCase.tenant_id == p.tenant_id))}
    existing_hashes = {h: n for h, n in s.execute(select(CaseFile.sha256, PermitCase.case_number)
                                                  .join(PermitCase, CaseFile.case_id == PermitCase.id)
                                                  .where(CaseFile.tenant_id == p.tenant_id))}
    try:
        preview, blobs = analyze_package(uploads, route, existing_numbers, existing_hashes)
    except batch_import.ImportError_ as e:
        raise HTTPException(422, str(e)) from e
    if linked is not None:
        from ..intake.attachments import group_linked
        group_linked(preview, [n for n, _ in uploads if n not in {d["name"] for d in linked.downloaded}], linked)
        preview["warnings"] = linked.warnings_he() + list(preview.get("warnings") or [])
        preview["linked_files"] = linked.as_dict()
    token = dt.datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
    d = _import_dir(p.tenant_id, token)
    (d / "blobs").mkdir(parents=True, exist_ok=True)
    for ref, data in blobs.items():
        (d / "blobs" / ref).write_bytes(data)
    (d / "preview.json").write_text(json.dumps(preview, ensure_ascii=False), encoding="utf-8")
    import hashlib
    batch = ImportBatch(tenant_id=p.tenant_id, token=token, created_by=p.id, storage_path=str(d),
                        source_files=[{"name": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in uploads],
                        summary={"analysis": preview["counts"]})
    s.add(batch)
    s.flush()
    audit.record(s, p.tenant_id, p.id, "import.analyze", "import_batch", batch.id,
                 {"files": [n for n, _ in uploads], "counts": preview["counts"],
                  "linked_files": linked.as_dict() if linked else None})
    s.commit()
    return {"token": token, "batch_id": batch.id, **preview}


@router.get("/api/import/{token}/page/{ref}/{n}.png")
def import_page(token: str, ref: str, n: int, p: Principal = Depends(require("case.create"))):
    """Render a page of a staged document — the source preview next to an extracted value."""
    if not TOKEN_RE.match(token) or not REF_RE.match(ref):
        raise HTTPException(404)
    path = _import_dir(p.tenant_id, token) / "blobs" / ref
    if not path.exists():
        raise HTTPException(404, "המסמך לא נמצא או שפג תוקף הייבוא")
    try:
        return Response(render_page_png(path, n, zoom=1.3), media_type="image/png")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, "העמוד לא נמצא") from e


@router.post("/api/import/commit")
def import_commit(body: ImportCommitIn, p: Principal = Depends(require("case.create")),
                  s: Session = Depends(get_session)):
    import shutil
    from ..intake.commit import commit_preview
    if not TOKEN_RE.match(body.token):
        raise HTTPException(404, "הייבוא לא נמצא")
    d = _import_dir(p.tenant_id, body.token)
    batch = s.scalars(select(ImportBatch).where(ImportBatch.tenant_id == p.tenant_id, ImportBatch.token == body.token)).first()
    if batch is None or batch.status != "analyzed" or not (d / "preview.json").exists():
        raise HTTPException(404, "הייבוא לא נמצא, כבר בוצע או שפג תוקפו — יש לנתח את הקבצים מחדש")
    preview = json.loads((d / "preview.json").read_text(encoding="utf-8"))
    nums = [(a.fields.get("application_number") or "").strip() for a in body.applications if a.include]
    nums = [n for n in nums if n]
    if len(nums) != len(set(nums)):
        raise HTTPException(422, "מספרי בקשה כפולים בין הבקשות שנבחרו")
    result = commit_preview(s, p.tenant_id, p.id, batch, preview, d / "blobs",
                            [a.model_dump() for a in body.applications], body.run_checks, set(PERMIT_TYPES))
    final = settings.storage_dir / "_batches" / p.tenant_id / batch.id     # keep the original files with the batch
    final.parent.mkdir(parents=True, exist_ok=True)
    s.commit()
    shutil.move(str(d), str(final))
    batch.storage_path = str(final)
    s.commit()
    return result                                  # the typing worker types the new documents within seconds


@router.get("/api/import/batches")
def import_batches(p: Principal = Depends(require("case.create")), s: Session = Depends(get_session)):
    rows = s.scalars(select(ImportBatch).where(ImportBatch.tenant_id == p.tenant_id)
                     .order_by(ImportBatch.created_at.desc()).limit(50))
    return [{"id": b.id, "created_at": b.created_at.isoformat(), "created_by": b.created_by, "status": b.status,
             "files": b.source_files, "summary": b.summary} for b in rows]


@router.get("/api/cases/{case_id}/extracted")
def case_extracted(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """Extracted fields, comments and committee decision of an imported case, with sources."""
    c = get_case(s, p, case_id)
    refs = {}

    def ref(rid):
        if rid is None:
            return None
        if rid not in refs:
            r = s.get(SourceReference, rid)
            refs[rid] = None if r is None else {"file_id": r.file_id, "file": r.file_name, "page": r.page,
                                                 "original_page": r.original_page, "quote": r.quote, "method": r.method,
                                                 "confidence": r.confidence, "provider": r.provider_id}
        return refs[rid]
    fields = [{"field": f.field, "value": f.value.get("v"), "original_value": (f.original_value or {}).get("v"),
               "confidence": f.confidence, "status": f.status, "source": ref(f.source_ref_id)}
              for f in s.scalars(select(ExtractedField).where(ExtractedField.case_id == c.id).order_by(ExtractedField.id))]
    comments = [{"department": x.department, "department_he": x.department_he, "item_no": x.item_no, "text": x.text,
                 "source": ref(x.source_ref_id)}
                for x in s.scalars(select(PlanningComment).where(PlanningComment.case_id == c.id).order_by(PlanningComment.id))]
    decisions = [{"outcome": x.outcome, "text": x.text, "conditions": x.conditions, "meeting_number": x.meeting_number,
                  "meeting_date": x.meeting_date, "item_number": x.item_number, "source": ref(x.source_ref_id)}
                 for x in s.scalars(select(CommitteeDecision).where(CommitteeDecision.case_id == c.id))]
    return {"fields": [f for f in fields if f["field"] != "area"], "areas": [f for f in fields if f["field"] == "area"],
            "comments": comments, "decisions": decisions}


# ------------------------------------------------------------------ learning from decided cases

@router.post("/api/cases/{case_id}/decision")
async def case_decision(case_id: str, file: UploadFile | None = File(None), text: str | None = Form(None),
                        outcome: str | None = Form(None), p: Principal = Depends(require("learning.manage")),
                        s: Session = Depends(get_session)):
    """The committee's decision on a case the administrator loaded to learn from (a file, or the pasted text)."""
    from .. import learning
    c = get_case(s, p, case_id)
    if file is not None and file.filename:
        body = await file.read(source_service.load_config()["max_bytes"] + 1)
        name = file.filename
    elif text and text.strip():
        body, name = text.strip().encode("utf-8"), f"decision_{c.case_number}.txt"
    else:
        raise HTTPException(422, "יש לצרף את קובץ ההחלטה או להדביק את נוסחה")
    if len(body) > source_service.load_config()["max_bytes"]:
        raise HTTPException(413, "הקובץ גדול מדי")
    try:
        rec = learning.record_decision(s, c, p.id, name, body, outcome or None)
        learning.process(s, rec)                       # at once when the review is ready; else the worker does it
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    s.commit()
    return learning.record_dict(rec, c)


@router.get("/api/cases/{case_id}/decision")
def case_decision_get(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from .. import learning
    from ..models import LearningRecord
    c = get_case(s, p, case_id)
    rec = s.scalars(select(LearningRecord).where(LearningRecord.case_id == c.id, LearningRecord.status != "superseded")
                    .order_by(LearningRecord.id.desc())).first()
    return {"record": learning.record_dict(rec, c) if rec else None, "precedents": learning.precedents(s, c),
            "outcomes": learning.DECISION_OUTCOMES_HE}


@router.get("/api/cases/{case_id}/regulatory-resolution")
def case_regulatory_resolution(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    return reg.resolve_case(s, get_case(s, p, case_id))


@router.post("/api/cases/{case_id}/discover-plans")
def discover_case_plans(case_id: str, p: Principal = Depends(require("source.crawl")), s: Session = Depends(get_session)):
    return plan_discovery.refresh(s, get_case(s, p, case_id))


@router.get("/api/runs/{run_id}/findings/normalised")
def run_findings_normalised(run_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """Every finding of the run as a normalised record: measured / permitted / difference, method, evidence category,
    drawing and source references, V11 check status and the ten accuracy gates; plus coverage. Internal view."""
    from .. import finding_schema as FS
    run = _run(s, p, run_id)
    latest = s.scalar(select(func.max(CheckRun.version)).where(CheckRun.case_id == run.case_id)) == run.version
    rules = {r.id: r.raw for r in services.rules_for_tenant(s, p.tenant_id, include_deleted=True)}
    rows = [FS.normalise(f, rules.get(f.rule_id), latest) for f in run.findings]
    return {"run_id": run.id, "version": run.version, "latest": latest, "coverage": FS.coverage(rows), "findings": rows}


@router.get("/api/runs/{run_id}/revision")
def run_revision(run_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """What changed since the case's previous run: files, findings (new / corrected / unchanged / newly unresolved /
    newly applicable) and the exact inputs behind each change; plus the run's dependency-graph summary."""
    from .. import pdg
    run = _run(s, p, run_id)
    return {**pdg.revision(s, run), "pdg": (run.summary or {}).get("pdg")}
