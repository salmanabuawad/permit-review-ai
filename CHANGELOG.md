# Changelog

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
