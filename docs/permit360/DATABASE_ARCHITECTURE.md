# Database Architecture

## Today (IMPLEMENTED, 2026-11-26)

- **Engine:** PostgreSQL 16, database `permit_review` on the server's `16-main` cluster, with extensions `vector`
  0.6, `postgis` 3.4 and `pg_trgm`.
- **Access:** Unix-socket peer authentication. The app connects as role `permit`; the crawler connects as
  `permit-crawler`, a member of `permit`. No database password exists.
- **Schema:** Alembic migrations 0001–0010, 33 tables, moved from SQLite with `scripts/sqlite_to_postgres.py` (row
  counts and audit chains compared). The SQLite file is kept frozen as a rollback.
- **Tests:** the suite runs on both PostgreSQL (`BBP_TEST_DATABASE_URL`) and SQLite.

Current tables by area:

| Area | Tables |
|---|---|
| identity | municipalities, users, authority_memberships, login_accounts |
| cases | permit_cases, case_files, cad_entities, extracted_fields, document_classifications, import_batches, processing_jobs |
| review | check_runs, findings, review_attestations, committee_decisions, planning_comments, learning_records |
| rules | rule_definitions, rule_approvals, rule_drafts |
| knowledge | source_crawls, source_documents, source_snapshots, source_references, candidate_passages, regulatory_entries, parcel_plan_discovery |
| national | planning_committees, committee_settlements |
| platform | audit_events, inference_costs, ai_policies, derivation_cache |

## Target additions (each one a forward migration, applied to a live-data copy first)

| Table | Purpose | Reuses |
|---|---|---|
| `jurisdictions` | NATIONAL / DISTRICT / PLANNING_COMMITTEE / LOCAL_AUTHORITY / STATUTORY_PLAN / PROPERTY / APPLICATION nodes | planning_committees, municipalities |
| `regulatory_documents`, `regulatory_document_versions` | one row per official document, one per immutable version | source_documents / source_snapshots: extended in place, not duplicated |
| `regulatory_clauses` | clause tree (parent, number, page, original text, normalised text, topics, components, scope, dates, verification) | candidate_passages becomes the extraction stage |
| `clause_embeddings` | `vector(384)` per clause and model version; a separate index per model | — |
| `regulatory_relationships` | REFERENCES, DEFINES, AMENDS, SUPERSEDES, EXCEPTION_TO, APPLIES_TO, CONFLICTS_WITH, COMPLEMENTS, DEPENDS_ON | — |
| `rule_versions` | immutable executable versions (see REGULATORY_ENGINE.md) | rule_definitions history |
| `regulatory_conflicts` | classified pairs, status and resolution by a professional | V10 conflict detection |
| `pdg_nodes`, `pdg_edges` | Permit Dependency Graph | derivation_cache |
| `parcels`, `plan_boundaries` | PostGIS geometry (EPSG:2039), validity periods, source | regulatory_entries geometry |
| `properties`, `buildings`, `units`, `property_events` | Building360 passport with bitemporal validity | lot ledger YAML (import) |
| `workflow_templates`, `workflow_instances`, `tasks` | Process360 | case statuses |
| `benchmark_results`, `review_check_results` | measured performance and per-check results | check_runs.summary |
| `terminology` | Hebrew regulatory ontology (synonyms, spellings, distinct concepts), extendable by admins | knowledge.py prefixes |

## Principles

- **Tenant isolation.** Every tenant-owned row has `tenant_id`, and every query filters by it at the service layer.
  National rows use a shared scope and are read-only to tenants. Embeddings and cache entries carry the tenant id in
  their key. Row-level security can be added later as defence in depth.
- **Immutability.** Source versions, rule versions, locked runs and audit events are never updated in place.
- **Temporal queries.** `valid_from` / `valid_until` on regulations and property facts, plus `recorded_at`, give
  as-of reconstruction.
- **Indexes.** Use B-tree on `(tenant_id, …)`, GIN with trigram on normalised text, GiST on geometry, and exact vector
  search first. Add HNSW only after a benchmark shows a gain without loss of recall.
- **Backups.** The owner declined application-level backups (2026-11-26). Recovery currently relies on server-level
  arrangements; this is recorded as risk R-07.
