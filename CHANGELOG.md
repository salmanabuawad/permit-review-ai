# Changelog

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
