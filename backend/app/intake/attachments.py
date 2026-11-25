"""Follow the attachment links in an uploaded request before it is analysed.

A Rishui Zamin request form (and its permit-information file) lists every attached document as a link to
p-api.rishuybniya.moin.gov.il/api/FormDownload/... — the PDF itself carries none of them. So before analysis the
package is expanded: every such link in every uploaded PDF is downloaded, and the downloaded PDFs are searched in
turn (an information file links the planning info, the IEC letter links its own attachments, ...).

Only links to the official download API are followed (ALLOWED); any other link (gov.il pages, IEC, Home Front
Command) is counted and left alone, so an uploaded file cannot make the server fetch arbitrary URLs. A file whose
content was already uploaded or downloaded is not added twice. Limits: depth, file count, total size, time.
"""
from __future__ import annotations

import hashlib
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import pymupdf

from ..config import settings

log = logging.getLogger("bbp.intake.attachments")

ALLOWED = {"p-api.rishuybniya.moin.gov.il": "/api/FormDownload/"}
MAX_DEPTH = 3            # request form -> information file -> letter -> its attachments
MAX_FILES = 200
TIMEOUT_S = 120
WORKERS = 6
USER_AGENT = "Mozilla/5.0 (permit-review-ai attachment fetcher)"


@dataclass
class Expansion:
    downloaded: list[dict] = field(default_factory=list)     # {name, size, from}
    duplicates: list[dict] = field(default_factory=list)     # {name, same_as}
    failed: list[dict] = field(default_factory=list)         # {name, error}
    other_links: int = 0                                     # links not to the download API (not followed)
    truncated: str | None = None

    def warnings_he(self) -> list[str]:
        out = []
        if self.downloaded:
            out.append(f"הורדו {len(self.downloaded)} קבצים מהקישורים שבטופס הבקשה ובמסמכים המצורפים")
        if self.duplicates:
            out.append(f"{len(self.duplicates)} קבצים מקושרים זהים לקבצים שכבר קיימים — לא נוספו פעמיים")
        for f in self.failed:
            out.append(f"לא ניתן להוריד את '{f['name']}': {f['error']}")
        if self.truncated:
            out.append(self.truncated)
        return out

    def as_dict(self) -> dict:
        return {"downloaded": self.downloaded, "duplicates": self.duplicates, "failed": self.failed,
                "other_links": self.other_links, "truncated": self.truncated}


def is_download_link(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    prefix = ALLOWED.get((u.hostname or "").lower())
    return u.scheme == "https" and prefix is not None and re.sub("/+", "/", u.path).startswith(prefix)


def pdf_links(data: bytes) -> list[str]:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001 — not a readable PDF: nothing to follow
        return []
    seen, out = set(), []
    for page in doc:
        for link in page.get_links():
            uri = (link.get("uri") or "").strip()
            if uri and uri not in seen:
                seen.add(uri)
                out.append(uri)
    return out


def _name(url: str, disposition: str | None) -> str:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    name = (q.get("docName") or [None])[0]
    if not name and disposition:
        m = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I) or re.search(r'filename="?([^";]+)', disposition)
        name = urllib.parse.unquote(m.group(1)) if m else None
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", (name or "").strip()) or "attachment"
    return name[:180]


def _fetch(url: str, limit: int) -> tuple[str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        if not is_download_link(r.geturl()):
            raise ValueError("הפניה לכתובת מחוץ לרישוי זמין")
        if "text/html" in (r.headers.get("Content-Type") or ""):
            raise ValueError("התקבל דף אינטרנט ולא קובץ")
        data = r.read(limit + 1)
        if len(data) > limit:
            raise ValueError("הקובץ גדול מהמותר")
        if not data:
            raise ValueError("קובץ ריק")
        return _name(url, r.headers.get("Content-Disposition")), data


def expand(uploads: list[tuple[str, bytes]], fetch=None) -> tuple[list[tuple[str, bytes]], Expansion]:
    """uploads + every file linked from them (recursively), each file once. `fetch(url, limit) -> (name, bytes)`."""
    fetch = fetch or _fetch
    exp = Expansion()
    budget = settings.max_package_mb * 1024 * 1024
    files = list(uploads)
    by_sha = {hashlib.sha256(b).hexdigest(): n for n, b in uploads}
    names = {n for n, _ in uploads}
    visited: set[str] = set()
    frontier = [(n, b) for n, b in uploads if n.lower().endswith(".pdf")]
    for _depth in range(MAX_DEPTH):
        links = []
        for parent, data in frontier:
            for url in pdf_links(data):
                if not is_download_link(url):
                    exp.other_links += 1
                elif url not in visited:
                    visited.add(url)
                    links.append((parent, url))
        if not links:
            break
        room = MAX_FILES - len(exp.downloaded)
        if len(links) > room:
            exp.truncated = f"נמצאו יותר מ-{MAX_FILES} קבצים מקושרים — הורדו הראשונים בלבד"
            links = links[:max(room, 0)]
        spent = sum(len(b) for _, b in files)

        def get(item):
            parent, url = item
            try:
                return parent, url, *fetch(url, max(budget - spent, 1)), None
            except (urllib.error.URLError, OSError, ValueError) as e:
                reason = getattr(e, "reason", None) or e
                return parent, url, _name(url, None), None, str(reason)[:200]

        with ThreadPoolExecutor(WORKERS) as pool:
            results = list(pool.map(get, links))
        frontier = []
        for parent, url, name, data, error in results:
            if error:
                exp.failed.append({"name": name, "error": error, "from": parent})
                continue
            sha = hashlib.sha256(data).hexdigest()
            if sha in by_sha:
                exp.duplicates.append({"name": name, "same_as": by_sha[sha], "from": parent})
                continue
            if sum(len(b) for _, b in files) + len(data) > budget:
                exp.truncated = f"סך הקבצים המקושרים חורג מ-{settings.max_package_mb}MB — חלק לא הורדו"
                exp.failed.append({"name": name, "error": "חריגה מגודל החבילה", "from": parent})
                continue
            if name in names:                     # same name, different content: keep both
                stem, ext = PurePosixPath(name).stem, PurePosixPath(name).suffix
                name = f"{stem} ({sha[:6]}){ext}"
            names.add(name)
            by_sha[sha] = name
            files.append((name, data))
            exp.downloaded.append({"name": name, "size": len(data), "from": parent})
            if name.lower().endswith(".pdf"):
                frontier.append((name, data))
    log.info("attachments: %d downloaded, %d duplicate, %d failed, %d other links",
             len(exp.downloaded), len(exp.duplicates), len(exp.failed), exp.other_links)
    return files, exp


def group_linked(preview: dict, uploaded: list[str], exp: Expansion) -> None:
    """Every file downloaded from a request form's links belongs to that request.

    The analysis groups documents by the application number it reads in them, which splits a Rishui Zamin package:
    the permit-information file looks like a form of its own, letters carry no number, and most attachments end up
    unassigned. The download already records which file linked to which, so: find the application whose own form is an
    uploaded file, move every document from that file's link tree into it, and drop the applications that consisted
    only of such documents. Applications from other uploads are untouched."""
    parent = {d["name"]: d["from"] for d in exp.downloaded}
    up = set(uploaded)

    def root(name: str | None) -> str | None:
        seen = set()
        while name in parent and name not in seen:
            seen.add(name)
            name = parent[name]
        return name if name in up else None

    def file_of(d: dict) -> str:
        return (d.get("origin") or {}).get("file") or d["name"]

    apps = preview.get("applications") or []
    if not parent:
        return                                      # nothing was downloaded: the analysis stands as it is
    candidates: dict[str, list[dict]] = {}
    for a in apps:                                  # the application whose own form is the uploaded file
        for d in a["documents"]:
            r = file_of(d)
            if r in up and a.get("application_number") and d.get("doc_type") == "application_form":
                if not any(x is a for x in candidates.setdefault(r, [])):
                    candidates[r].append(a)
    # one request per uploaded form; a PDF holding several requests is left as analysed (whose links? unknown)
    owner = {r: c[0] for r, c in candidates.items() if len(c) == 1}
    if not owner:
        return
    moved = 0
    for r, a in owner.items():
        refs = {d["ref"] for d in a["documents"]}
        files = {file_of(d) for d in a["documents"]}
        for doc in preview["documents"]:
            if doc["status"] not in ("ok", "unassigned") or root(doc["name"]) != r or doc["name"] in files:
                continue
            if doc["ref"] in refs:
                continue
            a["documents"].append({"ref": doc["ref"], "name": doc["name"], "doc_type": doc.get("doc_type") or "other",
                                   "doc_class": (doc.get("classification") or {}).get("doc_class"),
                                   "classification": doc.get("classification"), "origin": None, "sha256": doc["sha256"]})
            refs.add(doc["ref"])
            files.add(doc["name"])
            if doc["status"] == "unassigned":
                doc["status"] = "ok"
                doc["messages"] = [m for m in doc.get("messages", []) if "לא שויך" not in m]
            doc["applications"] = [a["application_number"]]
            doc.setdefault("messages", []).append(f"שויך לבקשה {a['application_number']} — הורד מקישור בטופס הבקשה")
            moved += 1
    owners = {id(a) for a in owner.values()}
    keep = []
    for a in apps:
        files = [file_of(d) for d in a["documents"]]
        roots = {root(f) for f in files}
        only_downloaded = bool(files) and all(f in parent for f in files)
        absorbed = len(roots) == 1 and next(iter(roots)) in owner and id(owner[next(iter(roots))]) != id(a)
        if id(a) not in owners and only_downloaded and absorbed:
            continue                                # consisted only of documents linked from another request
        keep.append(a)
    dropped = len(apps) - len(keep)
    preview["applications"] = keep
    c = preview.setdefault("counts", {})
    c["applications"] = len(keep)
    c["applications_new"] = sum(1 for a in keep if a.get("status") == "new")
    c["applications_duplicate"] = sum(1 for a in keep if a.get("status") == "duplicate")
    c["documents_ok"] = sum(1 for d in preview["documents"] if d["status"] == "ok")
    c["documents_unassigned"] = sum(1 for d in preview["documents"] if d["status"] == "unassigned")
    if moved or dropped:
        preview.setdefault("warnings", []).append(
            f"{moved} מסמכים שהורדו מקישורים שויכו לבקשה שבטופס שלה; {dropped} 'בקשות' שזוהו בטעות במסמכים המצורפים אוחדו בה")
