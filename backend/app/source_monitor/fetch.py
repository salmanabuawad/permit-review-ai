"""HTTP fetching and link discovery for the source monitor (standard library only, no JS execution).

Only hosts that appear in the source register (plus configured extra hosts) are ever contacted,
including after redirects. Every outcome is reported honestly: a site that blocks automated access
is "blocked", one that does not answer is "unreachable" — never silently treated as unchanged.
"""
from __future__ import annotations

import html as htmllib
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

CHALLENGE = re.compile(r"captcha|cf-chl|just a moment|access denied|request rejected|incapsula|bot detection", re.I)


@dataclass
class Fetched:
    status: str                     # ok | not_modified | blocked | unreachable | error | too_large
    url: str
    http_status: int | None = None
    content_type: str | None = None
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None
    message: str | None = None
    final_url: str | None = None    # after redirects (to resolve relative links)


def canonical(url: str) -> str:
    """Readable, comparable form: unquoted path/query, lower-case host, no fragment."""
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), unquote(p.path), unquote(p.query), ""))


def wire(url: str) -> str:
    """Percent-encoded form for the request line (Hebrew file names)."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.encode("idna").decode() if not p.netloc.isascii() else p.netloc,
                       quote(p.path, safe="/%:@!$&'()*+,;=-._~"), quote(p.query, safe="=&%:@!$'()*+,;/?-._~"), ""))


def host(url: str) -> str:
    return urlsplit(url).netloc.lower()


def public_target(url: str) -> bool:
    """Reject private/reserved destinations; production egress must also block DNS rebinding."""
    try:
        p=urlsplit(url)
        if p.scheme not in ('http','https') or p.username or p.password or p.port not in (None,80,443) or not p.hostname: return False
        ips=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
        return bool(ips) and all(ipaddress.ip_address(a[4][0]).is_global for a in ips)
    except (ValueError,OSError): return False


class _HostGuard(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed: set[str]):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlsplit(newurl)
        if p.scheme not in ("http", "https") or p.netloc.lower() not in self.allowed or not public_target(newurl):
            raise urllib.error.URLError(f"redirect to a host outside the register: {p.netloc}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, cfg: dict, allowed: set[str], etag: str | None = None, last_modified: str | None = None) -> Fetched:
    if host(url) not in allowed or not public_target(url):
        return Fetched("error", url, message="כתובת מחוץ לרשם המקורות")
    headers = {"User-Agent": cfg["user_agent"], "Accept": "text/html,application/pdf,*/*;q=0.8",
               "Accept-Language": "he,en;q=0.7"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    opener = urllib.request.build_opener(_HostGuard(allowed))
    limit = int(cfg["max_bytes"])
    try:
        with opener.open(urllib.request.Request(wire(url), headers=headers), timeout=cfg["timeout_s"]) as r:
            data = r.read(limit + 1)
            ct = r.headers.get_content_type()
            res = Fetched("ok", url, r.status, ct, data, r.headers.get("ETag"), r.headers.get("Last-Modified"),
                          final_url=r.geturl())
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return Fetched("not_modified", url, 304)
        if e.code in (401, 403, 429) or (e.code == 503 and CHALLENGE.search(_peek(e))):
            return Fetched("blocked", url, e.code, message=f"האתר חוסם גישה אוטומטית (HTTP {e.code})")
        if e.code in (404, 410):
            return Fetched("error", url, e.code, message=f"המסמך לא נמצא בכתובת (HTTP {e.code})")
        return Fetched("error", url, e.code, message=f"שגיאת שרת (HTTP {e.code})")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        reason = getattr(e, "reason", e)
        if "outside the register" in str(reason):
            where = str(reason).rsplit(":", 1)[-1].strip()
            return Fetched("error", url, message=f"הפניה לאתר שאינו ברשם המקורות — לא נשלפה ({where})")
        return Fetched("unreachable", url, message=f"האתר אינו זמין מהשרת ({type(reason).__name__})")
    if len(res.body) > limit:
        return Fetched("too_large", url, res.http_status, res.content_type, message=f"המסמך גדול מ־{limit // 2**20} MB")
    if res.content_type == "text/html" and len(res.body) < 20000 and CHALLENGE.search(res.body[:20000].decode("utf-8", "ignore")):
        return Fetched("blocked", url, res.http_status, message="האתר הציג בדיקת רובוטים (CAPTCHA)")
    return res


def _peek(e: urllib.error.HTTPError) -> str:
    try:
        return e.read(4000).decode("utf-8", "ignore")
    except Exception:                               # noqa: BLE001
        return ""


def decode_html(body: bytes) -> str:
    m = re.search(rb'charset=["\']?([\w-]+)', body[:3000])
    for enc in ([m.group(1).decode()] if m else []) + ["utf-8", "windows-1255"]:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "ignore")


def page_title(text: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    return _clean(m.group(1))[:400] if m else None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


ANCHOR = re.compile(r"<a\b[^>]*?href\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a>", re.S | re.I)


def discover_links(text: str, base_url: str, cfg: dict) -> tuple[list[dict], int]:
    """Document links on a register page that look relevant to building rules. Returns (links, ignored)."""
    exts = tuple("." + e.lower() for e in cfg["document_extensions"])
    kws = cfg["relevance_keywords"]
    base_host = host(base_url)
    found: dict[str, str] = {}
    ignored: set[str] = set()
    for _, href, inner in ANCHOR.findall(text):
        href = htmllib.unescape(href).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = canonical(urljoin(base_url, href))
        p = urlsplit(url)
        if p.netloc != base_host or not p.path.lower().endswith(exts):
            continue
        label = _clean(inner)
        hay = label + " " + p.path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")
        if not any(k in hay for k in kws):
            ignored.add(url)
            continue
        if len(label) > len(found.get(url, "")):
            found[url] = label
        else:
            found.setdefault(url, label)
    links = [{"url": u, "text": t or urlsplit(u).path.rsplit("/", 1)[-1]} for u, t in sorted(found.items())]
    return links, len(ignored - set(found))


def discover_pages(text: str, base_url: str, cfg: dict) -> list[dict]:
    """Bounded same-origin navigation to regulatory index pages, not arbitrary permit records."""
    out={}
    keys=('הנחיות מרחביות','מדיניות תכנון','תקנות','חוקי עזר','תכניות בניין עיר','תוכניות בניין עיר','תכנון ובניה','תכנון ובנייה','מידע תכנוני','planning','guidelines','regulations')
    for _,href,inner in ANCHOR.findall(text):
        u=canonical(urljoin(base_url,htmllib.unescape(href).strip()));p=urlsplit(u)
        if p.scheme!='https' or host(u)!=host(base_url) or len(u)>950 or u==base_url: continue
        if p.path.lower().endswith(tuple('.'+x for x in cfg['document_extensions'])): continue
        label=_clean(inner)
        if any(k in (label+' '+p.path).lower() for k in keys): out[u]={'url':u,'text':label[:400]}
    return list(out.values())[:30]
