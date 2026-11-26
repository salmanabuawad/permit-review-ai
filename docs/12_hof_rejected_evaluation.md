# 12 — Blind evaluation on 136 rejected Hof Ashkelon applications, 26.11.2026

Package `Hof_Ashkelon_Rejected_Applications_Complete.zip` (public committee pages, 136 rejected applications). Raw
files stay in `exports/` (gitignored); the restricted set (decisions, protocols, reasons) was moved to the evaluation
store (`BBP_EVAL_STORE/Hof_Ashkelon_Rejected_Applications/`, 0700) and is never beside the blind set.

```
python scripts/evaluate_rejected.py run   exports/hof_rejected/Hof_Ashkelon_Rejected_Applications   # engine, frozen
python scripts/evaluate_rejected.py score exports/hof_rejected/Hof_Ashkelon_Rejected_Applications   # then labels
```

## Isolation

* `run` reads only `01_BLIND_REVIEW`; it refuses to start if `02_RESTRICTED_VALIDATION` is next to it. Every file is
  checked against the package's SHA-256 manifest.
* Every document is screened. Of 130 documents: 48 are **committee letters** (relief-publication instructions filed
  under "application_forms" — committee output, with names and the application number), 37 more carry an application
  number, 30 have no text layer, 8 are legacy DWF (no decoder), 5 are images/OLE. **2 documents passed** — and the
  route engine reads none. In practice the engine input is the register metadata: request text, application type,
  declared areas, plans, submission date.
* One case (CASE_000064) is **excluded**: its register request text was edited after the decision
  ("(לא מאושר-ראה החלטת ועדה)") — a label leak.
* The engine result was frozen (SHA-256) before the labels were extracted.

## Engine changes made before the run (logic, not tuned on labels)

* A relief named in the request while filed in the regular route is now judged even when no rights file exists for
  the plan (it needs none). Before, every case without a rights file returned NO_RIGHTS with no checks.
* "ללא הקלות" ("without reliefs") no longer counts as naming a relief.

## Results (135 scored)

Engine verdicts: NO_RIGHTS 121 (no rights file for the plan — 124 of 136 cite plans outside the knowledge base),
INSUFFICIENT_EVIDENCE 12 (all TAMA 39 lots: per-floor areas need the drawings), WRONG_ROUTE 2 (both confirmed).

The official reasons were tagged by topic (keyword rules over the committee's decision text; protocol text is not
OCR'd and partly broken, 34 cases got no tag). 202 topic mentions:

| | count |
|---|---|
| in engine scope (the engine had the input) | 10 |
| — DETECTED (confirmed engine finding) | 1 |
| — FLAGGED (engine left the topic open, named what is missing) | 9 |
| — MISSED | 0 |
| NO_INPUT (needs documents/drawings the public package does not hold) | 192 |
| engine findings with no matching official reason | 0 |

* CASE_000082: filed without reliefs, request names reliefs for a basement and pool → WRONG_ROUTE, confirmed. The
  committee: filed in the wrong route, must be requested as a relief. **Detected.**
* CASE_000090: filed without reliefs, request names a flat roof and moving service area → WRONG_ROUTE. The committee
  refused the reliefs as a substantial deviation. The engine found the deviation but did not classify it as
  substantial (it has no rights file for that plan) — FLAGGED.
* CASE_000083: the same request text as 20210885 (±0.00 change, basement) → zero level POSSIBLE_DEVIATION, route
  undecided; the committee: wrong route, basement exceeds TAMA 39. FLAGGED, as in the earlier blind run.
* The other FLAGGED topics are TAMA 39 lots whose rights / height / building-line reasons need the floor plans.

Most official reasons are outside what any engine can check from this package: incomplete submissions and failed
spatial control (36), ownership/consent (25), refused reliefs (20), unpermitted existing building (17), publication,
objections, outside authorities.

## What this does and does not show

* No false positive: nothing the engine confirmed lacks an official counterpart.
* Recall cannot be measured: 192 of 202 reasons need inputs that are behind the national licensing login (drawings,
  area tables, surveys). This package is not a test of the drawing engines; 6 cases have legacy DWF only (blocked).
* All 136 are rejections, so the decision itself carries no information; only per-reason agreement is scored.
* The tagging of official reasons is a keyword reading of broken text, not a professional reading.

## Rights files for the frequent plans (added after the blind run)

Read from the plans' scanned instructions (council GIS; OCR locally, every value checked against the page image;
sources in `knowledge/sources.d/hof_ashkelon_plans.yaml` with SHA-256 — OCR texts not stored, they contain
signatories' ID numbers):

| Plan | Village | Cases | What the file holds |
|---|---|---|---|
| 2/228/03/6 (2009) | Netiv HaAsara | 6 | lots 1-16, 22-26, 42-67, 76-85, 90-107: main 640 m² (≤350 per unit, 2 units), service 155 above + 120 below, coverage 650, 2 floors + basement. The plan prints a total of 810 m², less than its own parts (915) — reported, never used. |
| 291/03/6 (2006) | Nitzan | 9 | single-family lots: 55% main, 25% + 10% service **of the lot area**; lots 601-671: 350 / 60 / 100 m²; other two-family lots: main per lot 178-357 m² by §13ב, service by formula |
| 2/166/03/6 (1984) | Kochav Michael | 5 | farm plot: ≤3 units, ≤400 m² total (before the main/service split); professionals' zone ≤220 m² — the zone of a lot is on the map, not in the register |
| ד/820, ד/821, ד/822, 156/03/6 (1972) | Nir Israel, Bracha, Gea, Hodiya | 25 | parcellation plans: rights "according to the outline plan" (§12). Marked as by-reference; the regional outline plan is **not in the package** (the later plans listed — 633-0575639, 633-0966986 — postdate the submissions; 307/02/6 is a road plan; 633-0415778 covers non-agricultural uses) |
| 1/200/03/6 (1997) | Heletz expansion | 5 | added later: מגורים א' — lot ≥492 m², 1 unit, 40% main + 5% service of the lot area (45%), coverage 30%, 2 floors, 8.5 m sloped / 7.0 m flat, side and rear 3.0 m; every residential lot it defines is in this zone |
| 6/123/03/6 (2008) | Talmei Yafe expansion | 4 | added later: מגורים א' 2, lots 401-469 — 180 m² main + 50 above + 50 below service (280 total), coverage 36%, 1 unit, 2 floors + 1 below, 9.0 m sloped / 7.0 m flat |
| 2/156/03/6 | Hodiya extension | 4 | no plan instructions in the package |

Engine support added with them: rights by lot range, by land use and by main use (a barn or an antenna gets no
residential rights); rights as a percentage of the lot area (NOT_CHECKED until the lot area is known); per-lot main
area; a total-only right for pre-1989 plans; a half lot ("653 ב'") gets its zone but not the whole lot's rights. And
a guard: when the request adds to or regularises an existing building, the register's areas may be the addition only
and are **not** compared with the lot's rights (CASE_000008 declares 69 m² main — the addition — on a 640 m² lot).

**Re-run — development, not blind** (labels were seen before these files were written; the blind result is kept
separately, `exports/hof_rejected/results_blind_2026-11-26/`): rights now apply to 24 cases (was 12); reason topics in
engine scope 16 (was 10): DETECTED 1, FLAGGED 15, MISSED 0, unsupported 0. Remaining NO_RIGHTS: no rights file 77,
rights in the regional outline plan 25, zone unknown 4, % of an unknown lot area 3, non-residential use 2.

### The regional outline plan 234/02/6

Found in the package: 234/02/6, "תכנית מתאר למועצה אזורית חוף אשקלון", in force 31.12.1989. Chapter ה (built rural
zone, moshav): up to 3 housing units per farm holding — two of up to 160 m² gross and one of up to 55 m² gross (375 m²
gross in all), up to 3 floors. The parcellation plans now take these rights for their farm-holding lots (zone tables:
Bracha 1-95, Gea 1-38/40-54/55-68/71-92, Hodiya 1-93; Nir Israel's table gives no lot numbers). Auxiliary farms
(משקי עזר) get none. The amendments in the package (4/, 26/, 29/, 43/234/02/6) are site plans and change nothing here.

## Focus: requests of the last 5 years (from 26.11.2021)

At the user's request the 123 older requests were deleted from the extracted blind set and from the evaluation store
(moved to the trash), and the package itself was rebuilt: `exports/Hof_Ashkelon_Rejected_Applications_Complete.zip`
now holds only the 13 requests (431 MB, 496 of 3,195 files; SHA-256 6538af63…). Indexes (applications, completeness,
download manifest and log, missing files, HTML reports, case mapping, rejection index) are filtered to them; shared
meeting documents (19 meetings) and plan references are kept only where a kept case refers to them; every kept file is
byte-identical to the original and matches its manifest hash; no dropped case id or application number remains. The
original 3.9 GB zip was moved to the trash. The figures above for 136 cases are kept as the record.

13 requests remain (2022–2025). Engine: WRONG_ROUTE 1 (CASE_000082, confirmed — detected), INSUFFICIENT_EVIDENCE 2,
NO_RIGHTS 10. Official reason topics: 12 mentions, 2 in engine scope (1 detected, 1 flagged), 0 missed, 0 unsupported.

The recent refusals are mostly about **building provisions** — storey height (2.20 m where 2.50 m is required), a
third storey, parking height relief, 3 m walls around a roof terrace — and about unauthorised use, encroachment on
public land and missing ownership/consent. Since 05.04.2022 these are governed by the council-wide plan for building
provisions, 633-0928358 (cited in the recent protocols alongside the lot's plan).

### Building provisions 633-0928358 (in force 05.04.2022)

Read from its instructions (text-layer PDF, from the council GIS — apps.land.gov.il returned an error page; SHA-256
327daa37…; `knowledge/building_provisions/hof_633_0928358.yaml`). It **adds no building area** (§5 "לא רלוונטי"). It
changes the residential lots (מגורים א', מגורים, חד משפחתי) of the 29 plans in its §1.6 and is subordinate to TAMA 39;
it does not apply to farm holdings, auxiliary farms, professionals' houses or kibbutz "old camps". In kibbutzim only
Zikim lots 1-104 of 6/120/03/6 and Karmiya lots 201-257 of 6/109/03/6 — **not Zikim lot 368** (633-0723718 is not
among the plans it changes; the scoping test now checks exactly that instead of banning the plan number).

Encoded provisions: height ≤10.5 m (sloped ridge) / ≤9 m (flat, incl. railing) from the entrance level; entrance
≤1.2 m above the pavement; storage ≤12 m², inner ≤2.20 m; covered parking ≤30 m² (2 spaces), ≤2.5 / 2.2 m; pergolas
to a 0.00 side/rear line; basement ≤2.20 m, one external entrance, ≤10 m² main area for wet rooms; fences ≤1.8 m;
technical screens; service yard. The route engine applies it from 05.04.2022 to listed plans' residential lots as an
open check that names the limits and the drawings needed (sections, elevations, site plan) — with or without a
rights file.

Re-run of the 13 (development): the provisions apply to 6 requests (082, 085, 094, 114, 123, 128; CASE_000037 is a
farm holding — not covered). Reason topics in engine scope 4 of 12: DETECTED 1 (route), FLAGGED 3 (the three height
reasons — storey/parking/roof-terrace walls — with the limits that apply), MISSED 0, unsupported 0. The rest need the
drawings or are outside any plan check (ownership, unauthorised use, encroachment, incomplete submission).

### 1/200/03/6 and 6/123/03/6 (added for the recent requests)

CASE_000094 (Talmei Yafe lot 440, 2022, new house): 179.61 m² main ≤ 180 and 97.8 m² service ≤ 100 — within; per-floor
rights and the 2022 building provisions stay open (drawings). CASE_000082 (Heletz lot 237): 326.5 m² main needs a lot of
at least ~816 m² at 40% (minimum lot 492 m²) — open until the lot area is known. CASE_000114 is an addition (not
compared with whole-lot rights). Scores unchanged: 1 detected, 3 flagged, 0 missed, 0 unsupported.
