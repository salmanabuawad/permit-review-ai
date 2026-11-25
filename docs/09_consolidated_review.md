# 09 — Consolidated review update (Zikim lessons), 25.11.2026

What this update changed, what was tested, and what is **not** done. Reference application: national
10000612352-1, municipal 20260611, Zikim, block 2832, plan cell 368, units 319–320, plan 633-0723718.

## 1. Review statuses, licensing stage, scope

Every finding now carries, besides the engine status (PASS/FAIL/UNCERTAIN/NA) and the issue type (MISSING /
CONFLICT / INVALID), a review status — flag `STATUS_*` (`services.review_status`):

| Status | Meaning | In the external defects report |
|---|---|---|
| `CONFIRMED_DEFECT` | established by evidence, needs correction | yes (light red) |
| `DOCUMENTED_DISCREPANCY` | two sources disagree in a way that bears on this application | yes (light orange) |
| `UNRESOLVED` | evidence found but not enough to decide | no |
| `NOT_CHECKED` | the check could not run (no data / not implemented) | no |
| `FUTURE_STAGE` | a requirement of a later licensing stage | no |
| `PASS`, `NOT_APPLICABLE` | — | no |

* **Licensing stage** (`services.licensing_stage`): declared on the case (`declared.licensing_stage`), else from the
  committee register's status for the request, else `SPATIAL_REVIEW`. Rules carry `licensing_stage`
  (`PRELIMINARY_ACCEPTANCE … COMPLETION`, default `SPATIAL_REVIEW`); a missing item of a later stage is
  `FUTURE_STAGE`, never a current defect. Set from each source's own wording: "תנאי להיתר / תנאי למתן היתר" →
  `PERMIT_ISSUANCE`; Home Front Command → `DESIGN_CONTROL`; "בקשה להיתר תכלול" → current.
* **Scope**: flag `EXTERNAL` = goes into the defects report. A rule with `external: false` or a resolution marked
  `internal` stays in the audit record (e.g. the register's own status, image-model observations).
* **Sub-items**: a resolver may return several items (e.g. one per historical building), each with its own status,
  found / expected / difference / where / correction / evidence; stored as evidence entries `type: item`.
* **Final decision** (`services.final_decision`, in `run.summary.review`): `RETURN_FOR_CORRECTIONS` when the
  report has items; `REJECT_RECOMMENDATION` only for a confirmed defect of a rule marked `reject_basis`
  (none yet) — never for missing documents, incomplete checks or the official status;
  `INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION` when high-severity checks are open; else `NO_DEFECTS_IDENTIFIED`.
  `run.summary.review` also holds counts per status, coverage (completed / applicable) and limitations.

## 2. Areas — sources A and B (deterministic geometry)

`agent/area_geometry.py` (runs on the AI PC inside the drawing reader; DWFX never processed on the app server):

* finds the sheets drawn by an area-calculation tool (resource title `…\AreaCalculation\…`);
* **scale from the package, never from declared totals**: `Units Transform` (model → plot) × the FixedPage
  `RenderTransform` gives plot points per model unit; the model unit (cm/mm/m) is the only one that gives
  building-sized diagrams (3–80 m);
* unions the coloured fills per category with Shapely, separates diagrams from the table strips, detects
  overlaps between categories (double counting) and repeated / mirrored units;
* classifies by the tool's colour legend; protected-room floor up to 9 m² net per room is service, the rest primary
  (HA-917226302E). The committee guideline "12.5 m² gross" (HA-ED8592A090, legal status unverified) gives a
  different split — recorded as `UNRESOLVED`, internal.

Rule `HA-AREA-DIAGRAMS` compares A (declared main / service) with B. Zikim: A 366.10 / 125.24 / 491.34 vs
B 366.101 / 125.247 / 491.348 — PASS; no overlaps; the two units are repeated copies.

**Source C (reconstructing areas from the floor plans' walls) is not implemented.** Every PASS says so; A = B does
not establish compliance.

## 3. Historical permits and the cumulative rights table

`knowledge/lots/hof_ashkelon_2832_368_permits.yaml` — area tables of signed permit drawings (documents of the
committee register), transcribed from the drawn tables (no text layer) and accepted only where the table's own
arithmetic closes; crops in `knowledge/lots/evidence/` (no personal data). Rule `HA-368-TABLE-VS-PERMITS`:

* a table row equal to a permit's area **before** its approved addition → `CONFIRMED_DEFECT` (outdated value);
* any other gap → `DOCUMENTED_DISCREPANCY` (a later permit may explain it).

Zikim: building 112 — table 265.70 main, permit 20210501: 265.70 + 13.44 = 279.14 (defect; the permit's own service
total 179.35 ≠ its components 170.14, noted). Building 114 — table 391.49 total vs permit 20210495 378.14
(+13.35, discrepancy). The lot ledger (`hof_ashkelon_2832_368.yaml`): 51 records = 49 direct (the spec's
27/4/14/3/1) + 2 found only by the broad search; delta chains for 48, 112, 114; personal identifiers redacted.

## 4. Other checks added

| Rule | Result for Zikim | How |
|---|---|---|
| `HA-LAND-PARCEL` | discrepancy | the form declares parcel 27; the ownership-proof section holds the parcel-28 extract; RMI: entered parcels ≠ contract |
| `HA-RMI-CONSENT` | future stage | RMI: consent only after the committee decision |
| `HA-633-MEKOROT-5M` | pass | Mekorot's response lists only well protection radii, no pipelines (response was a ZIP inside response.zip — intake now opens one nested level) |
| `HA-633-TECH-SCREENING` | unresolved (internal) | image model flagged possible unscreened AC on sheet 6 twice; a model reading never makes a defect |
| `HA-633-FENCES`, `HA-633-INFILTRATION` | not checked | no separation-wall geometry / no permeable-area data or lot boundary in the measured sheets |
| `HA-368-TABLE-ARITHMETIC` | pass | 0.141 m² is within the rounding of 41 rows at 2 decimals (≤ 0.205) |
| `HA-368-REGISTRY-STATUS` | internal | the official status is not independent evidence |

## 5. External defects report

`backend/app/defects_report.py`; API `GET /api/runs/{id}/defects` (JSON), `/defects.pdf`, `/defects.docx`; buttons on
the results page. Title "דוח ליקויים – בקשה להיתר מס׳ …"; neutral header with identification and recommendation;
one block per item — finding, difference, where, evidence (quotes; the permit-table crop as an unmodified image),
requirement, impact, correction; a short limitation statement. Hebrew RTL in both formats (PDF: reportlab +
python-bidi; Word: `w:bidi`, `w:rtl`, `w:bidiVisual`). Word output checked by tests, not opened in Word here.

Zikim run (version 15): **RETURN_FOR_CORRECTIONS** — 3 confirmed defects (building 112 table value, survey map
older than 6 months, construction-waste estimate missing), 3 discrepancies (building 114, parcel 27/28,
units 313–314 vs the register). Internal: 4 future-stage, 1 unresolved, 2 not checked, 29 passed, 6 n/a.

## 6. Performance (Zikim, first run)

| Step | Where | Time |
|---|---|---|
| Area geometry (B) | AI PC | 5.8 s |
| Drawing read (74 image calls) | AI PC, RTX 3050 | 33 min (hours on CPU before the GPU preset) |
| Screening pass (9 calls) | AI PC | ~50 s |
| Check run (36 files, incl. local AI summary) | app server | 31–39 s |

Not measured yet: token counts, cache hit rates, CPU/GPU utilisation per run (spec §21).

## 7. Not implemented (spec items still open)

* Source C (wall reconstruction), measured setbacks / building lines / coverage from geometry, annotated crops for
  geometric defects (none confirmed in this case), DWG/DXF/vector-PDF area extraction beyond the DWFX tool legend.
* Import of `Zikim_Lot368_Local_AI_Knowledge_Base.zip` — the file is not on this machine.
* Blind validation set (20210885 Be'er Ganim, 20211027 Hodiya) — source packages not collected.
* Processing caches keyed by SHA-256 + algorithm version (results are stored per file, not yet a general cache),
  per-run metrics of tokens / GPU, GIS and cadastral cross-checks, Ministry of Health approval reconciliation
  (45 vs 56 units, lot 168 vs 368).

## 8. Deploy and rollback

* App server: copy `backend/app/{rules/evidence.py,rules/engine.py,services.py,main.py,reports.py,defects_report.py,
  batch_import.py}`, `knowledge/{rules,sources.d,lots}`; `pip install python-docx==1.1.2` in the venv; build the
  frontend (`npm ci && npx tsc -b && npx vite build`); `systemctl restart permit-review-ai`; rerun checks.
* AI PC: `agent/area_geometry.py`, `agent/drawing_reader.py`; `systemctl --user restart bbp-ai-agent`.
* No database migration: the new data lives in existing JSON columns (finding `flags` / `evidence`,
  `run.summary.review`, file `ingest_report.drawing_read`).
* Rollback: `git revert` the commit and redeploy the same paths; old runs stay readable (the old UI ignores the new
  flags). The `ministral-3-8b-vision` preset can be removed from `~/muniflow/.local/models.ini` (copy of the previous
  file kept in the session scratchpad) and the muniflow node restarted.
