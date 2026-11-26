"""Derivation cache (V9 §Output: cache per SHA-256 + parser/rule/algorithm version + jurisdiction + revision).

Two scopes:
  document  key = sha256(file) + algorithm + version. A document shared by several applications (the same survey,
            the same approval letter) is parsed once and reused.
  case      key = the above + jurisdiction + application revision + the SHA-256 of every input it depends on.

A new file, a new algorithm version, another jurisdiction or a new revision gives a new key — stale outputs are never
returned. `invalidate(sha)` removes a file's document derivatives and every case-level result that depended on it.
Hit / miss counts are kept per process (`stats()`) for the run metrics.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DerivationCache

_stats = {"hits": 0, "misses": 0}


def make_key(scope: str, algorithm: str, version: str, sha256: str, jurisdiction: str = "", revision: str = "",
             depends_on: list[str] | None = None) -> str:
    body = [scope, algorithm, str(version), sha256, jurisdiction or "", revision or "", sorted(depends_on or [])]
    return hashlib.sha256(json.dumps(body).encode()).hexdigest()


def get_or_compute(s: Session, *, algorithm: str, version: str, sha256: str, compute: Callable[[], dict],
                   scope: str = "document", jurisdiction: str = "", revision: str = "",
                   depends_on: list[str] | None = None) -> tuple[dict, bool]:
    """(output, hit). `compute` runs only on a miss; its output must be JSON-serialisable."""
    if scope not in ("document", "case"):
        raise ValueError(scope)
    if scope == "document" and (jurisdiction or revision):
        raise ValueError("document-scope derivatives must not depend on jurisdiction or revision")
    key = make_key(scope, algorithm, version, sha256, jurisdiction, revision, depends_on)
    row = s.get(DerivationCache, key)
    if row is not None:
        row.hits = (row.hits or 0) + 1
        _stats["hits"] += 1
        return row.output, True
    out = compute()
    _stats["misses"] += 1
    s.add(DerivationCache(key=key, scope=scope, algorithm=algorithm, algorithm_version=str(version),
                          input_sha256=sha256, jurisdiction=jurisdiction or "", revision=revision or "",
                          depends_on=sorted(set((depends_on or []) + [sha256])), output=out, hits=0))
    s.flush()
    return out, False


def invalidate(s: Session, sha256: str) -> int:
    """Remove every derivative of a file and every case-level result that used it. Returns rows removed."""
    n = 0
    for row in list(s.scalars(select(DerivationCache))):
        if row.input_sha256 == sha256 or sha256 in (row.depends_on or []):
            s.delete(row)
            n += 1
    s.flush()
    return n


def stats(reset: bool = False) -> dict:
    out = dict(_stats)
    if reset:
        _stats.update(hits=0, misses=0)
    return out
