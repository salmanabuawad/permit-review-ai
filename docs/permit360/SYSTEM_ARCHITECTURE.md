# System Architecture — target, and how we get there from today

## Decision: modular monolith

There is one deployable FastAPI application with internal modules and clear boundaries. Separate processes are used
only where isolation is a security or resource requirement, which today means the crawler (network isolation) and the
AI PC (GPU). Microservices, Docker and Kubernetes are not required; nothing in the measured load justifies them (3
active cases, about 30 s runs dominated by one LLM call).

## Component dependency diagram

```
                         ┌──────────────── Web UI (React/TS, RTL) ────────────────┐
                         │ Review360 · Regulation360 · Architect360 · Process360   │
                         │ Building360 · Admin (users, committees, AI, audit)      │
                         └──────────────────────────┬─────────────────────────────┘
                                                    │ HTTPS (nginx), session cookie, X-Authority
┌───────────────────────────── FastAPI modular monolith (user permit) ──────────────────────────────┐
│  api/ routers per module  ──►  application services                                                │
│                                                                                                    │
│  ┌ Intake ┐  ┌ Geometry ┐  ┌ Rules engine ┐  ┌ Knowledge ┐  ┌ Dependency Graph ┐  ┌ Workflow ┐    │
│  │ ingest │─►│ facts,   │─►│ applicability│◄─│ clauses,  │  │ nodes, edges,    │  │ (P360)   │    │
│  │ typing │  │ measures │  │ evaluation   │  │ hierarchy │  │ fingerprints,    │  └──────────┘    │
│  └────────┘  └──────────┘  │ evidence     │  │ retrieval │  │ invalidation     │                  │
│       │            │       └──────┬───────┘  └─────┬─────┘  └────────┬─────────┘                  │
│       └────────────┴──────────────┴────────────────┴─────────────────┘                             │
│                         │                                     │                                    │
│                 AI Gateway (router, prompts, cache, cost)   Audit · Attestation · Security          │
└──────────────┬──────────┴───────────────┬─────────────────────┬──────────────────────────────────────┘
               │ relay (outbound from PC) │ PostgreSQL 16       │ job rows
        ┌──────▼───────┐        ┌─────────▼─────────┐   ┌───────▼──────────────────────────┐
        │ AI PC        │        │ relational, JSON, │   │ Crawler process (permit-crawler) │
        │ llama.cpp    │        │ pgvector, PostGIS │   │ egress: public 80/443 only        │
        │ drawing read │        │ graph tables      │   │ sources, committees, XPLAN        │
        └──────────────┘        └───────────────────┘   └──────────────────────────────────┘
```

## Module boundaries (target package layout, introduced incrementally)

| Module | Owns | Today |
|---|---|---|
| `intake` | files, versions, typing, extracted fields | `ingest/`, `intake/`, `batch_import.py` |
| `geometry` | drawing conversion results, measurements, fingerprints | `geometry.py`, `units.py`, `agent/*` |
| `rules` | rule store, applicability, evaluation, evidence | `rules/*`, `coverage.py` |
| `knowledge` | sources, versions, clauses, embeddings, retrieval, hierarchy | `knowledge.py`, `source_monitor/*`, `regulatory.py`, `committees.py` |
| `graph` | dependency nodes and edges, invalidation, reuse decisions | `derivation_cache.py` (seed) |
| `review` | runs, findings, decisions, reports, attestations | `services.py`, `reports.py`, `attestation.py` |
| `workflow` | process templates, tasks, SLAs | case status fields only |
| `identity` | tenants, users, memberships, roles | `security.py`, `users.py`, `login.py` |
| `ai` | gateway, router, prompts, cache, costs | `ai/*` |
| `audit` | hash chain | `audit.py` |

Rule: a module calls another only through its service functions, never through its tables. `main.py` is split into
routers per module (backlog item B-01) without changing any URL.

## Processing model

- Synchronous API for reads and short writes.
- Durable job rows in PostgreSQL for long work: typing, conversion, onboarding, crawls, probes, and later graph
  recompute. Workers claim rows; a lease is recovered after a crash. One worker pool per resource class: CPU, crawler
  network, and GPU through the AI PC queue.
- No message broker until measured contention requires one.

## Data stores

PostgreSQL is the only database. It holds relational tables, JSON for evidence, pgvector for embeddings, PostGIS for
parcels and plan boundaries, and plain tables for the dependency graph. Files stay in content-addressed storage behind
a storage interface (local now; S3-compatible object storage is possible later). See DATABASE_ARCHITECTURE.md.

## Deployment

Ubuntu, systemd units, nginx and Let's Encrypt. Configuration lives in an env file (mode 600). PostgreSQL uses peer
authentication over the socket, so no database password exists. The crawler runs under its own uid behind nftables.
Rollback works by redeploying the previous commit; schema changes are forward-only migrations, each tested on a copy
of live data first.
