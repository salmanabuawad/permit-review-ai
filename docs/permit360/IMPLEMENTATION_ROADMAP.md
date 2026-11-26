# Implementation Roadmap

Principle: the working system stays live. Each step is a tested, deployable increment: a forward migration tested on
a copy of live data, regression tests passing on PostgreSQL, and a release note.

## Phase 1: Core intelligence (now)

| Step | Delivers | Status |
|---|---|---|
| 1.0 | PostgreSQL, user management, committee register and site probe, Permit360 assessment | **DONE 2026-11-26** |
| 1.1 | Split `main.py` into module routers (no URL changes) | **DONE 2026-11-26** (`app/api/`: identity, cases, rules, monitor, platform; 97 routes identical) |
| 1.2 | Summary cache by evidence fingerprint (largest measured win) | **DONE 2026-11-26** (live gain to be measured on the next unchanged re-run) |
| 1.3 | Rules: per-rule fixtures + validation gate; `rule_versions` history | **DONE 2026-11-26** (fixtures on 5 rules so far; more to add) |
| 1.4 | Clause model and hierarchy | **DONE 2026-11-26** for committee sources (hierarchy, terminology, clauses, scoped search); curated YAML passages / uploads into clauses: next |
| 1.5 | e5-small embeddings on the server CPU (approved) plus hybrid retrieval; Hebrew retrieval benchmark | embeddings + hybrid search **DONE**; benchmark pending a question set |
| 1.6 | Fetch committee candidate sources into snapshots and clauses (crawler) | snapshots + text **DONE 2026-11-26**; clause structure with 1.4 |
| 1.7 | AI gateway: model registry, prompt registry, response cache, task router | **DONE 2026-11-26** (validation per model waits for the benchmark) |
| 1.8 | Finding schema normalised (rule version, methodology, confidence, drawing reference) | **DONE 2026-11-26** (read model + accuracy gates; external report unchanged) |

## Phase 2: Preventive intelligence

**Status 2026-11-26:** PDG v1 + revision report, professional feedback engine + regression cases, Architect360 workspace — DONE. XPLAN live verification — open (REMAINING_BLOCKERS #4).

**PDG v1 + revision report DONE 2026-11-26** (rule-level inputs exact; document-level dependencies coarse).

PDG v1 (file → derivation → fact → evaluation → finding), incremental review with a revision report, drawing version
comparison (geometry fingerprints), the professional feedback engine (corrections become regression candidates),
Architect360 workspace (the same engine on unsubmitted designs), and XPLAN live verification.

## Phase 3: Permit lifecycle

**Status 2026-11-26:** Process360 workflow (templates, tasks, SLAs, escalation, bottlenecks), Building360 passport (bitemporal, standing, sources), management dashboard — DONE. External integrations — blocked (REMAINING_BLOCKERS #5).

Process360 workflow templates, tasks, SLAs and escalation; Building360 passport (property, building and unit model,
bitemporal facts, import of the lot ledger); management dashboards with root-cause views; integrations as agreements
allow.

## Phase 4: Construction intelligence

**Status 2026-11-26:** inspections base (milestones, approved vs observed, passport, photos, inspector role) — DONE. Mobile, LiDAR / point clouds, BIM — later.

Construction360: inspections, a mobile inspection app, approved-versus-observed comparison, BIM / IFC, point clouds.

## Dependencies

1.3 before 1.8 and the PDG; 1.4 before 1.5 and 1.6; 1.2 needs nothing (do it first); Architect360 needs 1.3 and the
PDG; Building360 needs PostGIS parcels (XPLAN or GIS source).
