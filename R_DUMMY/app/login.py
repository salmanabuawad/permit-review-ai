"""App login: accounts managed in the app (users.py, scrypt), or the legacy administrator in an htpasswd file (Apache apr1-md5 hashes), then a signed session
cookie. Replaces the browser's basic-auth popup.

* credentials: BBP_LOGIN_HTPASSWD (default <storage>/_keys/login.htpasswd, mode 600) — the same file format nginx uses;
  the app never stores or logs a password
* session: "user|expiry" signed with HMAC-SHA256 (key BBP_SESSION_KEY or a 600 file <storage>/_keys/session.key); sent
  as an HttpOnly, Secure, SameSite=Lax cookie; lifetime BBP_SESSION_HOURS (default 12)
* throttling: after 5 failed attempts from one address, 5 minutes of refusals
"""
from __future__ import annotations

import hashlib
import json
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

from .config import settings

COOKIE = "bbp_session"
ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
MAX_FAILS, LOCK_S = 5, 300
_fails: dict[str, list[float]] = {}
_lock = threading.Lock()


# ------------------------------------------------------------------ apr1-md5 (Apache htpasswd -m)

def _to64(v: int, n: int) -> str:
    out = ""
    for _ in range(n):
        out += ITOA64[v & 0x3F]
        v >>= 6
    return out


def apr1(password: str, salt: str) -> str:
    pw, magic, salt = password.encode(), b"$apr1$", salt[:8].encode()
    ctx = pw + magic + salt
    fin = hashlib.md5(pw + salt + pw).digest()
    for i in range(len(pw), 0, -16):
        ctx += fin[:min(16, i)]
    i = len(pw)
    while i:
        ctx += b"\0" if i & 1 else pw[:1]
        i >>= 1
    fin = hashlib.md5(ctx).digest()
    for i in range(1000):
        c = (pw if i & 1 else fin) + (salt if i % 3 else b"") + (pw if i % 7 else b"") + (fin if i & 1 else pw)
        fin = hashlib.md5(c).digest()
    f = fin
    h = "".join(_to64((f[a] << 16) | (f[b] << 8) | f[c], 4)
                for a, b, c in ((0, 6, 12), (1, 7, 13), (2, 8, 14), (3, 9, 15), (4, 10, 5)))
    h += _to64(f[11], 2)
    return f"$apr1${salt.decode()}${h}"


def htpasswd_path() -> Path:
    return Path(os.environ.get("BBP_LOGIN_HTPASSWD") or Path(settings.storage_dir) / "_keys" / "login.htpasswd")


def check_password(username: str, password: str, path: Path | None = None) -> bool:
    p = path or htpasswd_path()
    if not p.exists() or not username or not password:
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        user, _, h = line.strip().partition(":")
        if user == username and h.startswith("$apr1$"):
            salt = h.split("$")[2]
            return hmac.compare_digest(apr1(password, salt), h)
    return False


# ------------------------------------------------------------------ session

def _key() -> bytes:
    env = os.environ.get("BBP_SESSION_KEY")
    if env:
        return env.encode()
    p = Path(settings.storage_dir) / "_keys" / "session.key"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32))
        p.chmod(0o600)
    return p.read_text().strip().encode()


def make_session(user_id: str, hours: float | None = None) -> str:
    iat = int(time.time() * 1000)                                   # milliseconds
    exp = int(time.time() + 3600 * (hours or float(os.environ.get("BBP_SESSION_HOURS", "12"))))
    body = f"{user_id}|{iat}|{exp}"
    return body + "|" + hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()


def read_session_full(token: str | None) -> tuple[str, int] | None:
    """(user id, issued-at) of a valid, unexpired session, else None. Tokens from before issue times were recorded
    count as issued at 0, so a password reset or deactivation voids them too."""
    try:
        head, exp, sig = (token or "").rsplit("|", 2)
    except ValueError:
        return None
    good = hmac.new(_key(), f"{head}|{exp}".encode(), hashlib.sha256).hexdigest()
    try:
        if not hmac.compare_digest(good, sig) or int(exp) < time.time():
            return None
        user_id, _, iat = head.partition("|")
        return user_id, int(iat or 0)
    except ValueError:
        return None


def read_session(token: str | None) -> str | None:
    """The user id of a valid, unexpired session, else None."""
    got = read_session_full(token)
    return got[0] if got else None


# ------------------------------------------------------------------ throttling

def throttled(addr: str) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _fails.get(addr, []) if now - t < LOCK_S]
        _fails[addr] = recent
        return len(recent) >= MAX_FAILS


def record_failure(addr: str) -> None:
    with _lock:
        _fails.setdefault(addr, []).append(time.time())


def clear_failures(addr: str) -> None:
    with _lock:
        _fails.pop(addr, None)


def resolve_login_user(username: str, legacy_user_id: str) -> str | None:
    """Optional server-only username→User.id map. Invalid configuration fails closed.

    No client-supplied municipality or user ID is trusted. Existing single-account
    installations remain compatible only when the map is not configured.
    """
    raw = os.environ.get("BBP_LOGIN_USER_MAP")
    if raw is None:
        return legacy_user_id
    try:
        mapping = json.loads(raw)
        if not isinstance(mapping, dict):
            return None
        uid = mapping.get(username)
        return uid if isinstance(uid, str) and uid else None
    except (ValueError, TypeError):
        return None
