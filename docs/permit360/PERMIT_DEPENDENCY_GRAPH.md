# Permit Dependency Graph (PDG): design

State: **PROPOSED**. Its seeds exist: the `derivation_cache` (results keyed by file SHA-256 + algorithm + version),
`check_runs.input_hashes`, the ruleset hash and per-file ingest reports.

## Purpose

Every result the system produces (a measurement, a calculation, a rule evaluation, a finding, a report line) is a
node, with directed edges from everything it was derived from. When an input changes, the graph names exactly which
results are stale. Everything else is reused, with a recorded reason.

Example chain: `wall entity → footprint polygon → floor area → total built area → building-rights rule → finding`.

## Model (PostgreSQL tables)

```
pdg_nodes(
  id            bigserial PK,
  tenant_id     text not null,            -- isolation; national nodes use tenant '*'
  kind          text not null,            -- see node kinds
  key           text not null,            -- stable identity within kind (e.g. file_id:page:entity_handle)
  fingerprint   text not null,            -- hash of the node's content / inputs
  algo          text,                     -- algorithm@version, rule@version, prompt@version, model@quant
  value_ref     text,                     -- where the value lives (table:id or storage path)
  status        text not null,            -- VALID | STALE | FAILED
  created_at, computed_at,
  unique(tenant_id, kind, key, fingerprint))

pdg_edges(
  from_node bigint references pdg_nodes, -- input
  to_node   bigint references pdg_nodes, -- derived result
  role      text,                        -- which input of the derivation
  primary key(from_node, to_node))
```

Node kinds: `application`, `application_version`, `document`, `page`, `drawing_version`, `entity`, `geometry`,
`measurement`, `calculation`, `fact`, `rule_version`, `source_version`, `clause`, `applicability`, `evaluation`,
`finding`, `decision`, `report`, `task`.

## Fingerprints (change detection, layered)

| Level | Fingerprint |
|---|---|
| file | SHA-256 of bytes (exists today) |
| normalised document | SHA-256 of extracted text after whitespace and RTL normalisation |
| page | SHA-256 per page text plus a per-page raster hash |
| drawing entity | hash of (layer, type, rounded coordinates in normalised units, text) |
| geometry | hash of the canonical polygon (WKB after snapping to tolerance) |
| structured data | hash of the canonical JSON of declared fields |
| rule / source | rule version id; source snapshot SHA-256 |
| AI result | hash of (task, prompt version, model, quantisation, evidence fingerprints) |

## Propagation algorithm

1. A new application version arrives, so its inputs are fingerprinted bottom-up.
2. For each input node whose fingerprint changed (or which is new or deleted), mark every node reachable through
   `pdg_edges` as STALE (a recursive CTE).
3. Recompute STALE nodes in topological order. A recomputed node whose new fingerprint equals the old one stops the
   propagation below it ("early cut-off").
4. VALID nodes are reused. Each reuse is logged with the evidence: "fingerprint unchanged for inputs X, Y".
5. Report: new, corrected, unchanged and newly unresolved findings, and newly applicable requirements.

## Safety rules (when reuse is forbidden)

- If an input of a derivation is not represented in the graph (dependency completeness unknown), run a broader
  recheck: recompute the derivation and everything downstream.
- Any change in a rule version, source version, applicability inputs (date, plan, lot, use), engine version or
  coverage inventory invalidates the evaluations that used them.
- When entity-level matching is unreliable (for example, a re-exported drawing with new handles), fall back to
  drawing-level invalidation.
- Policy switch: `incremental=false` forces a full review. On a sample of revisions both modes run and their outputs
  are compared (the incremental-vs-full regression test, TESTING_STRATEGY.md).

## Regulatory change impact

A new source version or rule version marks its `clause` and `rule_version` nodes. Queries across tenants are not
allowed, so impact analysis runs per tenant and lists unlocked applications whose evaluations reference the changed
node. Locked reports are never altered; they keep their original snapshot (historical reproducibility).

## Relation to today's code (migration path)

1. Wrap `derivation_cache.get_or_compute` so every call also writes nodes and edges: file → derivation.
2. Record rule evaluations as nodes with edges from the facts and rule version they read. The facts already carry
   their source in `evidence`.
3. Use the graph to skip unchanged evaluations and the AI summary when its evidence fingerprint is unchanged. That
   summary is about 94 % of run time today.
4. Add entity fingerprints when drawing conversion exposes stable entities.

## Protectability (technical description only)

The mechanism combines regulatory provenance with geometric lineage in a single dependency graph. Fingerprints at
several levels (file, page, entity, polygon, structured data, rule and source version, AI prompt and model) decide,
per result, whether a professionally reviewed finding may be reused. Reuse requires that dependency completeness can
be established; otherwise the system falls back to a wider recheck. Every reuse is recorded with its evidence.
Whether any of this is protectable intellectual property is a question for a patent attorney. This document makes no
patentability or novelty claim.
