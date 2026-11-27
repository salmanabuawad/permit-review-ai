"""BlindDatasetSanitizer — finds review and outcome information inside blind-review inputs and produces sanitized
derivatives where the separation is reliable; otherwise it quarantines the file and marks the case contaminated.

Inspected: PDF (annotations, embedded files, metadata, text layer: outcome wording, approval stamps), DOCX (comments,
tracked changes, text), DWF / DWFX (markup resources and their labels, reviewer properties), DXF (markup / redline
layers, text entities), DWG (text strings only — undecodable geometry), IFC (annotations, comments), ZIP archives
(recursively). Originals are never modified. Derivatives go to <out>/<case>/..., quarantined files are only listed.

Reliability rule: a derivative is produced only when the outcome information is held in separable parts (PDF
annotation objects, DOCX comment parts, DWF markup resources). If outcome wording is in the drawing content itself, or
the geometry cannot be decoded to confirm that nothing remains (legacy DWF W2D, DWG), the file is QUARANTINED — a
structurally stripped DWF is kept as a *candidate* derivative, never used by the engine.
Report entries carry case ids, file names, finding types and counts — never reviewer names or the annotation text.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

OUTCOME = re.compile(r"סירוב|לסרב|נדח[הת]|החלטת (?:ה)?ועדה|החלטה לאשר|אושר בוועדה|פרוטוקול|חוות דעת|גליון דרישות|"
                     r"יש לציין|יש להציג|יש להשלים|יש לתקן|לתיקון|היתר בניה מס|תעודת גמר|נוסח סופי|REJECTED|APPROVED|"
                     r"refus|reject|decision|redline|markup", re.I)
DWF_MARKUP_ROLES = re.compile(r"markup", re.I)


@dataclass
class FileReport:
    case: str
    file: str
    kind: str
    sha256: str
    findings: list = field(default_factory=list)  # {type, count}
    action: str = "CLEAN"                          # CLEAN | SANITIZED | QUARANTINED | UNVERIFIABLE
    derivative: str | None = None
    candidate: str | None = None                   # stripped copy kept for inspection only (not engine input)
    note: str = ""


@dataclass
class CaseReport:
    case: str
    files: list = field(default_factory=list)
    contaminated: bool = False
    reasons: list = field(default_factory=list)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class BlindDatasetSanitizer:
    def __init__(self, out_dir: Path, known_contaminated: dict | None = None):
        self.out = Path(out_dir)
        self.known = known_contaminated or {}      # case -> reason (e.g. reviewer information exposed in inspection)

    # ------------------------------------------------------------------ per file
    def inspect(self, case: str, path: Path, rel: str) -> FileReport:
        data = path.read_bytes()
        suf = path.suffix.lower()
        r = FileReport(case, rel, suf.lstrip("."), _sha(data))
        try:
            if suf == ".pdf":
                self._pdf(r, path)
            elif suf == ".docx":
                self._docx(r, data)
            elif suf in (".dwf", ".dwfx"):
                self._dwf(r, data)
            elif suf == ".dxf":
                self._dxf(r, data)
            elif suf == ".dwg":
                self._dwg(r, data)
            elif suf == ".ifc":
                self._text_only(r, data, "ifc")
            elif suf == ".zip":
                self._zip(r, data)
            else:
                r.action, r.note = "UNVERIFIABLE", "format not inspectable (image / OLE / binary) — not used"
        except Exception as e:                    # an unreadable file is never passed on
            r.action, r.note = "QUARANTINED", f"could not be inspected: {type(e).__name__}"
        return r

    def _derive(self, r: FileReport, data: bytes, candidate: bool = False) -> str:
        dst = self.out / ("_candidates" if candidate else "") / r.case / r.file
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        return str(dst)

    def _pdf(self, r: FileReport, path: Path):
        import pymupdf
        doc = pymupdf.open(path)
        annots = sum(len(list(p.annots() or [])) for p in doc)
        text = "".join(p.get_text() for p in doc)
        emb = doc.embfile_count()
        meta = " ".join(str(v) for v in (doc.metadata or {}).values() if v)
        hits = len(OUTCOME.findall(text))
        for typ, n in (("annotations", annots), ("embedded_files", emb), ("outcome_text", hits),
                       ("outcome_metadata", len(OUTCOME.findall(meta)))):
            if n:
                r.findings.append({"type": typ, "count": n})
        if not text.strip():
            r.note = "no text layer — stamps or handwriting cannot be screened"
            if not annots and not emb:
                r.action = "UNVERIFIABLE"
                return
        if hits:
            r.action, r.note = "QUARANTINED", "outcome wording in the page content — not separable"
            return
        if annots or emb or OUTCOME.search(meta):
            for p in doc:
                for a in list(p.annots() or []):
                    p.delete_annot(a)
            for i in range(doc.embfile_count() - 1, -1, -1):
                doc.embfile_del(i)
            doc.set_metadata({})
            buf = io.BytesIO()
            doc.save(buf, garbage=4)
            r.action, r.derivative = "SANITIZED", self._derive(r, buf.getvalue())
        elif r.action != "UNVERIFIABLE":
            r.action = "CLEAN"

    def _docx(self, r: FileReport, data: bytes):
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        body = z.read("word/document.xml").decode("utf-8", "replace")
        text = re.sub(r"<[^>]+>", " ", body)
        comments = [n for n in names if re.search(r"word/comments", n)]
        tracked = len(re.findall(r"<w:(?:ins|del) ", body))
        hits = len(OUTCOME.findall(text))
        for typ, n in (("comments", len(comments)), ("tracked_changes", tracked), ("outcome_text", hits)):
            if n:
                r.findings.append({"type": typ, "count": n})
        if hits or re.search(r"הועדה המקומית לתכנון|מנהלת? ועדה|הנחיות לפרסום", text):
            r.action, r.note = "QUARANTINED", "committee document or outcome wording in the body"
            return
        if comments or tracked:
            r.action, r.note = "QUARANTINED", "comments / tracked changes — stripping them is not implemented"
            return
        r.action = "CLEAN"

    def _dwf(self, r: FileReport, data: bytes):
        start = data.find(b"PK\x03\x04")
        if start < 0:
            r.action, r.note = "QUARANTINED", "no package found"
            return
        z = zipfile.ZipFile(io.BytesIO(data[start:]))
        names = z.namelist()
        roles = {}                                # resource href -> role, from every descriptor / manifest
        for n in names:
            if n.endswith(("descriptor.xml", "manifest.xml")) or n.lower().endswith(".fdseq"):
                t = z.read(n).decode("utf-8", "replace")
                for m in re.finditer(r'<[^>]*Resource[^>]*role="([^"]+)"[^>]*href="([^"]+)"', t):
                    roles[m.group(2).replace("/", "\\")] = m.group(1)
        markup = [n for n in names if DWF_MARKUP_ROLES.search(roles.get(n.replace("/", "\\"), ""))
                  or re.search(r"markup", n, re.I)]
        labels = 0
        for n in markup:
            if n.lower().endswith(".xml"):
                t = z.read(n).decode("utf-8", "replace")
                labels += len(re.findall(r'name="(?:Label|Name)"', t))
        # the markup drawing layer: the W2D whose object id the private markup data names
        w2d_ids = set()
        for n in markup:
            w2d_ids |= set(re.findall(r'MarkupW2dId="([0-9A-Fa-f-]+)"', z.read(n).decode("utf-8", "replace")))
        markup_w2d = []
        for n in names:
            if n.endswith("descriptor.xml"):
                t = z.read(n).decode("utf-8", "replace")
                for m in re.finditer(r'<[^>]*href="([^"]+\.w2d)"[^>]*objectId="([^"]+)"', t):
                    if m.group(2).strip("{}").upper() in {x.upper() for x in w2d_ids}:
                        markup_w2d.append(m.group(1))
        if markup:
            r.findings += [{"type": "markup_resources", "count": len(markup)}, {"type": "markup_labels", "count": labels}]
        if markup_w2d:
            r.findings.append({"type": "markup_graphics_layer", "count": len(markup_w2d)})
        w2d = [n for n in names if n.lower().endswith(".w2d")]
        if not markup:
            r.action = "UNVERIFIABLE" if w2d else "CLEAN"
            r.note = "no markup resources; W2D drawing content not decodable — not verified" if w2d else ""
            return
        # structural strip: drop markup resources and every reference to them (candidate only)
        drop = set(markup) | {n for n in names if n.replace("/", "\\") in {x.replace("/", "\\") for x in markup_w2d}}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as o:
            for n in names:
                if n in drop:
                    continue
                b = z.read(n)
                if n.endswith((".xml",)) and not n in drop:
                    t = b.decode("utf-8", "replace")
                    for d in drop:
                        t = re.sub(r'<[^<>]*href="' + re.escape(d.replace("/", "\\")) + r'"[^<>]*/>', "", t)
                    b = t.encode("utf-8")
                o.writestr(n, b)
        r.candidate = self._derive(r, data[:start] + buf.getvalue(), candidate=True)
        r.action = "QUARANTINED"
        r.note = ("reviewer markup present; markup resources stripped into a candidate copy, but the W2D drawing content "
                  "cannot be decoded to confirm no reviewer graphics remain" +
                  ("" if markup_w2d else "; the markup graphics layer could not be identified"))

    def _dxf(self, r: FileReport, data: bytes):
        t = data.decode("utf-8", "replace")
        layers = set(re.findall(r"\n\s*8\s*\n([^\n]+)", t))
        mk = [l for l in layers if re.search(r"markup|redline|review|הער|בודק", l, re.I)]
        hits = len(OUTCOME.findall(t))
        if mk:
            r.findings.append({"type": "markup_layers", "count": len(mk)})
        if hits:
            r.findings.append({"type": "outcome_text", "count": hits})
        r.action = "QUARANTINED" if (mk or hits) else "CLEAN"
        r.note = "layer-level stripping is not implemented" if (mk or hits) else ""

    def _dwg(self, r: FileReport, data: bytes):
        strings = re.findall(rb"[\x20-\x7e]{6,}", data) + [s.decode("utf-16-le", "ignore").encode()
                                                          for s in re.findall(rb"(?:[\x20-\x7e\xd0-\xd7]\x00|[\x00-\xff]\x05){6,}", data)]
        hits = sum(1 for s in strings if OUTCOME.search(s.decode("utf-8", "ignore")))
        if hits:
            r.findings.append({"type": "outcome_text", "count": hits})
            r.action, r.note = "QUARANTINED", "DWG with outcome wording — no DWG reader to strip it"
        else:
            r.action, r.note = "UNVERIFIABLE", "DWG geometry not decodable (no licensed reader) — not verified"

    def _text_only(self, r: FileReport, data: bytes, kind: str):
        t = data.decode("utf-8", "replace")
        n = len(re.findall(r"IFCANNOTATION|IFCRELASSOCIATESDOCUMENT", t)) + len(OUTCOME.findall(t))
        if n:
            r.findings.append({"type": "annotations_or_outcome", "count": n})
        r.action = "QUARANTINED" if n else "CLEAN"

    def _zip(self, r: FileReport, data: bytes):
        z = zipfile.ZipFile(io.BytesIO(data))
        sub = []
        for n in z.namelist():
            if n.endswith("/") or ".." in n:
                continue
            tmp = self.out / "_tmp" / Path(n).name
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(z.read(n))
            sub.append(self.inspect(r.case, tmp, f"{r.file}!{n}"))
            tmp.unlink()
        bad = [s for s in sub if s.action in ("QUARANTINED",)]
        r.findings.append({"type": "archive_members", "count": len(sub)})
        r.action = "QUARANTINED" if bad else ("UNVERIFIABLE" if any(s.action == "UNVERIFIABLE" for s in sub) else "CLEAN")
        r.note = "; ".join(f"{s.file}: {s.action}" for s in sub)[:400]

    # ------------------------------------------------------------------ per case / dataset
    def run(self, blind_root: Path) -> list[CaseReport]:
        out = []
        for case in sorted(p for p in Path(blind_root).iterdir() if p.is_dir()):
            cr = CaseReport(case.name)
            for f in sorted(case.rglob("*")):
                if f.is_file() and f.name not in ("application_metadata.json", "document_manifest.json"):
                    cr.files.append(self.inspect(case.name, f, str(f.relative_to(case))))
            outcome = [x for x in cr.files if x.action == "QUARANTINED" and any(
                fd["type"] in ("markup_resources", "outcome_text", "comments", "annotations_or_outcome", "markup_layers")
                for fd in x.findings)]
            if outcome:
                cr.contaminated = True
                cr.reasons.append(f"{len(outcome)} input file(s) carried review or outcome information")
            if case.name in self.known:
                cr.contaminated = True
                cr.reasons.append(self.known[case.name])
            out.append(cr)
        shutil.rmtree(self.out / "_tmp", ignore_errors=True)
        return out

    @staticmethod
    def report(cases: list[CaseReport]) -> dict:
        files = [f for c in cases for f in c.files]
        by = {}
        for f in files:
            by[f.action] = by.get(f.action, 0) + 1
        return {"cases": len(cases), "contaminated_cases": [c.case for c in cases if c.contaminated],
                "files": len(files), "actions": by,
                "detail": [{"case": c.case, "contaminated": c.contaminated, "reasons": c.reasons,
                            "files": [asdict(f) for f in c.files]} for c in cases]}


def save_report(rep: dict, path: Path) -> None:
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
