# Testing Strategy

## Today (measured 2026-11-26)

- 39 test modules: 369 passed and 8 skipped on SQLite. On PostgreSQL, 329 passed with the tests that need the
  validation data deselected, because that data is not on the server.
- Families already covered: rules and operators, evidence, licensing routes, reliefs, applicability, coverage, intake
  and typing, batch import, reports (RTL), login and users, multi-authority isolation, source monitor (resume,
  schedule), regulatory registry, committees and probe, learning, blind-input allowlisting (ground truth is never an
  engine input), and known-outcome case 20221189.
- Validation corpus: blind 20210885, known outcome 20221189, development 20260265, plus 3 live Zikim cases (production
  data, not in git).

## Test families to add

| Id | Family | What |
|---|---|---|
| T-GEO | geometry | areas, setbacks and heights on reference drawings with hand-measured truth (tolerance stated) |
| T-RULE | per-rule tests | every rule version carries pass / fail / edge fixtures (REGULATORY_ENGINE.md `tests:`); runs on activation |
| T-EXT | extraction | form fields, area tables, plan numbers versus annotated pages |
| T-CMP | drawing comparison | same drawing re-exported is unchanged; one moved wall changes the right entities |
| T-PDG | dependency graph | invalidation reachability, early cut-off, completeness fallback |
| T-INC | incremental versus full | for every revision in the corpus, the incremental and full outputs must be identical (findings, statuses, values) |
| T-AI | AI accuracy | Hebrew planning benchmark (≥ 100 questions, professionally answered), JSON validity, citation accuracy, abstention |
| T-RAG | retrieval | Recall@K, MRR, isolation, temporal and geographic applicability, exceptions retrieved |
| T-XT | cross-municipality | the same national rule gives the same result in two authorities; local rules never leak |
| T-SEC | security | tenant isolation, ZIP and PDF attacks, prompt injection fixtures, authorisation matrix |
| T-RTL | interface | Hebrew RTL rendering of key pages and reports (screenshots at phone and desktop widths) |
| T-PERF | performance | the benchmark suite (PERFORMANCE_BENCHMARKS.md), cold versus warm |

## Corpus rules

- Use the real permit applications of Bnei Brak, Beit Shemesh, Haifa and Hof Ashkelon as the regression corpus,
  stored outside git (raw case data stays out of the repository).
- Keep separate splits: development, known-outcome regression, and held-out blind. A decision seen by anyone working
  on the engine moves that case to known-outcome.
- Missing ground truth is never fabricated. Accuracy claims cite the corpus size and the split.
- Every professional correction becomes a regression candidate (continuous improvement engine) after approval.

## Gates

A rule version must pass its own tests before activation. A release must pass the full suite on PostgreSQL, T-INC
with zero differences, and T-SEC.
