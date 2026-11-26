# Incremental Review

## Today

- **IMPLEMENTED:** files are content-addressed (SHA-256), and new uploads create new file versions. Expensive
  derivations (drawing conversion, geometry, drawing reading, applicability) are cached by file hash, algorithm and
  version (`derivation_cache`), so a re-run reuses them: 34–35 cache hits per run, 0 misses.
- **IMPLEMENTED:** each run records its input hashes and ruleset hash, and every run is kept as a version (history
  tab). Locked versions cannot be re-run.
- **PARTIAL:** `lifecycle.ApplicationVersionComparator` compares application versions (a library, not yet wired to
  the UI).
- **Not yet:** rules are re-evaluated on every run, the LLM summary is regenerated on every run, there is no
  change-impact report, and no geometry or entity fingerprints.

## Target flow (on a revised submission)

| Step | Mechanism |
|---|---|
| 1–3 unchanged / modified / new / deleted documents | file SHA-256, then normalised-text and page hashes (a re-export with identical content counts as unchanged) |
| 4–5 drawing geometry and entities | geometry and entity fingerprints (PERMIT_DEPENDENCY_GRAPH.md); match by layer, type and position when handles change |
| 6 semantic changes | structured-field diff of declared values; the LLM is used only for free-text changes and returns a list of changed topics, never a verdict |
| 7–9 affected calculations and rules, invalidation | PDG reachability from the changed nodes |
| 10 reuse | VALID nodes reused, with the reason recorded |
| 11 execution | recompute STALE nodes in topological order, with early cut-off |
| 12 revision report | new defects, corrected, unchanged, newly unresolved, newly applicable requirements |

Every reused or recomputed result explains itself: "reused: inputs A, B unchanged since version 3", or "recomputed:
drawing X page 2 changed".

## Fallback to full review

A full review runs when:

- dependency completeness cannot be established;
- the engine version, coverage inventory or applicability context changed;
- more than a threshold share of inputs changed (full review is then cheaper);
- the reviewer asks for it.

A sample of incremental runs is re-run in full and compared (TESTING_STRATEGY.md, test family T-INC).

## First increment (smallest valuable step, backlog B-02)

Cache the run summary by the fingerprint of its evidence (the findings and KB passages sent) plus the prompt version
and model. A re-run with unchanged inputs then skips the about 25–47 s LLM call, which is about 94 % of run time
today. The second increment skips rule evaluation when the facts fingerprint and the ruleset hash are unchanged.
