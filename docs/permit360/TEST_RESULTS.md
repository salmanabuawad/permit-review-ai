# Test results (2026-11-26, commit at time of writing: see DEPLOYED_COMMIT)

| Suite | Result |
|---|---|
| Full suite, SQLite (developer machine) | 415 passed, 9 skipped |
| Full suite, PostgreSQL 16 (server, `BBP_TEST_DATABASE_URL`), validation-data tests deselected (data kept off the server) | 379 passed, 11 skipped, 34 deselected |
| Real embedding model (server) | ranks the right Hebrew passage first |
| Frontend | `tsc --noEmit` clean; production build OK |

New test modules in this build: test_users, test_committees, test_committee_docs, test_embeddings, test_hierarchy,
test_ai_registry, test_finding_schema, test_pdg, test_feedback, test_architect, test_workflow, test_building,
test_construction, test_rule_fixtures, test_summary_cache, test_regulatory_completion.

Skipped tests: validation cases not present in the environment, and the real-model test where the model is absent.
