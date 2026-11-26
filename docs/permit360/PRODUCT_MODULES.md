# Product Modules — inventory, gaps and mapping to existing code

Legend: **I** implemented · **P** partial · **—** proposed (nothing built).

## Existing functionality inventory (by module)

| Capability | State | Code / data |
|---|---|---|
| Whole-request import (PDF split, רישוי זמין form fields with citations) | I | `backend/app/batch_import.py`, `pages/ImportCases.tsx` |
| Document typing (rules then local AI), attachments, extracted fields | I | `backend/app/intake/*` |
| PDF / DWG / DXF / Excel / DWFX / DWF ingest | I (no OCR) | `backend/app/ingest/*`, `agent/dwfx_convert.py`, `agent/dwf_legacy.py` |
| Area, floor, elevation geometry from drawings | P | `agent/area_geometry.py`, `floor_geometry.py`, `elevation_geometry.py` |
| Vision reading of drawing labels and tables | P (slow) | `agent/drawing_reader.py` |
| CAD viewer and sheet viewer with finding selection | P | `components/CadViewer.tsx`, `SheetViewer.tsx` |
| Executable rules, operators, conditions, severity, legal level | I | `rules/engine.py`, `knowledge/rules/*.yaml` |
| Measurement-first evidence (declared vs measured, uncertainty) | I | `rules/evidence.py`, `units.py`, `geometry.py` |
| Applicable regulation by date, plan, lot, use | P | `rules/applicability.py` |
| Licensing route validation | I | `rules/route.py`, docs/10 |
| Reliefs / deviation regulations | P | `rules/relief.py`, docs/13 |
| Coverage inventory and decision gating | I | `coverage.py`, `knowledge/coverage/required_checks.yaml` |
| Rule authoring with versions and approvals (DB) | I (0 rows live) | `RuleEditor.tsx`, `rule_definitions`, `rule_approvals` |
| Source monitor (crawl, snapshots, drafts) | I | `source_monitor/*`, `crawler_worker.py` |
| Upload of regulations as unverified knowledge | I | `source_monitor/service.py::ingest_upload` |
| Verified regulatory registry, scope resolution, limit conflicts | P (0 entries) | `regulatory.py` (V10) |
| XPLAN parcel plan discovery | P (disabled) | `plan_discovery.py` |
| KB search (BM25) and AI summary with cited passages | I | `knowledge.py`, `ai/gateway.py` |
| Defects report, Hebrew RTL PDF | I | `defects_report.py`, `reports.py` |
| Review attestations (signed) | I | `attestation.py` |
| Hash-chained audit | I | `audit.py` |
| Multi-authority workspaces, onboarding | I | `authority_onboarding.py`, `pages/Authorities.tsx` |
| National committee register and site probe | I | `committees.py`, `pages/Committees.tsx` |
| User management, logins, roles | I | `users.py`, `login.py`, `security.py`, `pages/Users.tsx` |
| Learning from committee decisions | P | `learning.py`, `pages/Learning.tsx` |
| Application version comparison | P (library only) | `lifecycle.py::ApplicationVersionComparator` |
| Derivation cache (by file hash, algorithm version) | I | `derivation_cache.py` |
| Processing jobs (durable typing / conversion) | I | `processing_jobs` table, typing worker |
| Dashboard (operational, AI metrics) | P | `pages/Dashboard.tsx`, `metrics.py` |
| Integrations page | — (all PLANNED) | `pages/Integrations.tsx`, `knowledge/integrations.yaml` |

## Mapping to the six products

### Review360: mostly implemented
Already present: classification, document inventory and completeness, drawing interpretation, geometry, area and
height checks, cross-document consistency, national and municipal rules, prioritised findings, reviewer decisions,
evidence reports, and locked versions.
Gaps: the finding schema lacks explicit `rule_version`, `confidence` and `calculation_methodology` fields (the data
exists in evidence but is not normalised); comparison with previously approved permits exists only for lot 2832/368;
drawing highlighting covers CAD only, not PDF sheets.

### Regulation360: partial
Present: rules with sources, a registry, crawling, snapshots, drafts, conflicts (V10) and the committee register.
Gaps: a single rule store; clause-structured knowledge; the hierarchy (national → district → committee → local →
plan → parcel → application); explicit precedence relationships; rule test cases per rule; regulatory change impact
analysis.

### Architect360: proposed
The same engine runs against an unsubmitted design. It needs an architect tenant type, a design workspace,
design-alternative comparison and a readiness score. The deterministic checks can be reused directly. Requires a
data-access policy (an architect sees only their own designs and public regulation).

### Process360: partial
Present: statuses, return for completion, waiting external, lock and audit.
Missing: a workflow template engine, tasks, SLAs, escalation, workload, fees and inspections.

### Building360: partial prototype
Present: the lot ledger (`knowledge/lots/hof_ashkelon_2832_368*.yaml`) and the rights files per plan.
Missing: a property / building / unit model in the database, historical snapshots, and the distinction between
approved, declared, observed and unverified.

### Construction360: proposed (phase 4)
