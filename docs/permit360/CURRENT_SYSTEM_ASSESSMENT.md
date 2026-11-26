# Current System Assessment — Permit Review AI (basis for KORTEX Permit360)

Date: 2026-11-26 · Deployed commit at assessment: `e483c19` · Live: https://permit.kortexd.com

Legend used in every Permit360 document: **IMPLEMENTED** (in production code, tested) · **PARTIAL** (exists, with stated
gaps) · **PROPOSED** (design only, nothing built).

## 1. What runs today

| Layer | Technology | Where | State |
|---|---|---|---|
| Web UI | React + TypeScript (Vite), Hebrew RTL, 15 pages | app server 185.229.226.37, nginx | IMPLEMENTED |
| API | Python, FastAPI, SQLAlchemy, one process (gunicorn + uvicorn worker) | app server, user `permit` | IMPLEMENTED |
| Database | PostgreSQL 16 (`permit_review`, extensions vector / postgis / pg_trgm), 33 tables, Alembic 0001–0010 | app server, socket + peer auth | IMPLEMENTED (moved from SQLite 2026-11-26) |
| Crawler | separate process `app.crawler_worker`, OS user `permit-crawler`, nftables egress limited to public 80/443 | app server | IMPLEMENTED |
| Local AI | llama.cpp router (one model on an RTX 3050 6 GB) + relay agent; drawing reader (Ministral 3 8B vision) | user's PC, reached through an outbound relay | IMPLEMENTED |
| Storage | local content-addressed files (`storage/`), originals kept, hashes recorded | app server | IMPLEMENTED |

## 2. Functional inventory (see `CURRENT_FUNCTIONALITY_INVENTORY` table in PRODUCT_MODULES.md for the per-module map)

**Intake and documents — IMPLEMENTED.** Batch import of whole requests (`batch_import.py`): splits multi-request PDFs,
reads the רישוי זמין form number and declared fields with page citations; document typing by rules then local AI
(`intake/`), attachments, classification records, extracted fields with source spans. Formats: PDF, DWG/DXF (`ingest/cad.py`),
DWFX/DWF (converted on the AI PC: `agent/dwfx_convert.py`, `dwf_legacy.py`), Excel. **Gap:** no OCR for scanned pages.

**Drawing analysis — PARTIAL.** On the AI PC: `area_geometry.py`, `floor_geometry.py`, `elevation_geometry.py`
(deterministic geometry from converted drawings) and `drawing_reader.py` (vision model reads labels and tables from
close-ups). Results are cached by file SHA-256. **Gaps:** reading is slow (measured 135 s to 31 min per drawing on the
6 GB GPU), coverage of drawing types is uneven, no entity-level fingerprints, no IFC.

**Rules engine — IMPLEMENTED, two stores.** `rules/engine.py` (operators, conditions, severities, legal level rank,
conflict detection, ruleset hash), `rules/evidence.py` (1,073 lines: measurement-first evidence, declared vs measured),
`rules/applicability.py` (applicable-regulation resolver by date, plan, lot, use), `rules/route.py` (licensing routes),
`rules/relief.py` (requested reliefs / deviation regulations 2002), `rules/spatial.py`, `derived.py`, `components.py`.
Rules live in YAML (`knowledge/rules/*.yaml`: Hof Ashkelon 33, Bnei Brak 19, internal QA 19, demo 4) **and** in the
`rule_definitions` table (rule editor, versions, approvals; 0 rows live). Two stores is a weakness (see §4).

**Coverage and decision gating — IMPLEMENTED.** `coverage.py` + `knowledge/coverage/required_checks.yaml`: families of
required checks; "no defects" only when every family is complete (and, since V10, never while regulatory coverage is
unproven). Reports count external lines, not whole findings.

**Reports — IMPLEMENTED.** Hebrew RTL defects report (PDF), external vs internal findings, neutral wording.

**Regulatory knowledge — PARTIAL.** 265 registered sources (`knowledge/sources.yaml`, `sources.d/`), 50 curated KB
passages searched with BM25 (`knowledge.py`, vector half disabled), source monitor (crawl official registers, ETag /
SHA-256 change detection, versioned snapshots, numeric clause drafts — 16 documents, 188 drafts live), uploads indexed
as unverified candidate passages, verified regulatory registry with exact-quote check and limit-conflict detection
(V10, 0 entries live), XPLAN plan discovery (written, disabled). **Gaps:** no clause-structured chunking, no embeddings,
curated knowledge split between YAML and DB, no national/district/committee hierarchy in the store.

**Multi-authority — IMPLEMENTED.** Workspaces per authority, memberships (revocable), `X-Authority` per browser tab,
per-authority colour, authority onboarding (official-directory discovery; gov.il blocks automated access), national
register of all 131 planning committees with site probe (vendor, request-search system, candidate sources).

**Users and security — IMPLEMENTED.** App login (scrypt accounts in DB + legacy htpasswd), user management per
authority, 7 roles × permission map, signed sessions with revocation, throttling, hash-chained audit log per authority,
signed review attestations, crawler isolation.

**Learning — PARTIAL.** Committee decisions loaded per case → compared by topic (confirmed / missed / not raised) →
`committee_reason` rule drafts that need administrator approval; precedents by plan / block; rule statistics. The
decision is never an engine input (blind-test hygiene).

**Workflow — PARTIAL.** Case statuses (in review, returned for completion, waiting external, approved / locked) and a
locked-version mechanism; no configurable workflow engine, SLAs or tasks.

**AI gateway — PARTIAL.** `ai/gateway.py`: providers (local relay, local BM25, template fallback), per-tenant AI
policy, token / latency / cost recording (`inference_costs`), no-cloud default. **Gaps:** no model registry, no
task router, no prompt registry with versions, no response cache for the run summary.

## 3. Measured baseline (live runs, 2026-11-26, Hof Ashkelon / Zikim cases)

| Metric | Value | Source |
|---|---|---|
| Review run wall time | 26.8–50.7 s (one outlier 102 s with model unavailable) | `check_runs.summary.metrics` |
| Of which LLM summary | 24.8–47.4 s (≈ 94 %) | same |
| Deterministic part (documents + rules) | ≈ 2–3.5 s CPU | same |
| Tokens per run (summary only) | ≈ 5,200–5,500 in / 240–480 out | same |
| Derivation cache | 34–35 hits, 0 misses per re-run | same |
| Drawing reading (one-time per file) | 135 s – 1,861 s on the AI PC | file ingest reports |
| Live volume | 3 cases, 107 files, 1,071 findings, 21 runs | database |

Conclusion: the deterministic engine is already fast; the cost is the unconditional LLM summary on every run and the
one-time drawing reading. Caching the summary by its inputs and reading only changed drawings are the largest wins.

## 4. Weaknesses and duplication

1. ~~Two rule stores~~: on closer reading these are deliberate layers (a git-reviewed shared catalogue plus each authority's edits). The real gaps were per-rule tests (now added) and an immutable version history (open).
2. **Knowledge split** — curated YAML passages, source-monitor drafts, candidate passages and the V10 registry are
   four parallel structures without a common clause model or hierarchy.
3. **API monolith in one file** — `main.py` ≈ 1,600 lines, `services.py` ≈ 900 lines. Target: routers per module.
4. **No dependency graph** — the derivation cache is keyed by file hash only; a new run re-evaluates every rule and
   re-generates the summary even when nothing changed.
5. **LLM summary on every run** with no cache (≈ 94 % of run time).
6. **Drawing reading throughput** — a single 6 GB GPU shared by all models.
7. **Audit chain forks** (3, from concurrent writes on SQLite on 2026-11-26) — fixed for PostgreSQL with an advisory
   lock; the historical forks are documented, not rewritten.
8. **Validation corpus is small** — one blind case (20210885), one known-outcome case (20221189), one development
   case (20260265), three live Zikim cases; Haifa / Beit Shemesh requests not yet uploaded. No accuracy figure can be
   claimed yet.
9. **External sources** — gov.il refuses automated access; mavat is a JavaScript app; XPLAN untested live.

## 5. Work per authority (preserved)

| Authority | What exists | State |
|---|---|---|
| Bnei Brak | tender analysis (`docs/00`), plan family בב/105 sources and rule candidates, 19 rules | rules await source documents (G1 in docs/00) |
| Hof Ashkelon | 33 rules, plan rights files, lot 2832/368 ledger, 3 live cases (Zikim), decided-case evaluation (docs/12) | most complete |
| Haifa / Beit Shemesh | authorities created, linked to their committees; recheck reports exist outside the system; Beit Shemesh spatial guidelines found by the probe | requests to be uploaded |

## 6. Unresolved questions

- Official committee codes (not in the Planning Administration list) — source needed.
- Licensing-regulation transition provisions and route lists (docs/00 G6).
- Access terms for רישוי זמין, BarTech and Complot data beyond their public pages.
- Professional owner for rule approval per authority.
