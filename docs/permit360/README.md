# KORTEX Permit360: architecture documents

Written 2026-11-26 from the repository and the live system (commit `e483c19`). Living documents: update them with
every milestone. Legend everywhere: IMPLEMENTED · PARTIAL · PROPOSED.

| # | Required deliverable (master prompt §22) | Document |
|---|---|---|
| 1 | Existing system assessment | [CURRENT_SYSTEM_ASSESSMENT.md](CURRENT_SYSTEM_ASSESSMENT.md) |
| 2 | Existing functionality inventory | [PRODUCT_MODULES.md](PRODUCT_MODULES.md) §inventory |
| 3 | Gap analysis | [PRODUCT_MODULES.md](PRODUCT_MODULES.md) §mapping · [CURRENT_SYSTEM_ASSESSMENT.md](CURRENT_SYSTEM_ASSESSMENT.md) §4 |
| 4 | Target architecture | [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) |
| 5 | Component dependency diagram | [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) |
| 6 | Database architecture | [DATABASE_ARCHITECTURE.md](DATABASE_ARCHITECTURE.md) |
| 7 | Permit Dependency Graph design | [PERMIT_DEPENDENCY_GRAPH.md](PERMIT_DEPENDENCY_GRAPH.md) |
| 8 | Regulatory rule schema | [REGULATORY_ENGINE.md](REGULATORY_ENGINE.md) |
| 9 | AI Gateway architecture | [AI_GATEWAY.md](AI_GATEWAY.md) |
| 10 | Integration feasibility matrix | [INTEGRATION_STRATEGY.md](INTEGRATION_STRATEGY.md) |
| 11 | Security architecture | [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md) |
| 12 | Migration strategy | [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) §deployment · [DATABASE_ARCHITECTURE.md](DATABASE_ARCHITECTURE.md) · [REGULATORY_ENGINE.md](REGULATORY_ENGINE.md) §migration · [PERMIT_DEPENDENCY_GRAPH.md](PERMIT_DEPENDENCY_GRAPH.md) §migration path |
| 13 | Prioritised development backlog | [DEVELOPMENT_BACKLOG.md](DEVELOPMENT_BACKLOG.md) |
| 14 | Testing strategy | [TESTING_STRATEGY.md](TESTING_STRATEGY.md) |
| 15 | Performance and cost measurement plan | [PERFORMANCE_BENCHMARKS.md](PERFORMANCE_BENCHMARKS.md) |
| 16 | Risk register | [DEVELOPMENT_BACKLOG.md](DEVELOPMENT_BACKLOG.md) §risks |
| 17 | Implementation roadmap | [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) |

Status: [REMAINING_BLOCKERS.md](REMAINING_BLOCKERS.md) · [TEST_RESULTS.md](TEST_RESULTS.md).
Studies: [HOF_ASHKELON_DECISIONS_STUDY.md](HOF_ASHKELON_DECISIONS_STUDY.md) (committee decisions 2016–2026, aggregates).

Also: [PERMIT360_VISION.md](PERMIT360_VISION.md), [INCREMENTAL_REVIEW.md](INCREMENTAL_REVIEW.md),
[KNOWLEDGE_BASE_STRATEGY.md](KNOWLEDGE_BASE_STRATEGY.md). The release log is the repository's
[CHANGELOG.md](../../CHANGELOG.md).

Earlier project documents (`docs/00`–`13`) remain the record of sources, contradictions, rule catalogue, IP
inventory and case evaluations; these documents refer to them instead of repeating them.
