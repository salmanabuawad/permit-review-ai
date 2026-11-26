"""Local multilingual embeddings (intfloat/multilingual-e5-small, ONNX, server CPU) and chunk indexing.

* Model: pinned revision with checked file hashes (models/…/PROVENANCE.json); MODEL_ID is stored with every vector,
  so vectors of different models are never compared (a model change means re-indexing, not mixing).
* Chunks: a page's text split on paragraph / sentence boundaries into ~700-character windows with overlap, so a
  requirement keeps its neighbouring condition; the original page text is untouched.
* Indexing is incremental (only chunks without a vector for MODEL_ID) and bounded per call; guidelines and plans first.
* Without the model files the search falls back to keyword retrieval and says so ("retrievers").
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import CommitteeChunk, CommitteeDocument, CommitteePassage, CommitteeSnapshot

MODEL_ID = "multilingual-e5-small@614241f"
DIM = 384
DEFAULT_DIR = "/opt/permit-review-ai/models/multilingual-e5-small/614241f622f53c4eeff9890bdc4f31cfecc418b3"
CHUNK, OVERLAP, MIN_CHUNK = 700, 120, 40
_lock = threading.Lock()
_model = None


def model_dir() -> Path:
    return Path(os.environ.get("BBP_EMBED_MODEL_DIR") or DEFAULT_DIR)


def available() -> bool:
    d = model_dir()
    return (d / "model.onnx").exists() and (d / "tokenizer.json").exists()


class _E5:
    def __init__(self, d: Path, threads: int):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        o = ort.SessionOptions()
        o.intra_op_num_threads = threads
        self.s = ort.InferenceSession(str(d / "model.onnx"), o, providers=["CPUExecutionProvider"])
        self.t = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.t.enable_truncation(512)
        self.t.enable_padding()

    def __call__(self, texts: list[str]) -> list[list[float]]:
        import numpy as np
        enc = self.t.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        h = self.s.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})[0]
        v = (h * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
        v = v / np.linalg.norm(v, axis=1, keepdims=True)
        return v.astype("float32").tolist()


def embedder(threads: int = 2):
    """The loaded model (once per process), or None when the files are absent."""
    global _model
    with _lock:
        if _model is None and available():
            _model = _E5(model_dir(), threads)
        return _model


def chunks(page: str) -> list[tuple[int, int]]:
    """(start, end) windows over the page text, cut at paragraph / sentence ends where possible."""
    t = page or ""
    out, i, n = [], 0, len(t)
    while i < n:
        end = min(n, i + CHUNK)
        if end < n:
            cut = max(t.rfind("\n", i + CHUNK // 2, end), t.rfind(". ", i + CHUNK // 2, end), t.rfind(":", i + CHUNK // 2, end))
            if cut > i:
                end = cut + 1
        if len(t[i:end].strip()) >= MIN_CHUNK:
            out.append((i, end))
        if end >= n:
            break
        i = max(end - OVERLAP, i + 1)
    return out


def vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def make_chunks(s: Session, limit: int = 2000) -> int:
    """Split passages that have no chunks yet (current document versions only)."""
    done = select(CommitteeChunk.passage_id)
    q = (select(CommitteePassage).join(CommitteeSnapshot, CommitteePassage.snapshot_id == CommitteeSnapshot.id)
         .join(CommitteeDocument, CommitteeSnapshot.document_id == CommitteeDocument.id)
         .where(CommitteeDocument.sha256 == CommitteeSnapshot.sha256, CommitteePassage.id.not_in(done)).limit(limit))
    n = 0
    for p in s.scalars(q):
        for k, (a, b) in enumerate(chunks(p.text_he)):
            s.add(CommitteeChunk(passage_id=p.id, ord=k, start=a, end=b))
            n += 1
    s.commit()
    return n


KIND_ORDER = {"guideline": 0, "plan": 1, "bylaw": 2, "procedure": 3}


def index(s: Session, batch: int = 32, max_chunks: int = 256, model=None) -> dict:
    """Embed up to max_chunks chunks that have no vector for MODEL_ID. Returns counts."""
    model = model or embedder()
    if model is None:
        return {"embedded": 0, "reason": "model not installed"}
    made = make_chunks(s)
    rows = s.execute(select(CommitteeChunk, CommitteePassage.text_he, CommitteeDocument.kind)
                     .join(CommitteePassage, CommitteeChunk.passage_id == CommitteePassage.id)
                     .join(CommitteeSnapshot, CommitteePassage.snapshot_id == CommitteeSnapshot.id)
                     .join(CommitteeDocument, CommitteeSnapshot.document_id == CommitteeDocument.id)
                     .where(CommitteeChunk.model.is_(None)).limit(max_chunks * 4)).all()
    rows.sort(key=lambda r: KIND_ORDER.get(r[2], 9))
    rows = rows[:max_chunks]
    done = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vecs = model(["passage: " + txt[c.start:c.end] for c, txt, _ in part])
        pg = s.get_bind().dialect.name == "postgresql"
        for (c, _, _), v in zip(part, vecs):
            if pg:
                s.execute(text("UPDATE committee_chunks SET model = :m, embedding = CAST(:v AS vector) WHERE id = :i"),
                          {"m": MODEL_ID, "v": vec_literal(v), "i": c.id})
            else:
                c.model, c.embedding = MODEL_ID, json.dumps(v)
        s.commit()
        done += len(part)
    return {"chunks_made": made, "embedded": done}


def semantic(s: Session, query: str, k: int = 50, committee_id: str | None = None, model=None) -> list[tuple[int, float]]:
    """(chunk_id, similarity) of the nearest chunks; exact search (no approximate index yet)."""
    model = model or embedder()
    if model is None:
        return []
    qv = model(["query: " + query])[0]
    if s.get_bind().dialect.name == "postgresql":
        sql = ("SELECT ch.id, 1 - (ch.embedding <=> CAST(:q AS vector)) AS sim FROM committee_chunks ch "
               "JOIN committee_passages p ON p.id = ch.passage_id JOIN committee_snapshots sn ON sn.id = p.snapshot_id "
               "JOIN committee_documents d ON d.id = sn.document_id "
               "WHERE ch.model = :m AND d.sha256 = sn.sha256" + (" AND d.committee_id = :c" if committee_id else "") +
               " ORDER BY ch.embedding <=> CAST(:q AS vector) LIMIT :k")
        return [(r[0], float(r[1])) for r in s.execute(text(sql), {"q": vec_literal(qv), "m": MODEL_ID, "k": k,
                                                                    **({"c": committee_id} if committee_id else {})})]
    out = []                                         # SQLite (tests): exact cosine in Python
    q = select(CommitteeChunk.id, CommitteeChunk.embedding).where(CommitteeChunk.model == MODEL_ID)
    for cid, e in s.execute(q):
        v = json.loads(e)
        out.append((cid, sum(a * b for a, b in zip(v, qv)) / (math.sqrt(sum(a * a for a in v)) or 1)))
    return sorted(out, key=lambda x: -x[1])[:k]


def rrf(*rankings: list, k: int = 60) -> list:
    """Reciprocal rank fusion of ranked id lists."""
    score: dict = {}
    for ranking in rankings:
        for r, key in enumerate(ranking):
            score[key] = score.get(key, 0.0) + 1.0 / (k + r + 1)
    return sorted(score, key=lambda x: -score[x])


def normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip())
