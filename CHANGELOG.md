# Changelog

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
