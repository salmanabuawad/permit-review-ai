# 10 — Licensing Route Validation Engine (26.11.2026)

`backend/app/rules/route.py`, rules `QA-LICENSING-ROUTE` and `QA-FLOOR-RIGHTS`, tests
`backend/tests/test_route_validation.py`, blind evaluation `scripts/evaluate_blind.py`.

## What it does

Aggregate compliance (total main / service area) is not enough. Per application the engine:

1. **Plans in force on the submission date** — `knowledge/rights/*.yaml` carry `effective_from` / `effective_to`;
   a plan not in force on the date gives no rights (`NO_RIGHTS`).
2. **Floor-specific rights and basement limits** — e.g. TAMA 39 single-unit lot: main 220, service above ground 70,
   service below ground (basement) 60, total 350, 2 floors above the entrance, one basement floor for service uses,
   and note (4): above-ground areas may be transferred to the basement if totals are unchanged.
3. **Proposed floors** — from measured drawings or a declared per-floor table (`declared.floor_areas`); never derived
   from totals. Without them: `NOT_CHECKED`, naming the missing drawings.
4. **Classification** of each deviation against the deviation regulations 2002 (`knowledge/law/…yaml`):
   `WITHIN` · `RELIEF` (needs a relief, s.147) · `PROHIBITED` (substantial deviation, reg. 2) ·
   `DEVIATION_UNCLASSIFIED` (a certain deviation the encoded law does not classify) · `POSSIBLE_DEVIATION` (depends on
   a value not in the inputs) · `NOT_CHECKED`. Encoded mechanically: basement definition (ceiling ≤ 1.20 m above
   ground, reg. 2(8)) — a raised basement counts as a floor; added floors (2(8)); service area used for main uses
   (2(16)); building lines front / side / rear with their relief-only exceptions (2(5)–(7)); old-plan area increase
   (reg. 9, plans deposited before 1.8.1989). Not encoded: anything needing judgement (e.g. "changes the character of
   the surroundings").
5. **Route needed vs. route selected** — the selected route comes from the register's application type (81 regular,
   82 with reliefs, 83 short track), a declared `licensing_route`, or the request form (a relief section).
   Any deviation excludes the regular route, so a regular-route application with a deviation is `WRONG_ROUTE`
   whether the deviation is relief-eligible or prohibited.

## Evidence policy

* A confirmed result needs its inputs (drawings / declared per-floor table) and a plan in force on the date.
* A **prohibited** classification is confirmed only when the deviation regulations are verified for the date: the
  encoded text is consolidated to 20.11.2011, so for later requests it is reported, not confirmed.
* A plan clause whose mechanism is unclear stays unresolved: TAMA 39's "תותר העברה" (transfer to the basement) does
  not say whether it is by right or needs publication, so a basement relying on it is a `POSSIBLE_DEVIATION`.
* A confirmed prohibited deviation sets `REJECT_BASIS`, the only ground the decision engine accepts for
  `REJECT_RECOMMENDATION`.

## Regression 20210885 (Be'er Ganim, lot 1652) — blind

Inputs (`validation/cases/20210885`): the applicant-side register facts and the GIS planning panel. The 2021
drawings, basement plan, per-floor areas and proposed ±0.00 are not public (Rishui Zamin, login only).

Engine result: aggregate rights met (219.45 ≤ 220 main, 128.35 ≤ 130 service, lot 502.1 ≥ 500); floor and basement
checks `NOT_CHECKED` (no plans); the declared ±0.00 change a `POSSIBLE_DEVIATION` (value unknown; guideline
flexibility +0.5 / −0.2 m); verdict `INSUFFICIENT_EVIDENCE`, nothing confirmed.

Scored afterwards against `validation/ground_truth/20210885.yaml` (decision 20.05.2024: refuse — wrong route, basement
area not per TAMA 39, relief needed): wrong route FLAGGED, basement area FLAGGED, 0 missed, 0 false positives; the
engine's reading of the plan's rights matches the committee's (220 / 70 / 60 / 350). A test asserts that no module
under `backend/app` reads the ground truth.

Not reproducible blind: the committee's opinion cites a second plan (633-0928358) for the area transfer; the GIS lists
only TAMA 39 for the parcel and the national plan register was not checked — a known gap of the plan lookup.

## Limits

* Floor areas by floor name come only from a declared table today; the geometry engines (sources B/C) measure floors
  but cannot yet name them (labels are drawn as lines), so they do not feed this engine.
* Rights files exist for TAMA 39 single-unit lots only; other plans return `NO_RIGHTS` (rule not applicable).
* Relief availability for area increases under plans deposited after 1.8.1989 is not settled by the encoded text.
