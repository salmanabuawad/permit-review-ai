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

Next inputs that would make this measurable: rights files for the frequent plans (291/03/6, 156/03/6, ד/821, ד/822,
2/228/03/6), and the original submissions of the 6 cases with drawings.
