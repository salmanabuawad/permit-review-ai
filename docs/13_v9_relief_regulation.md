# 13 — V9 update: regulatory coverage, relief validation, rejection learning (26.11.2026)

Built into the existing engines (route / rights / building provisions / evidence / cache / evaluation), no prototype.

## What was implemented

| Module | File | What it does |
|---|---|---|
| ApplicableRegulationResolver | `backend/app/rules/applicability.py` | Per application: national regulation (deviation regs 2002), the lot-defining plan's rights (zone by lot / land use / use), outline plans reached through `rights_from`, local guidelines, regulatory (תקנונית) plans that change listed plans, plans encoded as rules. Status APPLIES / NOT_APPLICABLE / UNRESOLVED with the reason. Component limits per (component, attribute); when two sources set different values, the one that legally **changes** the other governs (in force on the submission date); with no recorded relation → UNRESOLVED_CONFLICT. Cached by property + knowledge-base version. Integrated into every server run (`summary.review.regulation_sources`, internal only). |
| Component validation | `backend/app/rules/components.py` | 12 component kinds; area, inner height, outer height, width, length, ridge / flat height, setbacks — each against its own limit; internal and external heights are separate attributes. Evidence source per value: measured / drawing_read / declared / committee_reported (never shown as geometry). |
| ReliefValidationEngine | `backend/app/rules/relief.py` | Binding regulation (plan, clause, page), permitted / requested, absolute and % deviation, legal availability (design provisions: CONDITIONAL under reg. 2(10) — a legal judgement), justification, evidence, discretion, s.149 publication. Outcomes: CONFIRMED_VIOLATION, LEGALLY_UNAVAILABLE_RELIEF, UNRESOLVED_APPLICABILITY, INSUFFICIENT_EVIDENCE, MISSING_PLANNING_JUSTIFICATION, DISCRETIONARY_DECISION_REQUIRED, WITHIN_LIMIT. Only the first two may reach an external report. |
| Rights by category and floor | `backend/app/rules/route.py` | Main above / below, service above / below checked separately. An unsplit total proves compliance only when it fits the **smallest** category limit; otherwise NOT_CHECKED with "טבלת שטחים לפי קומה". No transfer between categories unless the plan's transfer rule allows it. A split that does not add up to the declared total is flagged. Committee-reported splits are `confirmable: false`. |
| Decision taxonomy + lifecycle | `backend/app/lifecycle.py` | The 8 decision types, several per application; RELIEF_REJECTED is never an application rejection; final status from the last decisive event (permit issued). Stored in the evaluation outputs (not a database table). |
| ApplicationVersionComparator | `backend/app/lifecycle.py` | Compares versions per attribute; a geometric change is stated only when both versions carry geometry, else NOT_VERIFIED; an unevidenced relief list is NOT_VERIFIED, never "dropped". |
| BlindDatasetSanitizer | `backend/app/blind_sanitizer.py` | PDF (annotations, embedded files, metadata, outcome wording), DOCX (comments, tracked changes, committee letters), DWF/DWFX (markup resources, labels, markup graphics layer), DXF (markup layers), DWG (strings), IFC, ZIP (recursive). Originals untouched; derivatives only where separation is reliable; otherwise QUARANTINED and the case contaminated. Now the gate of `scripts/evaluate_rejected.py run`. |
| Known-outcome runner | `scripts/known_outcome.py`, `validation/known_outcome/20221189/case.yaml` | Engine first on application facts, then a labelled pass with committee-reported values; comparison with the committee; Hebrew RTL report. |
| KB comparison | `scripts/kb_compare.py` | Collected documents vs registered sources by SHA-256. |

Knowledge base: 633-0928358 now carries its approved version, verified applicability rule, internal / external height
definitions (clause 4.1.2 ב, p.13), relief provision, and clause + page for every executable provision; 6/123/03/6
carries its component limits (mamad 7, storage 12, covered parking 31 m², heights 9 / 7 m, table §5 notes, p.13).

## 20221189 (Talmei Yafe, lot 440) — known-outcome regression, not a blind test

Contaminated for blind use: the meeting-archive DWF holds reviewer markup (36 distinct labels, e.g. requests to state a
justification for the relief and to show parking levels), and the committee documents were read during inspection.

| Item | Committee | Engine |
|---|---|---|
| Governing parking inner height | 2.20 m, plan 633-0928358 | 2.20 m, 633-0928358 clause 4.1.2 ב p.13 (over 6/123/03/6) |
| External height | 2.50 m | 2.50 m (separate attribute) |
| Deviation | 2.63 − 2.20 = 0.43 m, 19.55 % | 0.43 m, 19.55 % |
| Relief | refused — no planning justification | MISSING_PLANNING_JUSTIFICATION, legal availability CONDITIONAL (reg. 2(10)), discretionary, internal only |
| Covered-parking area | — | 30 m² (633-0928358) governs; 31 m² of 6/123/03/6 superseded |
| Areas | main 179.61 ≤ 180; basement 49.27 ≤ 50; service above 24.10 ≤ 50 | application facts only: main WITHIN, service 97.8 NOT_CHECKED (unsplit, > 50); with the committee split (labelled): all four categories WITHIN, and 24.43 m² of the declared 97.80 not assigned to a floor (flagged) |
| Decisions | relief refused 18.04.2023 (202315), approved 28.05.2023 (2023058), permit 30.07.2023 | RELIEF_REJECTED → RETURNED_FOR_CORRECTIONS ×n → APPLICATION_APPROVED; final PERMIT_ISSUED |
| Versions | — | areas unchanged (permit text); parking height after correction NOT_VERIFIED (approved plan set image-only) |

7 of 7 comparison points match. External report: no evidence-backed defect (a refused relief is not illegal
construction). Report: `exports/reports/20221189_comparison.html` (RTL) and `.json`.

## Blind dataset sanitization (13 recent requests)

6 files inspected: the meeting DWF of CASE_000094 — 4 markup resources, 74 label properties, the markup graphics layer
identified; stripped into a *candidate* copy but QUARANTINED (the W2D drawing content cannot be decoded to prove nothing
remains); 5 committee letters (DOCX) quarantined. Contaminated cases: CASE_000094 only. It is excluded from the blind
score (now 12 scored: 1 detected, 2 flagged, 0 missed, 0 unsupported). Report: `exports/hof_rejected/results/sanitization_report.json`.

## Zikim recheck

Lot 368 (633-0723718): 633-0928358 → NOT_APPLICABLE (633-0723718 is not among the plans it changes; in Zikim it covers
only lots 1–104 of 6/120/03/6). 633-0723718 → APPLIES, encoded as rules (`knowledge/rules/hof_ashkelon.yaml`). The
regional outline plan 234/02/6 covers the council area; its kibbutz provisions were not read, so it is not used for lot
368 (recorded here, not assumed). Server runs record the resolver output per case.

## Not implemented / open (not claimed)

* GIS lot data (areas, zones) — skipped at the user's request; percentage rights stay NOT_CHECKED.
* Geometry of components (parking heights etc.) is not measured from drawings here: the values are declared or
  committee-reported. Legacy DWF W2D cannot be decoded (no licensed decoder).
* DOCX comment / tracked-change stripping and DXF layer stripping: detected and quarantined, not stripped.
* Decision records are evaluation outputs, not database tables; no UI.
* Relief legal availability for non-design components (setbacks, floors, area) uses the existing route engine; the
  relief engine reports UNKNOWN for components it has no regulation mapping for.
