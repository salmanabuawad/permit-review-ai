"""Knowledge base: source register + passage store + hybrid retrieval.

POC: lexical BM25 over passages (knowledge/kb/*.yaml). The vector half of the hybrid
retrieval is an adapter (pgvector in production) that is disabled until a local embedding
model is benchmarked; search() reports which retrievers ran. Every hit carries a citation
(source_id, page, section) — a passage without a source is rejected at load time.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

import yaml

from .config import settings

TOKEN = re.compile(r"[֐-׿A-Za-z0-9/.]+")
HE_PREFIXES = ("וה", "שה", "בה", "לה", "מה", "כש", "ו", "ה", "ב", "ל", "מ", "ש", "כ")


def _norm(tok: str) -> str:
    tok = tok.lower().strip(".")
    if re.match(r"^[֐-׿]{4,}$", tok):
        for p in HE_PREFIXES:
            if tok.startswith(p) and len(tok) - len(p) >= 3:
                return tok[len(p):]
    return tok


def tokenize(text: str) -> list[str]:
    return [_norm(t) for t in TOKEN.findall(text or "")]


@lru_cache(maxsize=1)
def load_sources() -> dict:
    data = yaml.safe_load((settings.knowledge_dir / "sources.yaml").read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["sources"]}


@lru_cache(maxsize=1)
def load_passages() -> list[dict]:
    sources = load_sources()
    out = []
    for p in sorted((settings.knowledge_dir / "kb").glob("*.yaml")):
        for item in yaml.safe_load(p.read_text(encoding="utf-8")).get("passages", []):
            if item.get("source_id") not in sources:
                raise ValueError(f"passage without registered source: {item}")
            out.append(item)
    return out


@lru_cache(maxsize=1)
def _index():
    docs = [tokenize(p["text_he"] + " " + p.get("section", "")) for p in load_passages()]
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    avgdl = sum(len(d) for d in docs) / max(len(docs), 1)
    return docs, df, avgdl


def search(query: str, k: int = 5) -> list[dict]:
    docs, df, avgdl = _index()
    passages = load_passages()
    sources = load_sources()
    q = tokenize(query)
    n = len(docs)
    k1, b = 1.5, 0.75
    scored = []
    for i, d in enumerate(docs):
        s = 0.0
        for t in q:
            f = d.count(t)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avgdl))
        if s > 0:
            scored.append((s, i))
    scored.sort(reverse=True)
    hits = []
    for s, i in scored[:k]:
        p = passages[i]
        src = sources[p["source_id"]]
        hits.append({**p, "score": round(s, 3), "source_title_he": src["title_he"], "url": src.get("url"),
                     "verification": src.get("verification"), "retrievers": ["bm25"]})
    return hits
