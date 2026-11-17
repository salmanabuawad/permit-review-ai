"""Intake pipeline:  document → text → classification → application identification →
structured extraction → validation (schema + grounding + index cross-check) → preview.

Pure with respect to the database: the caller passes the set of application numbers and file
hashes that already exist (for duplicate detection) and gets back a JSON-able preview plus the
staged blobs. Nothing is written to the database here. Errors in one file never stop the others.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict
from pathlib import PurePosixPath

import pymupdf

from .. import batch_import as legacy
from . import classify as C
from . import metadata as M
from . import protocol as P
from . import text as T
from .grounding import ground
from .schemas import DOC_CLASSES, ApplicationExtraction, Extracted, SourceRef

KIND = {".pdf": "pdf", ".dxf": "dxf", ".dwg": "dwg", ".xlsx": "xlsx", ".xlsm": "xlsx", ".csv": "csv",
        ".json": "json", ".html": "html", ".htm": "html"}
DOC_TYPE_BY_CLASS = {"committee_protocol": "committee_protocol", "planning_regulation": "planning_regulation",
                     "architectural_drawing": "architectural_plan", "permit_application": "application_form"}
MERGE_FIELDS = ["application_number", "building_file_number", "address", "gush", "helka", "zone", "plot_area_m2",
                "application_type",
                "permit_type", "description", "applicable_plans", "deviations"]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _field_json(e: Extracted | None):
    if e is None:
        return None
    s = e.source
    return {"value": e.value, "confidence": s.confidence, "needs_review": s.confidence < 0.8,
            "source": s.model_dump()}


def rules_extract(payload: dict) -> dict:
    """local_rules provider for the 'Extraction' task."""
    if payload["kind"] == "protocol_item":
        return P.parse_application(payload["pages"], payload["file"], payload.get("sha"),
                                   payload.get("page_map")).model_dump()
    # original application form: generic "label: value" extraction (legacy, still content-based)
    ext = ApplicationExtraction(pages=[p for p, _ in payload["pages"]])
    for page_no, txt in payload["pages"]:
        fields, sources = legacy.extract_fields(txt, payload["file"], page_no)
        for k, v in fields.items():
            src = sources[k]
            ref = SourceRef(file=payload["file"], file_sha256=payload.get("sha"), page=page_no,
                            method=src.method, confidence=src.confidence)
            target = {"case_number": "application_number", "title": None, "survey_map_date": None}.get(k, k)
            if target and hasattr(ext, target) and getattr(ext, target) is None and not isinstance(v, list):
                setattr(ext, target, Extracted(value=v, source=ref))
            elif target == "applicable_plans" and ext.applicable_plans is None:
                ext.applicable_plans = Extracted(value=", ".join(v) if isinstance(v, list) else v, source=ref)
    return ext.model_dump()


class Package:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.documents: list[dict] = []
        self.index_rows: list[M.IndexRow] = []
        self.planning_items: list[dict] = []
        self.warnings: list[str] = []
        self.extractions: list[tuple[dict, ApplicationExtraction]] = []   # (doc, extraction)

    def stage(self, data: bytes) -> str:
        ref = uuid.uuid4().hex[:12]
        self.blobs[ref] = data
        return ref


def _pdf_pages(data: bytes) -> tuple[list[str], list[int]]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        texts = [p.get_text() for p in doc]
        drawings = []
        for i, p in enumerate(doc):
            if i < 3 and len(texts[i].strip()) < 600:
                try:
                    drawings.append(len(p.get_drawings()))
                except Exception:  # noqa: BLE001
                    drawings.append(0)
        return texts, drawings
    finally:
        doc.close()


def _process_document(pkg: Package, group: str, name: str, data: bytes, route) -> None:
    ext = PurePosixPath(name).suffix.lower()
    kind = KIND.get(ext)
    sha = _sha(data)
    doc = {"ref": pkg.stage(data), "name": name, "group": group, "sha256": sha, "size": len(data), "kind": kind,
           "status": "ok", "messages": [], "classification": None, "pages": None, "applications": [],
           "planning_items": 0, "doc_type": None, "needs_ocr_pages": []}
    pkg.documents.append(doc)
    if kind is None:
        doc.update(status="skipped", messages=[f"סוג קובץ לא נתמך ({ext or 'ללא סיומת'})"])
        return
    try:
        if kind in ("csv", "json", "html") or (kind == "xlsx"):
            header, rows = M.parse_index(name, data)
            cls = C.classify_file(name, kind, table_header=header)
            doc["classification"] = cls.model_dump()
            if cls.doc_class == "metadata_index":
                pkg.index_rows.extend(rows)
                doc.update(status="metadata", doc_type=None,
                           messages=[f"קובץ אינדקס: {len(rows)} שורות — משמש להתאמת מסמכים בלבד, לא נוצרת ממנו בקשה"])
                return
            if kind != "xlsx":
                doc.update(status="skipped", messages=["טבלה שאינה אינדקס בקשות — דולגה"])
                return
            doc["doc_type"] = "area_table"
            return
        if kind in ("dxf", "dwg"):
            cls = C.classify_file(name, kind)
            doc.update(classification=cls.model_dump(), doc_type="architectural_plan")
            return
        texts, drawings = _pdf_pages(data)
        doc["pages"] = len(texts)
        empty = [i + 1 for i, t in enumerate(texts) if len(t.strip()) < 20]
        if empty:   # OCR only where there is no text layer
            ocr = route("OCR", "CASE_DOCUMENT", {"file": name, "pages": empty})
            if ocr.outcome in ("OK", "FALLBACK") and ocr.output:
                for p, t in (ocr.output.get("pages") or {}).items():
                    texts[int(p) - 1] = t
            else:
                doc["needs_ocr_pages"] = empty
                doc["messages"].append(f"עמודים ללא שכבת טקסט ({', '.join(map(str, empty))}) — נדרש OCR, אין ספק OCR פעיל")
        cls = C.classify_file(name, "pdf", texts, drawings)
        doc["classification"] = cls.model_dump()
        doc["doc_type"] = DOC_TYPE_BY_CLASS.get(cls.doc_class) or legacy.guess_doc_type(name, "pdf", "\n".join(texts), None)[0]
        if cls.doc_class == "committee_protocol":
            items, front = P.split_items(texts)
            for kind_i, pages in items:
                cleaned = [(p, T.clean_page(texts[p - 1])) for p in pages]
                if kind_i == "planning":
                    pi = P.parse_planning(cleaned)
                    pkg.planning_items.append({"file": name, **pi.model_dump()})
                    doc["planning_items"] += 1
                    continue
                payload = {"kind": "protocol_item", "pages": cleaned, "file": name, "sha": sha}
                res = route("Extraction", "CASE_DOCUMENT", payload)
                if res.outcome not in ("OK", "FALLBACK") or not res.output:
                    doc["messages"].append(f"חילוץ נכשל לעמודים {pages[0]}–{pages[-1]} — הועבר לבדיקה ידנית")
                    continue
                extraction = ApplicationExtraction.model_validate(res.output)          # schema validation
                for f in MERGE_FIELDS:
                    v = getattr(extraction, f)
                    if v is not None:
                        v.source.provider = res.provider_id or "local_rules"
                extraction, _ = ground(extraction, " ".join(t for _, t in cleaned))     # no invented values
                pkg.extractions.append((doc, extraction))
                doc["applications"].append(extraction.application_number.value if extraction.application_number else None)
            if not items:
                doc["messages"].append("פרוטוקול ללא פריטי בקשות")
        elif cls.doc_class == "permit_application":
            ranges = legacy.split_multi_request_pdf(data) or [(0, len(texts) - 1)]
            for first, last in ranges:
                pages = [(p + 1, texts[p]) for p in range(first, last + 1)]
                res = route("Extraction", "CASE_DOCUMENT", {"kind": "form", "pages": pages, "file": name, "sha": sha})
                if res.outcome in ("OK", "FALLBACK") and res.output:
                    extraction, _ = ground(ApplicationExtraction.model_validate(res.output), " ".join(t for _, t in pages))
                    pkg.extractions.append((doc, extraction))
                    doc["applications"].append(extraction.application_number.value if extraction.application_number else None)
    except Exception as exc:  # noqa: BLE001 — one bad file must not stop the batch
        doc.update(status="failed", messages=doc["messages"] + [f"שגיאה בעיבוד הקובץ: {exc}"])


def _merge(app: dict, e: ApplicationExtraction, doc: dict, page_map: dict[int, int]) -> None:
    for f in MERGE_FIELDS:
        v = getattr(e, f)
        if v is None:
            continue
        if page_map and v.source.page in page_map:
            v.source.original_page = page_map[v.source.page]
        cur = app["fields"].get(f)
        if cur is None or v.source.confidence > cur["confidence"]:
            app["fields"][f] = _field_json(v)
        elif cur and str(cur["value"]) != str(v.value) and f not in ("permit_type",):
            app["warnings"].append(f"ערך שונה בין מסמכים בשדה '{f}': '{cur['value']}' / '{v.value}'")
    seen = {(c["department"], c["item_no"], T.compact(c["text"])) for c in app["comments"]}
    for c in e.comments:
        key = (c.department, c.item_no, T.compact(c.text))
        if key not in seen:
            seen.add(key)
            d = c.model_dump()
            d["source"]["original_page"] = page_map.get(c.source.page) if page_map else None
            app["comments"].append(d)
    for a in e.areas:
        key = (a.floor, a.status, a.label, a.value_m2)
        if key not in {(x["floor"], x["status"], x["label"], x["value_m2"]) for x in app["areas"]}:
            app["areas"].append(a.model_dump())
    if e.decision and app["decision"] is None:
        app["decision"] = e.decision.model_dump()
        if page_map:
            app["decision"]["source"]["original_page"] = page_map.get(e.decision.source.page)
    for p in e.procedure:
        if p not in app["procedure"]:
            app["procedure"].append(p)
    for k in ("meeting_number", "meeting_date", "item_number"):
        if getattr(e, k) and not app.get(k):
            app[k] = getattr(e, k)
    app["warnings"].extend(w for w in e.warnings if w not in app["warnings"])


def analyze_package(uploads: list[tuple[str, bytes]], route, existing_numbers: set[str] | None = None,
                    existing_hashes: dict[str, str] | None = None) -> tuple[dict, dict[str, bytes]]:
    existing_numbers = existing_numbers or set()
    existing_hashes = existing_hashes or {}
    pkg = Package()
    items, unpack_warn = legacy.unpack(uploads)
    pkg.warnings.extend(unpack_warn)
    for group, name, data in items:
        _process_document(pkg, group, name, data, route)

    by_file = {r.get("file"): r for r in pkg.index_rows if r.get("file")}
    by_number = {r.get("application_number"): r for r in pkg.index_rows if r.get("application_number")}
    by_folder = {r.get("folder"): r for r in pkg.index_rows if r.get("folder")}
    apps: dict[str, dict] = {}
    used_rows: set[int] = set()

    def app_for(number: str | None, key_hint: str) -> dict:
        key = number or f"ללא-מספר-{key_hint}"
        if key not in apps:
            apps[key] = {"key": uuid.uuid4().hex[:8], "application_number": number, "fields": {}, "comments": [],
                         "areas": [], "decision": None, "procedure": [], "documents": [], "warnings": [],
                         "index_row": None, "status": "new", "meeting_number": None, "meeting_date": None,
                         "item_number": None}
        return apps[key]

    for doc, e in pkg.extractions:
        content_no = e.application_number.value if e.application_number else None
        row = by_file.get(doc["name"]) or (by_number.get(content_no) if content_no else None) or by_folder.get(doc["group"])
        row_no = row.get("application_number") if row else None
        if content_no and row_no and content_no != row_no:
            doc["messages"].append(f"אי-התאמה: מספר הבקשה במסמך {content_no} ובאינדקס {row_no} — הותאם לפי המסמך")
            row = by_number.get(content_no)
        number = content_no or row_no
        app = app_for(number, doc["ref"])
        page_map = {}
        if row and row.get("page_start") and str(row.get("page_start")).isdigit():
            start = int(row.get("page_start"))
            if len(e.pages) == (doc.get("pages") or 0):          # excerpt file: page i ↦ start + i - 1
                page_map = {p: start + p - 1 for p in e.pages}
        _merge(app, e, doc, page_map)
        if row:
            used_rows.add(id(row))
            app["index_row"] = {"source": row.source, "row": row.row, **row.values}
        if number is None and row is None:
            app["warnings"].append("לא זוהה מספר בקשה — יש להזין ידנית")
        # the document attached to the case: the item's own pages when the PDF holds several items
        multi = len([1 for d, _ in pkg.extractions if d is doc]) > 1
        if multi:
            first, last = min(e.pages), max(e.pages)
            ref = pkg.stage(legacy.pdf_subset(pkg.blobs[doc["ref"]], first - 1, last - 1))
            app["documents"].append({"ref": ref, "name": f"{PurePosixPath(doc['name']).stem}_p{first}-{last}.pdf",
                                     "doc_type": doc["doc_type"], "doc_class": doc["classification"]["doc_class"], "classification": doc["classification"],
                                     "origin": {"file": doc["name"], "sha256": doc["sha256"], "pages": [first, last]},
                                     "sha256": _sha(pkg.blobs[ref])})
        elif not any(d["ref"] == doc["ref"] for d in app["documents"]):
            app["documents"].append({"ref": doc["ref"], "name": doc["name"], "doc_type": doc["doc_type"],
                                     "doc_class": doc["classification"]["doc_class"], "classification": doc["classification"], "origin": None,
                                     "sha256": doc["sha256"]})

    # supporting documents and drawings: attach by folder or index row, otherwise report unassigned
    for doc in pkg.documents:
        if doc["status"] != "ok" or doc["applications"]:
            continue
        row = by_file.get(doc["name"]) or by_folder.get(doc["group"])
        target = None
        if row and row.get("application_number") in apps:
            target = apps[row.get("application_number")]
        elif doc["group"]:
            same = [a for a in apps.values() if any(d2["group"] == doc["group"] for d2 in pkg.documents
                                                    if any(x["ref"] == d2["ref"] for x in a["documents"]))]
            target = same[0] if len(same) == 1 else None
        if target:
            target["documents"].append({"ref": doc["ref"], "name": doc["name"], "doc_type": doc["doc_type"] or "other",
                                        "doc_class": (doc["classification"] or {}).get("doc_class"), "classification": doc["classification"], "origin": None,
                                        "sha256": doc["sha256"]})
            doc["applications"] = [target["application_number"]]
        else:
            doc["messages"].append("המסמך לא שויך לבקשה (אין מספר בקשה, תיקייה או שורת אינדקס מתאימה)")
            doc["status"] = "unassigned"

    for app in apps.values():
        row = app["index_row"]
        if row:   # cross-check / fill gaps from the index (metadata, not document content)
            checks = [("gush", row.get("gush")), ("helka", row.get("helka")),
                      ("address", M.index_address(row.get("address"))),
                      ("building_file_number", row.get("building_file_number"))]
            for f, iv in checks:
                if not iv:
                    continue
                cur = app["fields"].get(f)
                if cur is None:
                    app["fields"][f] = {"value": iv, "confidence": 0.9, "needs_review": False,
                                        "source": SourceRef(file=row["source"], page=None, quote=None,
                                                            method=f"קובץ אינדקס, שורה {row['row']}", confidence=0.9).model_dump()}
                elif f == "address" and M.same_address(str(cur["value"]), iv):
                    if cur["value"] != iv:          # same address — show the index spelling, keep the document quote
                        cur["source"]["method"] += " · הוצג בכתיב האינדקס (זהה בתוכן)"
                        cur["value"] = iv
                elif T.compact(str(cur["value"])) != T.compact(str(iv)):
                    app["warnings"].append(f"אי-התאמה בין המסמך לאינדקס בשדה '{f}': '{cur['value']}' / '{iv}'")
                    cur["needs_review"] = True
        no = app["application_number"]
        if no and no in existing_numbers:
            app["status"] = "duplicate"
        for d in app["documents"]:
            d["duplicate_of"] = existing_hashes.get(d["sha256"])

    orphans = [r for r in pkg.index_rows if id(r) not in used_rows and r.get("application_number") not in apps]
    if orphans:
        pkg.warnings.append(f"{len(orphans)} שורות באינדקס ללא מסמך תואם — לא נוצרו מהן בקשות: "
                            + ", ".join(str(r.get("application_number")) for r in orphans[:10]))

    counts = defaultdict(int)
    for d in pkg.documents:
        counts[f"documents_{d['status']}"] += 1
    counts["applications"] = len(apps)
    counts["applications_new"] = sum(1 for a in apps.values() if a["status"] == "new")
    counts["applications_duplicate"] = sum(1 for a in apps.values() if a["status"] == "duplicate")
    counts["planning_items"] = len(pkg.planning_items)
    for d in pkg.documents:
        if d["classification"]:
            d["classification"]["doc_class_he"] = DOC_CLASSES.get(d["classification"]["doc_class"])
    result = {"documents": pkg.documents, "applications": sorted(apps.values(), key=lambda a: (a["item_number"] is None, int(a["item_number"] or 0), a["application_number"] or "")),
              "planning_items": pkg.planning_items, "warnings": pkg.warnings, "counts": dict(counts),
              "index_rows": len(pkg.index_rows)}
    return result, pkg.blobs
