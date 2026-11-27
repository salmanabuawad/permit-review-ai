# Performance and Cost: baselines and measurement plan

## Baseline (measured on live runs, 2026-11-26; Permit Review AI V10)

| Metric | Value | Conditions |
|---|---|---|
| review run, wall time | 26.8 / 27.9 / 28.8 / 29.4 / 30.6 / 33.4 / 50.7 s | 3 Hof Ashkelon (Zikim) cases, warm derivation cache |
| of which local LLM summary | 24.8–47.4 s (≈ 94 %) | ministral-class model on RTX 3050 6 GB through the relay |
| document text step | 0.74–0.95 s | |
| CPU time | 1.8–3.4 s | |
| tokens per run | 5,166–5,503 in, 238–481 out | summary only; all other steps use no LLM |
| AI cost per run | 0 ₪ (local) | electricity not measured |
| derivation cache | 34–35 hits, 0 misses per re-run | |
| drawing reading, one-time per drawing | 135 s – 1,861 s | AI PC; vision model; cached by file hash |
| model unavailable | 102 s, template fallback | one run |

There is no accuracy baseline yet: the corpus is too small to report precision or recall. 20210885 has a frozen blind
result (`validation/results/20210885.*`); see docs/09 and docs/12 for the case-level evaluations.

## Metrics to collect per run (most already recorded in `check_runs.summary.metrics`)

| Metric | Recorded today? |
|---|---|
| wall time, CPU time, document text time | yes |
| LLM provider, outcome, tokens in / out, latency, cost | yes |
| derivation cache hits / misses | yes |
| AI PC drawing time, model, calls per file | yes |
| regulatory discovery and retrieval time | no |
| reused vs recomputed results (PDG) | no (no PDG yet) |
| deterministic vs AI share of checks | no |
| peak memory, GPU utilisation | no |
| defect precision / recall, unresolved checks, independent measurement coverage | coverage yes; precision / recall need ground truth |

## Benchmark procedure

1. Fixed corpus: the validation cases plus consenting live cases, frozen inputs.
2. Cold run (empty caches, models unloaded), then warm run, then a revision run (one document changed).
3. Same hardware and model configuration; record the commit, model, quantisation and prompt versions.
4. Report absolute numbers and changes against this baseline; no improvement is claimed without a run.

## Expected first gains (targets to verify)

- Cache the summary by evidence fingerprint: an unchanged re-run should drop from about 30 s to about 3 s.
- Revision runs: only changed drawings are re-read; the gain depends on the share of drawings changed.

## Measurements after the Permit360 build (2026-11-26, live server)

| Metric | Value | Conditions |
|---|---|---|
| keyword search over committee text | median 23 ms, p95 67 ms | 8 Hebrew queries, ~16,000 pages, trigram index |
| hierarchy clause search (authority chain, synonym expansion) | median 29 ms, p95 123 ms | ~27,600 clauses cut so far |
| semantic search (e5-small, exact scan, pgvector) | median 108 ms, p95 114 ms | 6,752 vectors embedded so far (of 63,935) |
| embedding model load | 3.6 s, once per process | server CPU |
| embedding throughput | ≈ 4.4 chunks / s (≈ 256 tokens) | 2 CPU threads |
| hybrid value example | "הנחיות מרחביות מרפסות": keyword 0 hits, semantic 50 | |
| AI summary on an unchanged re-run | reused from cache (0 tokens) instead of 25–47 s | first live re-run will record `llm.cached` |
| dependency-graph parity (demo) | unchanged re-run: every rule's inputs identical, 0 violations | `test_pdg.py` |

Not yet measured: semantic latency at the full 64k vectors (exact scan grows linearly; an HNSW index only after a
benchmark shows no recall loss), Recall@K / MRR (needs a question set with expected clauses), defect precision /
recall (needs professionally verified ground truth).

## XPLAN plan discovery (2026-11-27, live, crawler process)

| Metric | Value | Conditions |
|---|---|---|
| one case, full discovery | ≈ 1.5–2 s | layer schema check + declared-plan lookup + cell geometry + intersect / within + land use |
| one plan cell per district | 0.8–1.7 s; own plan COVERS in all 6 | דרום, חיפה, ירושלים, מרכז, צפון, תל-אביב (מטה holds national plans only) |
| Zikim cell 368 (633-0723718) | 5 covering plans, 5 land-use cells | three Hof Ashkelon cases |
