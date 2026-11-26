# Development Backlog (prioritised) and Risk Register

Priority: P1 (next), P2 (this phase), P3 (later). Size: S (≤ 1 day), M (≤ 1 week), L (> 1 week).

| Id | Item | Value | P | Size | Depends |
|---|---|---|---|---|---|
| B-02 | Cache the run summary by evidence fingerprint and prompt / model version (**done**) | about 90 % less time on unchanged re-runs | P1 | S | — |
| B-01 | Split `main.py` into routers per module, no URL change (**done**) | maintainability | P1 | M | — |
| B-03 | Rules: per-rule fixtures and validation gate (**done**, 5 rules so far); fixtures for every rule; immutable `rule_versions` history. Two layers kept (git catalogue + per-authority DB), see REGULATORY_ENGINE.md | safe rule edits | P1 | M | — |
| B-04 | Clause model and jurisdiction hierarchy; migrate passages, drafts and uploads | Regulation360 base | P1 | L | — |
| B-05 | Embeddings (e5-small, server CPU) + hybrid retrieval + tenant-keyed index; benchmark first | retrieval accuracy | P2 | M | B-04 |
| B-06 | Unified job queue (claim + lease) for all background work; job dashboard | reliability | P2 | M | — |
| B-07 | Fetch committee candidate sources into snapshots (crawler) | pre-built knowledge for 131 committees | P1 | M | probe done |
| B-08 | AI gateway: model registry, prompt registry, schema validation, task router, injection hardening | cost, safety | P2 | M | — |
| B-09 | PDG v1: nodes and edges from the derivation cache and rule evaluations; invalidation; revision report | incremental review | P2 | L | B-03 |
| B-10 | Finding schema: rule version, methodology, confidence, drawing / page / entity reference | traceability | P2 | M | B-03 |
| B-11 | XPLAN live verification through the crawler; PostGIS parcels and plan boundaries | applicability | P2 | M | — |
| B-12 | Safe archive and document parsing sandbox | security | P2 | M | — |
| B-13 | Per-account throttling, TOTP for administrators | security | P2 | S | — |
| B-14 | Professional feedback engine (correction becomes a regression candidate; approval before shared change) | continuous improvement | P2 | M | B-10 |
| B-15 | Hebrew terminology ontology, admin-editable | retrieval, classification | P2 | M | B-04 |
| B-16 | Model evaluation: Hebrew planning benchmark (questions answered by professionals) | model choice | P2 | L | expert time |
| B-17 | Architect360 workspace | prevention | P3 | L | B-03, B-09 |
| B-18 | Process360 workflow engine | lifecycle | P3 | L | — |
| B-19 | Building360 passport (PostGIS, bitemporal) | reuse of property context | P3 | L | B-11 |
| B-20 | Management dashboards (stages, waiting time, bottleneck root causes) | management | P3 | M | B-18 |
| B-21 | English UI (i18n) alongside Hebrew RTL | reach | P3 | M | — |

## Risk register

| Id | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | Small validation corpus means accuracy cannot be demonstrated | high | high | collect consented cases per authority; keep blind / known splits |
| R-02 | gov.il and mavat block automation | high | medium | operator-read lists, authorised uploads, XPLAN REST |
| R-03 | Single 6 GB GPU limits drawing reading throughput | high | medium | deterministic geometry first; read only changed drawings; hardware plan |
| R-04 | Vendor systems (BarTech, Complot, רישוי זמין) have no agreed interface | medium | high | public pages only; seek agreements |
| R-05 | Incremental reuse hides a change (incomplete dependencies) | medium | high | completeness rule, full-review fallback, T-INC parity tests |
| R-06 | Regulatory interpretation error presented as fact | medium | high | provenance classes, professional approval, conflicts blocked from external reports |
| R-07 | No application-level backups (owner's decision) | medium | high | confirm the server backup policy; document recovery |
| R-08 | Scope of Permit360 outruns delivery capacity | high | medium | phase gates; ship Review360 / Regulation360 value first |
| R-09 | Licensing / IP terms of models and tender (docs/06) | medium | medium | licence register per model; legal review |
| R-10 | Shared server hosts other applications | medium | medium | resource limits per service; separate DB roles (done) |
