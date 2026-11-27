# Changelog

## 2026-11-27 — Search engines and AI tools: trilingual discovery

- The app page carries a Hebrew / English / Arabic title, description, keywords, canonical URL (permit360.kortexd.com),
  Open Graph tags and schema.org SoftwareApplication data; a `<noscript>` summary links to the about page.
- `/about.html`: a static page in Hebrew, English and Arabic describing the product for committees and for engineers
  and architects (readable without JavaScript), linked from the login page.
- `/robots.txt` (public pages open; the application, its API and the AI relay closed), `/sitemap.xml` with hreflang,
  and `/llms.txt` for AI tools. nginx serves the site's text files as UTF-8.

## 2026-11-27 — Committee roles: administrator and reviewer only

- A committee now has two roles: its administrator (מנהל/ת ועדה) and reviewers (בודק/ת). Reviewers do all the
  professional work the former roles did between them — cases, runs, findings, locking, rules (authoring and approval),
  committee sources, inspections, file deletion, assignment, audit and the management dashboard. Users, AI settings,
  crawl schedules and loading decided cases stay with the administrator. End users remain in the Pro workspace.
- Migration 0027 moves existing users: engineer, licensing manager, secretariat, inspector and external party →
  reviewer; the committee's application editors → end user (the same permissions they had). Workflow steps and stored
  templates addressed to former roles go to reviewers; overdue tasks escalate to the administrator. A row or task with
  a former role name is still read as its successor.
- Four eyes kept without role separation: a correction (override) is accepted into the regression cases by a different
  reviewer or the administrator, never by the reviewer who raised it.

## 2026-11-27 — End-user self sign-up, outgoing mail, permit360.kortexd.com

- Self sign-up for engineers and architects (migration 0026, `app/signup.py`): the login page's form creates an inactive
  end_user login in the Permit360 Pro workspace → a verification link is e-mailed (valid 48 h) → the superadmin approves
  or rejects it under Users → sign-up requests (BBP_SIGNUP=approval, the default; `open` skips approval, `off` hides it).
  The applicant is notified of the outcome by mail. The role is always end_user in the Pro workspace; the password
  policy matches administrator-created logins; three requests per address per hour, a ceiling on pending requests;
  unverified requests expire and rejected ones are deleted (the username is freed). Logging in before verification or
  approval says which step is missing, only after the correct password. Without outgoing mail, sign-up is off.
- Outgoing mail (`app/mailer.py`): SMTP from the server environment (BBP_SMTP_*), sent as info@kortexd.com — the same
  mailbox MuniFlow uses. Links in mail come from BBP_PUBLIC_URL, never from the request's Host header.
- The app now also answers on https://permit360.kortexd.com (primary; the certificate covers both names);
  permit.kortexd.com keeps working, including the AI PC's relay endpoint.
- Cadastre lookup on PostgreSQL falls back to the stored GeoJSON when a row has no PostGIS geometry (the project tests
  now pass on PostgreSQL too).

## 2026-11-27 — Permit360 Pro: dual-entry projects, jurisdiction from official boundaries, user levels

- Planning jurisdictions (migration 0025, `app/jurisdiction.py`): the Planning Administration's planning areas (310, with
  the official code CodeMT, e.g. 633 Hof Ashkelon), municipal boundaries (411) and village committees (1,785), loaded as
  versioned datasets (a refresh supersedes, never deletes) into PostGIS, EPSG:2039. Planning areas are linked to the
  committee register by exact name (222), a curated alias list (8), or a unique member municipality (13); 35 are
  district-administered; 32 have no committee in the register. All 131 committees now carry their official code(s).
- Committee discovery: the registered cadastral parcel ∩ planning areas → RESOLVED (one area covers ≥ 99.5 %),
  AMBIGUOUS (all candidates returned, never guessed), UNLINKED, UNRESOLVED; cached per parcel and dataset versions.
  Path A verifies a chosen committee (VERIFIED / MISMATCH / AMBIGUOUS). Manual selection only when official data cannot
  answer, marked MANUAL_UNRESOLVED everywhere.
- Projects (`app/projects.py`, `/api/projects…`): creation by either path (confirmation required), knowledge
  initialization (XPLAN discovery; committee probe / fetch when its knowledge base is empty or stale), the Applicable
  Regulatory Package (property, jurisdiction re-check, committee KB, plans, land use, rights from verified rights files,
  restrictions incl. §§ 77–78 notices, deposited and partial plans, requirements, missing / outdated), a nine-stage
  preparation workflow with next actions, and an engineering assistant (local model, answers only from the package and
  the committee's texts; invented numbers rejected). Authorised users upload documents to a committee's knowledge base.
  UI: "פרויקט חדש" wizard (both paths) and a "פרויקט" tab on the project.
- User levels: superadmin (platform flag, BBP_SUPERADMINS), committee admin, committee user (professional sub-roles
  keep their permissions), end user (engineers / architects in the Permit360 Pro workspace, outside every committee;
  only their own projects). Roles are validated per environment; the level shows in the top bar.
- Committee decisions: PDF protocols of 2016–2023 read (pdftotext; the 2021–2023 font maps נ to U+F8FF); decisions
  classified from the operative opening first. Hof Ashkelon: 3,697 of 3,956 items with a decision; study updated.

## 2026-11-27 — Committee decision files (protocols) and the Hof Ashkelon decisions study

- Meeting protocols (migration 0024): each meeting's archive page → its accessible decisions file (HTML, served as an
  octet-stream download) → per item: plans, designation, uses, areas, request, staff opinion (rights computation and
  reviewer notes), recommendation and decision. The interested-parties block (names) is not stored. An item with no
  decision on its page takes the file's decision (`decision_source = protocol`). Runs inside the meetings job.
- Hof Ashkelon: accessible decision files exist from mid-2023 (155 meetings); 538 decisions filled, 922 items annotated.
  Earlier meetings have only PDF protocols whose Hebrew text extracts in reversed visual order — not read yet.
- docs/permit360/HOF_ASHKELON_DECISIONS_STUDY.md (aggregates only): 1,955 decided requests, ~94 % approved; a staff
  recommendation to approve was followed in 413 of 414 cases; recurring reasons and conditions; coverage gaps.

## 2026-11-27 — National cadastre (registered parcels)

- `cadastre_parcels` / `cadastre_blocks` (migration 0023; PostGIS geometry in EPSG:2039 with GiST index) loaded from the
  Survey of Israel open data on data.gov.il by `scripts/load_cadastre.py`, through a dependency-free shapefile reader
  (`app/shapefile_reader.py`). `GET /api/cadastre/parcel?gush=&helka=`. XPLAN discovery now prefers a verified parcel,
  then the registered cadastral parcel (PARCEL_CADASTRE), then the declared plan's cell. An ambiguous parcel (several
  rows) is never guessed. The files themselves need a signed-in download from data.gov.il (Google sign-in by a person).
- Loaded live 2026-11-27: snapshot 12.8.2026, 18,689 blocks and 1,097,775 parcels (1.8 GB with the GiST index).
  Zikim check: plan cell 368 is split between parcels 2832/27 (24 % of the cell) and 2832/28 (76 %), and each parcel
  is far larger than the cell. On the registered parcels, discovery adds two partial plans the cell did not show:
  a תת"ל 100 notice under §§ 77–78 (preparation; conditions on permits) over part of parcel 27, and 633-0332759
  (public buildings for education, roads, 2016) over part of parcel 28; the declared plan 633-0723718 covers each
  parcel only partly. Which part a building stands on needs its location on the site plan.

## 2026-11-27 — Deep search of a committee; committee text in the summary; meeting record (study only)

- Deep search (`POST /api/committees/deep`, crawler job `deep`): the committee's own site breadth-first (depth 3, up to
  300 pages and 400 documents, own hosts only, no search / account pages, one request per delay), every content page
  stored as text and every linked document fetched; then the committee's online plans from XPLAN (name an exact entry
  of the plan's committee list) as one versioned document with a passage per plan, objectives included.
- Clause cutting and embedding now take the committees of authorities on the system first.
- A run's summary passages add up to 3 passages from the case committee's own fetched text (semantic, cosine ≥ 0.84),
  labelled "מאתר הוועדה — לא מאומת"; never a finding or a rule. Hybrid committee search moved to
  `committee_docs.hybrid_search`.
- Committee meeting record (migration 0022, `app/meetings.py`, crawler job `meetings`, alternating with indexing):
  meetings → items → item pages (request, reliefs, decision, outcome class). Applicant names are not stored. Study and
  validation material only — committee decisions are ground truth and never an engine input. Hof Ashkelon: 607
  meetings 2016–2026 imported from the public meeting search (run by the owner; the site's reCAPTCHA is not bypassed).

## 2026-11-27 — XPLAN plan discovery live, in the crawler

- Plan discovery is now a job of the restricted crawler process: "איתור תכניות ב־XPLAN" queues it
  (`POST /api/cases/{id}/discover-plans`), the crawler runs it, the panel follows `GET /api/cases/{id}/plan-discovery`.
  The app process never contacts XPLAN. Network use needs `BBP_XPLAN_ENABLED=true` (now set on the server).
  Migration 0021: queue state, requester, error on `parcel_plan_discovery`; an interrupted job is marked failed when
  the crawler starts.
- Per case: each declared plan as XPLAN shows it (status, stage, publication in רשומות, subtype, committee, Mavat
  link); plans whose blue line intersects the case geometry, each COVERS (the geometry lies within the plan, to within
  0.5 m) or PARTIAL; and the land-use cells that intersect it. Every plan is a candidate, never legal activation;
  XPLAN shows online plans only (coverage is never complete).
- Geometry: the verified parcel when there is one; otherwise the declared plan's land-use cell polygon from XPLAN (the
  declared lot, or the authority ledger's only cell for the block and plan), labelled as a plan cell, not a
  registered parcel. The public cadastre (GovMap) refuses the server (HTTP 403), so no parcel boundaries are fetched.
- The declared plan and its cell become passport facts (source `xplan`; APPROVED when XPLAN's status is "אישור").
- Spatial queries are POSTed: the service answers 404 to a polygon in a long query string. Verified live: the three
  Hof Ashkelon cases (cell 368 of 633-0723718: five covering plans, among them 633-0639674 deposited for objections)
  and one approved plan cell in each of the six districts (own plan COVERS in all, 0.8–1.7 s each).

## 2026-11-26 — Construction360: site inspections (base)

- `inspections` (migration 0020): per case and milestone (start, foundations, frame, roof, envelope, completion);
  results record each item's approved and observed value with a tolerance; a difference beyond it is a deviation —
  a finding for a professional, never an automatic sanction. Every observation becomes an OBSERVED fact in the
  property passport (Building360). Photos: JPEG / PNG only, ≤ 15 MB, content-addressed, optional location.
- New role "פקח/ית בנייה" (`inspector`) and permission `inspection.manage`. Case tab "פיקוח".
- Not built (later): mobile app, photogrammetry / LiDAR / point clouds, BIM comparison.

## 2026-11-26 — Management dashboard

- `GET /api/dashboard/management`, dashboard section: workflow bottlenecks per step (open, overdue, average waiting
  and working days), workload per assignee / role with overdue tasks and escalations, recurring violations across the
  latest run of each case, cases returned for completion more than once, and processing (all checks deterministic;
  AI summary calls vs reuse; tokens per run). Completion projections are not shown until there is enough process data.

## 2026-11-26 — Building360: property passport

- `properties` / `property_facts` (migration 0019): a property per block / parcel (or plan cell, when the source is
  cell-based); facts are bitemporal — valid from / to in the world, recorded / superseded in the system — so a re-sync
  never overwrites and "what did we know on date X about date Y" can be answered.
- Standing per fact: APPROVED (issued permit / certificate in the committee register; signed permit area table whose
  arithmetic closes), DECLARED (applications, declared values, pending submissions), OBSERVED (site inspections),
  UNVERIFIED (with the reason: flagged by spatial control, table that does not close). Sources: the Hof Ashkelon
  register snapshot and permit tables (knowledge/lots), cases and committee decisions.
- API: `/api/properties`, `/api/properties/{id}?as_of=&known_at=`, `/api/cases/{id}/properties`,
  `POST /api/properties/sync`. Case tab "נכס".

## 2026-11-26 — Process360: permit workflow, tasks, SLAs and escalation

- `workflow_templates` / `workflow_tasks` (migration 0018). Default template: intake → completeness → engineering,
  regulatory and external approvals in parallel → committee decision → permit conditions → permit issuance, each with
  a role and an SLA in days; an authority's administrator saves its own template (validated: keys, roles, dependencies,
  no cycles); running cases keep the tasks they started with.
- A step becomes ready when its dependencies are done; only its role (or a manager) acts on it; a legally required
  decision (committee, permit) is completed only by its role or the system administrator, with a note, and cannot be
  skipped. Due date counted from readiness; overdue tasks; escalation to the department manager past twice the SLA.
- Bottlenecks per step: open, overdue, average waiting (ready → started) and working (started → done) days.
- UI: case tab "תהליך", page "משימות" (mine / overdue).

## 2026-11-26 — Architect360: pre-submission checks of private designs

- A design is a case of kind `design` owned by its architect (migration 0017): kept out of the authority's case lists,
  dashboard and metrics, and invisible (404) to everyone but its owner and the system administrator. Permission
  `design.create` (planner, system administrator).
- `POST /api/designs`, upload through the case files endpoint, `POST /api/designs/{id}/check` runs the same engine;
  readiness = share of applicable checks that pass, blockers (violations, document gaps, declaration mismatches) with
  measured / permitted values and the recommended fix, open checks — labelled an estimate, never compliance.
  `GET /api/designs/compare?a=&b=`: per rule, better / worse / open in both.
- Page "בדיקה לפני הגשה".

## 2026-11-26 — Professional feedback engine and regression cases (Permit360 §15)

- Overriding a finding now records a classified feedback record (`feedback_records`, migration 0016): original and
  corrected result, reason, category (algorithm / measurement defect, extraction error, interpretation error, missing
  knowledge, application-specific exception, prompt deficiency), the affected rule and version, other open findings of
  the same rule in the authority's latest runs, and a regression candidate built from the exact facts the rule read
  (dependency graph). A case-specific exception never becomes a candidate.
- An approver (`rule.approve`) accepts a record into a regression case (`regression_cases`) or dismisses it; shared
  rules, prompts and algorithms are never edited by this path. `GET /api/feedback/regression` runs the current rules
  against every accepted case.
- UI: decisions (confirm / override with category and corrected result) in the case's "בקרת דיוק" tab — the findings
  list had lost its decision controls; the learning page shows feedback and the regression run (also to reviewers).

## 2026-11-26 — Permit Dependency Graph v1 and revision reports (Permit360 phase 2)

- Every run records one graph node per rule evaluation (`pdg_nodes`, migration 0015): the exact facts the engine read
  (recorded while evaluating), the rule's version and definition hash, and a fingerprint of the run's post-processing
  context (input files, declarations, drawing values, register status). The context is coarse on purpose: any
  document change counts as a change for every rule until per-document dependencies are traced.
- Parity check on every run: a rule with the same fingerprint as in the previous run but a different result is
  recorded as a missing dependency (`summary.pdg.parity_violations`) and is never reused.
- `GET /api/runs/{id}/revision`: files added / changed / removed; findings new / corrected / unchanged / newly
  unresolved / newly applicable, each with the inputs whose values changed (or the rule definition, e.g. an approval).
  Case view, tab "השוואה לגרסה קודמת".
- Measured on the demo case: an unchanged re-run — every rule's inputs identical, no parity violation.

## 2026-11-26 — Normalised findings, V11 check statuses and accuracy gates (Permit360 1.8)

- `finding_schema.py` and `GET /api/runs/{id}/findings/normalised`: every finding with measured / permitted /
  difference, method, evidence category (declared value, drawing dimension, geometric measurement, document presence),
  drawing and source references, rule version, confidence, recommended action, professional validation; the V11 check
  status (PASS, CONFIRMED_VIOLATION, DOCUMENT_INCONSISTENCY, DECLARATION_MISMATCH, DISCRETIONARY_REVIEW_REQUIRED,
  UNRESOLVED, NOT_APPLICABLE, EXECUTION_ERROR); the ten accuracy gates as PASS / FAIL / NOT_EVALUATED (temporal
  applicability, exceptions and reliefs are not modelled per finding yet and say so); coverage against the run's full
  inventory and the independent-measurement share. A violation is CONFIRMED only when every mandatory gate passes.
- Case view, tab "בקרת דיוק" (internal). The external report's logic is unchanged.

## 2026-11-26 — Model registry, prompt registry, task routing (Permit360 1.7)

- `knowledge/ai_models.yaml`: the 17 local models with source, licence, SHA-256, quantisation and host, from the AI PC's
  provenance files (three community builds marked unverified). Status IN_USE (Ministral 3 8B IQ4_XS for text and
  vision; e5-small for embeddings) or CANDIDATE; `validated_for` is empty for every model until the Hebrew planning
  benchmark passes.
- Prompt registry: a prompt's version is the hash of its exact text; every model result's trail records
  `prompt: id@version`.
- Task routing (`ai/registry.py`): deterministic work (numbers, geometry, parsing, layout) never goes to a model;
  escalation only on objective triggers (missing evidence, invalid schema, numbers not in the source, possible
  exception, inconsistent rules, unverified material defect) and only to a model validated for the task — with none,
  the item stays UNRESOLVED. AI settings page: registry, prompt versions and routing table (read-only).

## 2026-11-26 — Regulatory hierarchy, Hebrew terminology and clauses (Permit360 1.4)

- `jurisdictions` (migration 0014): IL → 6 districts → 131 committees → the system's authorities, built from the
  committee register at startup. Retrieval for an authority covers its own chain only; scopes are retrieval
  boundaries, not legal precedence.
- `terminology`: 25 concepts with their Hebrew forms (spellings, plurals, abbreviations); matching tolerates Hebrew
  prefix letters; legally different concepts stay apart (internal vs building height, main vs service area, parking vs
  covered parking). Editors (`rule.edit`) add forms; `GET/POST /api/terminology`.
- `regulatory_clauses`: fetched committee pages are cut along their legal numbering (1. / 1.1 / א. / (א) / סעיף),
  with parent, depth, offsets, verbatim text and topics; incremental, in the crawler's idle time. All UNVERIFIED.
- `GET /api/knowledge/clauses?q=` searches the authority's chain with synonym expansion; `GET /api/knowledge/hierarchy`
  shows the chain with clause counts. Authorities page: hierarchy chips and clause search.

## 2026-11-26 — Rule version history (Permit360 1.3 complete)

- `rule_versions` (migration 0013): every saved version of a rule edited in the rules screen (create, edit, delete,
  restore) is appended by a session hook on `RuleDefinition`, never updated; backfilled from current definitions.
  `GET /api/rules/{id}/versions`. Together with per-rule fixtures and the two-layer catalogue this completes 1.3.

## 2026-11-26 — Local embeddings and hybrid search (Permit360 1.5, first part)

- Model: intfloat/multilingual-e5-small (MIT), ONNX, revision 614241f, file hashes checked, provenance recorded next to
  the model (`/opt/permit-review-ai/models/…/PROVENANCE.json`); runs on the server CPU (onnxruntime 1.32, tokenizers
  0.22.1, 2 threads). Owner approval: 2026-11-26.
- Committee text is split into ~700-character windows with overlap (`committee_chunks`, migration 0012, pgvector
  `vector(384)` on PostgreSQL) and embedded incrementally by the crawler worker when it has nothing else to do
  (guidelines and plans first); every vector carries its model id, so vectors of different models are never compared.
- Search over committee text is hybrid: exact keyword and nearest-meaning chunks fused by reciprocal rank; each hit
  says what found it. Without the model files it falls back to keyword search. Exact vector search; an approximate
  index only after a benchmark.
- Measured: ≈ 4.4 chunks / s (≈ 256 tokens) on 2 CPU threads; a Hebrew sanity check ranks the right passage first.
  No retrieval benchmark yet (needs a question set with expected clauses).

## 2026-11-26 — Per-rule fixtures (Permit360 B-03, revised)

- A rule may carry `tests: [{facts, expect, note?}]`. The engine runs them on validation (`run_rule_tests`), so an edit
  in the rules screen that changes the outcome at a fixture is refused; the catalogue's fixtures run in the test
  suite. Fixtures test the rule's logic (evaluated as approved); real runs keep the approval gate.
- First fixtures: HA-633-FLOORS, UNITS-CELL, MAIN-AREA-CELL, SERVICE-AREA-CELL, BB-SG16-31.2-RAILING (boundaries,
  missing data, other plan, applicability unknown / not met).
- Decision recorded: the YAML catalogue and per-authority DB edits stay two layers (shared rules are not copied into
  every authority).

## 2026-11-26 — API split into modules (Permit360 B-01)

- `app/main.py` (≈ 1,800 lines) now only assembles the app (CORS, login gate, startup); the 95 endpoints moved
  verbatim into `app/api/` routers — identity, cases, rules, monitor, platform — with shared schemas and helpers in
  `app/api/common.py`. Route table checked identical (97 method/path pairs; no overlapping pair changed order).
  Tests replace settings through `tests.conftest.use_settings`.

## 2026-11-26 — AI summary reused when nothing changed (Permit360 B-02)

- The run's AI summary (≈ 94 % of run time, 25–47 s) is cached by the fingerprint of its exact prompt (findings,
  knowledge passages, prompt template) plus the provider configuration and authority. An unchanged re-run reuses it;
  any change in a finding, passage, prompt or model regenerates it; a template fallback (model unavailable) is never
  cached. Hits are recorded in the AI cost log as `CACHE_HIT` (no time, tokens or cost) and in run metrics
  (`llm.cached`).
- Crawler start marks committee probe / fetch jobs left running as failed (re-queue to resume).

## 2026-11-26 — Committee candidate sources fetched into searchable snapshots

- The crawler fetches each committee's candidate sources (from the site probe) into `committee_documents` /
  `committee_snapshots` / `committee_passages` (migration 0011): only the committee's own site (or its BarTech /
  Complot host), at most 40 requests per committee per run, one per second; documents linked from a source page are
  followed one level; changed documents become new versions (ETag / Last-Modified, then SHA-256); identical files are
  stored and extracted once. Text extraction of third-party PDF / Office files runs in a child process with memory,
  CPU and time limits (`safe_extract.py`). Legacy .doc / .xls and links to other sites are recorded, not fetched.
- Committees page: "קליטת מסמכי המקורות", documents with versions and pages per committee, opening a stored file, and
  search across all fetched text. Everything is marked unverified; nothing becomes a rule.

## 2026-11-26 — KORTEX Permit360: assessment and architecture (documents only)

- `docs/permit360/`: system assessment with measured baseline, functionality inventory and gaps, target architecture
  (modular monolith), database plan, Permit Dependency Graph design, executable rule schema, AI gateway, incremental
  review, knowledge strategy, integration feasibility matrix, security, testing, performance plan, roadmap, backlog
  and risk register. Every capability is marked implemented / partial / proposed; no code changed.
- Committee site probe (same day): vendor, request-search system, engineering site and candidate sources for each of
  the 131 committees, read from their public sites through the restricted crawler.

## 2026-11-26 — National register of planning committees

- All 131 local and regional committees (32 regional) from the Planning Administration's list, read 2026-11-26
  (page updated 2026-08-27), stored as published in `knowledge/committees/gov_il_local_committees.json` and loaded into
  `planning_committees` / `committee_settlements` (migration 0010): district, kind, settlements served, committee site,
  vendor (BarTech 39 / Complot 24 from the site address; 68 still unknown), engineering site, request-search system,
  sources and knowledge status. The list publishes no official committee code; the field stays empty until verified.
- Authorities of the system link to their committee by exact name (חוף אשקלון, חיפה, בית שמש, בני ברק).
- Page "מאגר ועדות ארצי": filters by district, vendor, knowledge status and settlement; platform administrators fill in
  the official code, engineering site, request-search URL and vendor. Re-import never overwrites curated values.

## 2026-11-26 — PostgreSQL (V11 phase 2)

- Live data moved from SQLite to PostgreSQL 16 (`permit_review`, extensions vector, postgis, pg_trgm) with
  `scripts/sqlite_to_postgres.py`: schema from the migrations, all 31 tables / 3,224 rows copied in one transaction,
  sequences moved on, counts and audit chains compared with the source. Socket + peer authentication: the app connects
  as role `permit`, the crawler as `permit-crawler` (member of `permit`); no database password exists.
  Rollback: the SQLite file is untouched (frozen at the move) and its URL is kept, commented, in the env file.
- Full test suite passes on PostgreSQL (`BBP_TEST_DATABASE_URL`), except tests that need validation case data, which
  is not on the server.
- Audit log: three forks found in the Hof Ashkelon chain (events 851/852 -> 848, 897-899 -> 895, 936 -> 933), all from
  concurrent background writes on 2026-11-26; every row still hashes its own content (no edits). Kept as is (append-only).
  Appends are now serialized per authority on PostgreSQL (transaction advisory lock); `audit.chain_report` tells
  edited rows from broken links.

## 2026-11-26 — User management

- Logins live in the database (`login_accounts`, scrypt): the authority's administrator (permission `user.manage`,
  page "משתמשים") creates users with a role and a temporary password, adds people from other authorities with a role
  here, changes roles, deactivates logins, resets passwords and removes members. A password set by an administrator
  must be replaced at the next login (nothing else answers until then). Everyone can change their own password (click
  your name in the top bar). Deactivation and resets end open sessions (sessions carry their issue time).
- Safeguards: no one changes their own role or deactivates / removes themselves; an authority keeps one working
  administrator; an administrator manages only their own authority's users.
- The htpasswd administrator keeps working; changing that password moves the login into the database.
- Memberships are revoked, not deleted (`authority_memberships.active`), so the actor stays in the audit trail and the
  person can be added back. Migration 0009.

## 2026-11-26 — Regulatory scope registry, source conflicts, resumable crawls (V10 overlay, merged)

- Crawls keep their queue (`checkpoint`): a failed, interrupted or budget-limited ("partial") crawl resumes where it
  stopped, without re-fetching committed documents. On-demand authorities resume only when asked ("המשך הסריקה");
  scheduled ones continue a partial crawl on the next worker pass and retry a failed one after an hour.
  `coverage_complete` on a finished crawl means every queued URL was fetched — not full statutory coverage.
- Verified regulatory registry (`regulatory_entries`, approval via API with an exact quote checked against the
  ingested page): date, property, lot, use and EPSG:2039 geometry scope; contradictory limits, differing limits and
  explicit replacements detected. Internal "תחולה" tab on each case. Not executable rules.
- Candidate conflicts between sources (same wording, different numbers) listed on the source monitor page.
- XPLAN parcel plan discovery module, off by default and never run in the app process while crawling is isolated.
- No "no defects" recommendation while regulatory coverage is unproven (always, for now). Cases with defects unchanged.
- Not taken from the overlay: its automatic all-authority scheduler and timer (crawls stay on demand / admin schedule),
  its file lock (crawls are claimed through the database by the single crawler process), and UI it re-added that was
  removed earlier (login restyle, evidence button, coverage block in the report). Migration renumbered to 0008.

## 2026-11-26 — Learning from decided cases; crawls on demand behind a restricted crawler

- The administrator loads a whole case (normal import) and the committee's decision (file or text, "החלטת ועדה" tab).
  Once the review is ready the decision is compared with it by topic: confirmed, missed, not raised. The decision text
  enters the authority's knowledge base (document, snapshot, searchable passages), the precedent shows on requests with
  a shared plan or block, and per-rule statistics show on the "למידה מהחלטות" page. Missed reasons become
  `committee_reason` rule drafts — a rule takes effect only after the administrator approves it. The decision is never
  an engine input. Migration 0007 (`learning_records`).
- Crawls run on demand only by default; the administrator may set daily or weekly per authority. Crawling and
  authority onboarding run only in the crawler process (OS user `permit-crawler`), whose outbound traffic the firewall
  limits to public addresses on 80/443 and the local DNS. Failed or interrupted jobs show as failed, never retried.

## 2026-11-26 — Multi-authority workspaces and regulatory knowledge onboarding

- Authority memberships (migration 0006): the login account is separate from its actor in each authority; the browser
  tab sends `X-Authority`, the server checks membership on every request (revoked access fails closed). Creating an
  authority needs an explicit account in `BBP_AUTHORITY_CREATORS`; a duplicate name or ID grants nothing.
- Login accounts map to users through `BBP_LOGIN_USER_MAP` (server-side; invalid map fails closed).
- New authority: official sources found through the Planning Administration committee directory (exact name match,
  ambiguous or blocked results shown, never called complete) or an admin catalog (`BBP_AUTHORITY_CATALOG`); first crawl
  bounded to the official hosts; public-address check on every fetch and redirect.
- Upload of laws, plans and guidelines (PDF, DOCX, XLSX, TXT) to the current authority: validated, hash-deduplicated,
  every snapshot kept, text indexed as unverified candidate passages (search scoped to the authority). Rules still go
  through drafts and professional approval; nothing is activated automatically.
- Onboarding is a durable job (row state + lease, retry up to 3, stale lease recovered after a restart), run by the
  onboarding worker (`BBP_ONBOARDING_WORKER=true`).
- Unknown authorities start with shared QA only (Bnei Brak / Hof Ashkelon specific checks excluded) and never cite
  another authority's sources; missing rights files and submission dates are "not checked", not "not applicable".
- Re-checking the 3 live requests on a migrated copy: identical defects and discrepancies.

## 2026-11-26 — ElevationEngine (section geometry)

- `agent/elevation_geometry.py`: slab levels, floor-to-floor heights and the highest drawn point of each section, from
  the vector geometry and the viewport scale (no label reading); run by the AI-PC drawing reader.
- Height check: when the label read and the section geometry are both under the limit, the height passes on measured
  evidence (a single stray read is shown as unsupported); geometry over the limit never passes.
- Defects report PDF restyled: short professional layout (numbered items, category line, finding, required
  correction, one reference line), no grid tables or crops.
- Zikim: floor-to-floor 3.06-3.08 m, 2 slab levels; top 6.90 m (311-312), 6.32 m (319-320, 339-340) above the
  ground-floor slab. 339-340 height: UNRESOLVED -> PASS.

## 2026-11-26 — V9 update: regulation resolver, component and relief validation, blind sanitizer

- `ApplicableRegulationResolver` (sources, applicability, limit conflicts by legal relation, cached; in every run's internal
  record), component validation (internal ≠ external height), `ReliefValidationEngine`, rights by category and floor,
  decision taxonomy + lifecycle, `ApplicationVersionComparator`, `BlindDatasetSanitizer` (gates the blind evaluator).
- 20221189 known-outcome regression (contaminated for blind use): 7/7 points match the committee. Details: docs/13.
- KB: 633-0928358 clauses, pages, height definitions, applicability; 6/123/03/6 component limits; `kb_compare.py`.

## 2026-11-26 — rights for 1/200/03/6 (Heletz) and 6/123/03/6 (Talmei Yafe)

- Rights files from the plans' scanned tables; a zone can apply by use when the plan defines only one residential zone.

## 2026-11-26 — building provisions 633-0928358

- `knowledge/building_provisions/hof_633_0928358.yaml`: council-wide building provisions (in force 05.04.2022, no
  building area) for the residential lots of 29 listed plans; farm holdings and Zikim lot 368 out of scope.
- Route engine: `building_provisions()` — an open check with the limits for requests from 05.04.2022 on listed plans'
  residential lots. Zikim scoping test narrowed to "never applied to lot 368".
- Last-5-years re-run: 4 of 12 reason topics in scope (1 detected, 3 flagged), 0 missed, 0 unsupported.

## 2026-11-26 — regional outline plan 234/02/6; last-5-years focus

- `knowledge/rights/hof_234_02_6_regional_outline.yaml`: moshav farm holdings, 3 units (2 × 160 + 55 m² gross). The
  parcellation plans ד/821, ד/822, 156/03/6 (and ד/820 by land use) take these rights for their farm-holding lots.
- Route engine: a plan's zone can take its rights from another plan's zone (`rights_from`), with that plan's dates.
- Rejected-applications set reduced to the 13 requests since 26.11.2021 (older ones deleted from the extracted copies).

## 2026-11-26 — rights files for frequent Hof Ashkelon plans

- `knowledge/rights/hof_*.yaml`: 2/228/03/6 (Netiv HaAsara), 291/03/6 (Nitzan), 2/166/03/6 (Kochav Michael); ד/820,
  ד/821, ד/822, 156/03/6 marked as rights-by-reference (regional outline plan, not available). Sources with SHA-256.
- Route engine: zones by lot range / land use, main-use filter, % of lot area, per-lot main area, total-only rights,
  half lots; declared areas of an addition are not compared with whole-lot rights.
- Rejected-applications re-run (development): rights for 24 cases (was 12), 0 missed, 0 unsupported.

## 2026-11-26 — blind run on 136 rejected Hof Ashkelon applications

- `scripts/evaluate_rejected.py` (+ `_score.py`): engine on the blind set only, inputs hashed and screened (committee
  letters, decision wording, application numbers excluded), frozen before the labels are read from the evaluation
  store. Results and limits: `docs/12_hof_rejected_evaluation.md`.
- Route engine: a relief named in a regular-route request is judged without a rights file; "ללא הקלות" is not a relief.

## 2026-11-26 — V9 unified integration

Details, results and blockers: `docs/11_v9_integration.md`. Baseline tag `pre-v9-baseline`.

- Required-check inventory per rule family (`knowledge/coverage/required_checks.yaml`, `app/coverage.py`): no
  NO_DEFECTS_IDENTIFIED unless every family is complete; NOT_IMPLEMENTED checks are listed; independent checks need
  measured or document evidence.
- Signed review attestations bound to the run digest (`app/attestation.py`), VALID / STALE / INVALID; derivation cache
  keyed by SHA-256 + algorithm version (+ jurisdiction + revision) with invalidation; run metrics (wall, CPU, tokens,
  cache, AI-PC work). Migration 0005. API: attestations, coverage, internal audit, metrics.
- Legacy DWF inventory with archive limits — BLOCKED_NO_DECODER (no licensed W2D decoder). BIM source D:
  NOT_AVAILABLE for Zikim (the "Model" DWFX is a 2D plot of a DWG).
- Route engine: short-track size on gross new construction, net/gross mismatch is a document discrepancy (Karmiya
  20260265, development dataset). Spatial margins with uncertainty; well zones by plan 633-0723718 §6.4 wording.
- Source C: fragmented floor outlines → UNRESOLVED, internal. Unconverted drawings never confirm missing sheets.
- Blind evaluation: input allowlist + decision-vocabulary scan, freeze before reveal, ground truth moved out of the
  repository. `scripts/unified.py` runner. Linux PDF font default.
- A height read only once can no longer confirm a violation: when the twice-read ridge is within the limit the
  height is UNRESOLVED (339-340: ridge +6.85 twice, one stray +13.20).
- AI-PC drawing reader unloads other router models before reading (a resident text model made the vision model fail
  to load on the 6 GB GPU: every sheet read returned 500).
- Zikim 10000611793-1 and 10000615058-2 imported from their original packages and run; 10000612352-1 re-run.

## 2026-11-26 — licensing route validation

- `backend/app/rules/route.py`: per-floor and basement rights, the regulation's basement definition, deviation
  classification (relief / substantial / unclassified / possible), route needed vs. selected, law as of the
  submission date, strict confirmation policy. Rules QA-LICENSING-ROUTE, QA-FLOOR-RIGHTS; `REJECT_BASIS` flag.
- Knowledge: TAMA 39 rights (OCR of the scanned regulations), the deviation regulations 2002 (text extracted from the
  .doc), Be'er Ganim building guidelines.
- Blind regression 20210885 with separate ground truth and `scripts/evaluate_blind.py`; 19 tests.

## 2026-11-26 — area check source C

- `agent/floor_geometry.py`: floor areas from the floor plans' cut walls (XPS paths, viewport scale from the file,
  section and site-plan filtering, opening bridging with a stability check, duplicate plans grouped); run by the
  drawing reader. Rule HA-AREA-FLOORPLANS compares C with the diagram categories inside the walls.
- Zikim: ground floor matches (247.55 vs 247.545); upper floor walls enclose 13.85 m² more than counted — unresolved,
  internal. Canopies outside the walls are not measured from the plans yet.

## 2026-11-25 — consolidated review update (Zikim)

Details, test results and limitations: `docs/09_consolidated_review.md`.

### Added
- Review statuses per finding (CONFIRMED_DEFECT, DOCUMENTED_DISCREPANCY, UNRESOLVED, NOT_CHECKED, FUTURE_STAGE, PASS,
  NOT_APPLICABLE), licensing stage per rule and per case, external/internal scope, final decision engine.
- Deterministic area geometry from DWFX area-calculation diagrams (`agent/area_geometry.py`): scale from the package
  transforms, Shapely unions, overlap / double-count / repeated-unit detection; rule HA-AREA-DIAGRAMS (A vs B).
- Historical permit reconciliation (`knowledge/lots/hof_ashkelon_2832_368_permits.yaml`, rule HA-368-TABLE-VS-PERMITS).
- Checks: HA-LAND-PARCEL, HA-RMI-CONSENT (future stage), Mekorot 5 m from Mekorot's response, technical-systems
  screening pass in the drawing reader (internal only), fences / infiltration reported as not checked.
- External defects report: JSON, Hebrew RTL PDF and Word (`backend/app/defects_report.py`, `/api/runs/{id}/defects*`).
- Results page rebuilt around the defects report (defects, discrepancies; internal record folded).
- Lot ledger: indirect records flagged (49 direct + 2), delta chains, redaction of phone numbers / names / owners.
- Local GPU vision preset `ministral-3-8b-vision`; drawing reader defaults to it.

### Changed
- Area-table arithmetic uses a rounding tolerance from the source precision.
- The register's status is internal (never a defect or a decision basis); table-vs-register gaps are neutral
  discrepancies.
- Intake opens one level of nested ZIPs (external bodies' responses).
- Height fact uses the highest plausible ridge reading; the read roof type is passed on.

### Not done
- Source C (floor-plan reconstruction), measured setbacks / coverage, blind validation set, KB package import (file not
  available), general processing cache and per-run token / GPU metrics.
