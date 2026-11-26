# Regulatory Engine (Regulation360): rule schema, layers, precedence, conflicts

## Today

- **IMPLEMENTED:** `rules/engine.py` evaluates YAML rules (75 rules). It supports operators `< <= > >= == != between in`,
  conditions, severities, a legal level rank, a ruleset hash, conflict detection, and evidence-based evaluation in
  `rules/evidence.py`.
- **IMPLEMENTED:** the rule editor stores versions, approvals and notes in `rule_definitions` / `rule_approvals`.
- **PARTIAL:** the applicability resolver (`rules/applicability.py`), the V10 regulatory registry (`regulatory.py`),
  and limit conflicts.

## Regulatory layers (retrieval and applicability scopes, not automatic precedence)

| Layer | Scope key | Example |
|---|---|---|
| national law | `NATIONAL` | Planning and Building Law 1965 |
| national regulation | `NATIONAL` | Licensing regulations 2016, deviation regulations 2002 |
| national policy / TAMA | `NATIONAL` | TAMA 38, 39 |
| district plan | `DISTRICT:<district>` | district outline plans |
| committee | `PLANNING_COMMITTEE:<committee_id>` | committee policy, spatial guidelines |
| local authority | `LOCAL_AUTHORITY:<tenant>` | bylaws |
| statutory plan | `STATUTORY_PLAN:<plan_no>` | בב/105, 633-0928358 |
| parcel | `PROPERTY:<gush>/<helka>[/<lot>]` | lot ledger, parcel restrictions |
| application | `APPLICATION:<case>` | תיק מידע conditions, approved reliefs |

A committee may serve several authorities (`committee_settlements`, `municipalities.committee_id`, both IMPLEMENTED).
National knowledge is stored once and shared; local layers are visible only inside their jurisdiction.

## Executable rule schema (single store, target)

```yaml
id: HOF-HEIGHT-MAX            # unique, stable
version: 3                    # increments on any change; versions are immutable
title_he: גובה מרבי למבנה
description_he: ...
source:
  source_id: HOF-633-0928358  # register id
  snapshot_sha256: …          # exact document version
  section: "4.1.2"
  page: 12
  quote_he: "גובה הבניין לא יעלה על 9 מ'"   # verbatim, checked against the extracted page
effective_from: 2015-03-01
effective_until: null
jurisdiction: STATUTORY_PLAN:633-0928358
geo_applicability: {plan_area: true, zones: ["מגורים א"]}   # or reviewed polygon (EPSG:2039)
application_applicability: {permit_types: [new, addition], routes: [standard]}
inputs: [{fact: building.height_m, unit: m, evidence: [GEOMETRIC_MEASUREMENT, DRAWING_DIMENSION]}]
logic: {op: "<=", left: building.height_m, right: 9.0, tolerance: 0.05}
exceptions: [{ref: REL-DEVIATION-2002-2, effect: allows_relief, max: "10%"}]
precedence: {legal_level: plan, notes: "subject to deviation regulations"}
depends_on: [HOF-ZONE-RESOLVE]
verification: VERIFIED_SOURCE | SOURCE_LOCATED | SOURCE_MISSING
approval: {status: PROFESSIONALLY_APPROVED, by: user, at: …, note: …}
tests: [{facts: {building.height_m: 9.2}, expect: FAIL}, {facts: {building.height_m: 8.9}, expect: PASS}]
```

The logic language is restricted and declarative: comparison, ranges, ratio, sum, area and distance over named facts,
`all` / `any` / `not`, and conditions. Generated code is never executed. An AI model may propose a rule draft;
activation needs a verified source quote and professional approval. This is already enforced for drafts
(`rule_drafts`, `committee_reason`).

**Migration:** import the 75 YAML rules into `rule_definitions` as version 1, carrying their current approval states
(they are recorded as PROFESSIONALLY_APPROVED on the owner's instruction, and each records who approved it). Then
make the DB the only store, with YAML kept as an export format (backlog B-03).

## Precedence and conflicts

Precedence is recorded, never inferred. Each rule names its legal level and explicit relationships (`AMENDS`,
`SUPERSEDES`, `EXCEPTION_TO`, `DEPENDS_ON`, `CONFLICTS_WITH`). When two applicable rules disagree, the engine
classifies the pair:

| Class | Meaning | Effect |
|---|---|---|
| CONFIRMED_CONFLICT | same scope, period and quantity; incompatible values | both blocked from external findings; professional resolution task |
| POTENTIAL_CONFLICT | similar wording, different numbers (V10 candidate detection) | internal only |
| COMPLEMENTARY | both can hold (e.g. a minimum and a maximum) | both evaluated |
| DIFFERENT_SCOPE / DIFFERENT_PERIOD | does not overlap for this application | the non-applicable one is NOT_APPLICABLE |
| SUPERSEDED | explicit, verified supersession | the old rule is NOT_APPLICABLE, citing the supersession |
| UNRESOLVED | the evidence cannot decide | check UNRESOLVED |

The newest or strictest rule is never chosen automatically, and AI confidence does not resolve a legal question.

## Check statuses (per applicable check)

`PASS`, `CONFIRMED_VIOLATION`, `DOCUMENT_INCONSISTENCY`, `DECLARATION_MISMATCH`, `DISCRETIONARY_REVIEW_REQUIRED`,
`UNRESOLVED`, `NOT_APPLICABLE`, `EXECUTION_ERROR`. They map onto today's evidence statuses (`rules/evidence.py`).
Coverage is measured against the full applicable inventory (`coverage.py`), never only against the checks that ran.

## Historical permits and decisions

Approved permits and committee decisions are **precedent**, not rules. The learning module turns a missed reason into
a draft that needs approval, and nothing becomes a rule automatically.
