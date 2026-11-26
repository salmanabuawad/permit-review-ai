# 11 — V9 unified integration, 26.11.2026

What the V9 instruction (`CLAUDE_V9_Unified_Update.md`) asked, what was built and run, and what is blocked. Built
into the existing engines, not a rewrite. Baseline: tag `pre-v9-baseline` (465dd2d); work on branch
`v9-integration`, fast-forwarded to `main`.

## 0. The V9 bundle itself is not on this machine

The instruction refers to "the actual V5 cumulative code and V6–V8 additions plus a V9 offline integration CLI"
(`unified.py`) and to `Zikim_Lot368_Local_AI_Knowledge_Base.zip`. Neither exists here (searched the whole disk). So:

* `python unified.py test` of the bundle could not be run. A runner with the same operations
  (`scripts/unified.py test | spatial | dwf | bim | review | blind`) was built over this repository's engines.
* The V5 results quoted in the instruction (local building line −0.240 m / +0.009 m, well-zone overlap) are not
  reproduced — their geometry is not here. Their *rules* are encoded and tested (§4).
* The KB zip import is **blocked** (file absent).

## 1. Required-check inventory and coverage

`knowledge/coverage/required_checks.yaml` lists, per rule family (documents, land, areas, rights, route, spatial,
infrastructure/environment), the checks a review must complete and the rules that can satisfy each.
`backend/app/coverage.py` computes per check: COMPLETED / OPEN / NOT_APPLICABLE / FUTURE_STAGE / **NOT_IMPLEMENTED**
(no rule exists for it in this jurisdiction). `independent: true` checks (areas from geometry, height, coverage,
building lines) count a PASS only when it rests on measured or document evidence, not a declared value.

`final_decision` now returns NO_DEFECTS_IDENTIFIED only when every family is complete; an empty or partial check list
gives INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION. The old test asserting "one PASS → no defects" was changed accordingly.
The defects report's limitation names the families not fully checked.

## 2. Authenticated review record

`backend/app/attestation.py`, table `review_attestations` (migration 0005). A reviewer's attestation is created on the
server from the authenticated principal, bound to the run's digest (inputs' SHA-256, rule-set hash, every finding's
status and reviewer decision) and signed with HMAC-SHA256 using a server-only key (`BBP_ATTESTATION_KEY` or a 0600
key file under the storage dir). `verify` → VALID / STALE (run changed or a newer run exists) / INVALID (forged or
edited row). Locking a case records an APPROVED_FOR_REPORT attestation. Signatures are never returned to clients.
Only reviewer / department manager / city engineer can attest; only the latest run.

API: `POST/GET /api/runs/{id}/attestations`, `GET /api/runs/{id}/coverage`, `GET /api/runs/{id}/audit`
(internal audit record — every outcome, evidence, coverage, metrics; `audit.read` only), `GET /api/runs/{id}/metrics`.

Not changed: authentication is still the staging header behind nginx basic auth; production SSO/OIDC remains open.

## 3. Cache and metrics

`backend/app/derivation_cache.py`, table `derivation_cache`: document-scope key = file SHA-256 + algorithm + version
(a document shared by several applications is parsed once); case-scope key adds jurisdiction, application revision
and the hashes it depends on. `invalidate(sha)` removes a file's derivatives and every case result that used it.
Document text extraction uses it (`pdf_text/1`).

`run.summary.metrics`: wall time, CPU time, document-text time, local model tokens in/out (from the model server's
`usage`), latency, cost, cache hits/misses, and per drawing the AI-PC work (drawing-read seconds, image calls, model,
geometry algorithm versions). GPU utilisation itself is not sampled (the GPU is on the AI PC; its time is recorded per
file).

## 4. Engines

| Item | Status |
|---|---|
| **Legacy DWF / W2D** (`agent/dwf_legacy.py`) | **BLOCKED_NO_DECODER.** No licensed decoder (Autodesk DWF Toolkit, ODA Drawings SDK, validated ezdwf) is installed or licensed. The module inventories the package with archive limits (member count, total size, ratio, path traversal), records file / stream SHA-256, page ids and W2D header; paper size is labelled `paper_metadata_not_measurement`. A decoder that is found but not validated is still BLOCKED. Tested on the real Zikim sanitary annex (W2D 06.00) and the Karmiya 6-sheet DWF (W2D 06.01). |
| **DWG** | blocked as before: no ODA converter; DWG files stay NEEDS_CONVERSION. |
| **BIM (source D)** | `unified.py bim`: the Zikim "28655-2-Model.dwfx" is a 2D ePlot of a DWG (no BIM objects or phases) → NOT_AVAILABLE. IFC phases can be read but are corroboration only — model phases do not prove construction. |
| **Source C guard** | when the floor plans give more wall outlines than distinct floor diagrams (the outline did not close), source C is UNRESOLVED and internal, never a discrepancy. Found on 311-312 and 339-340 (§6). |
| **Spatial margins** (`app/rules/spatial.py`) | margin vs uncertainty: methods disagreeing in sign (the V5 −0.240 / +0.009 case) or a margin within uncertainty → UNRESOLVED; a violation on unverified (candidate) geometry → UNRESOLVED; only verified geometry can confirm. Not yet fed by a measured building-line engine (no ITM-controlled setback measurement exists). |
| **Well zones** | from plan 633-0723718 §6.4 ב(4), checked on the OCR of the approved scan: zone A forbids any building, zone B building that may pollute "such as residential", zone C only severe-pollution works (sewage facility, main sewer line, effluent irrigation); (ד) forbids fertilisation as an activity. Zone C overlap with a house is therefore **not** a residential ban; overlap alone is never a violation. |
| **Plan scoping** | no rights file or rule mentions 633-0928358; a test fails if one ever assumes it for Zikim. |
| **Short track (Karmiya 20260265)** | eligibility on the *gross* new construction (18 m² ≤ the 25 m² item) — the form's 1 m² is the net change after cancelling 17 m² approved but never built; that mismatch is a DOCUMENT_DISCREPANCY for clarification, not a route deviation. The 18 m² is from the applicant's description, so not confirmable; the plans are in an undecodable DWF. |

## 5. Blind evaluation isolation

`scripts/evaluate_blind.py`: every input is on `validation/cases/<id>/allowlist.yaml` with its SHA-256 and role; an
unlisted or changed file stops the run, and inputs are scanned for decision vocabulary (role labels alone prove
nothing). The engine result is frozen (`<id>.frozen.json` with its hash) before the ground truth is read; scoring
refuses an unfrozen or edited result. Ground truth moved **out of the repository** to the evaluation store
(`BBP_EVAL_STORE`, default `~/.local/share/permit-review-eval`, 0700; never on the app server); the repo keeps only
its SHA-256 (`validation/ground_truth.sha256`). Karmiya is a development dataset (`validation/dev_cases/`), never scored.

**Actual sample: 1 case scored, 0 with complete inputs** (target 30). 20210885: 2 of 2 official findings flagged
(undecidable without the drawings), 0 confirmed, 0 missed, 0 false positives, 0 unsupported. No precision figure is
meaningful at this size.

## 6. Zikim re-runs (from the original package files, separately)

Each case run on the 37 server from its own original package files (no file shared between cases; each file's
SHA-256 kept). Drawings converted and read on the AI PC (local vision model). Final runs:

| Case | Lots | Run | Decision | Confirmed defects | Discrepancies | Unresolved | Not checked |
|---|---|---|---|---|---|---|---|
| 10000612352-1 | 319-320 | 22 | RETURN_FOR_CORRECTIONS | 3 | 3 | 2 | 2 |
| 10000611793-1 | 311-312 | 6 | RETURN_FOR_CORRECTIONS | 3 | 2 | 1 | 11 |
| 10000615058-2 | 339-340 | 6 | RETURN_FOR_CORRECTIONS | 3 | 2 | 2 | 11 |

External defects, all three: construction-waste estimate missing (HA-633-WASTE-ESTIMATE), cumulative rights table
does not match the historic permits (HA-368-TABLE-VS-PERMITS), survey older than 6 months (QA-SURVEY-MAP-AGE).
Discrepancy, all three: area table vs the committee registry. 319-320 also: the land extract's parcel differs from the
declared one.

Coverage (no case can be NO_DEFECTS — `full_compliance_possible` is false for all):

* 319-320: documents, land, rights, infrastructure COMPLETE; areas, spatial PARTIAL. Open: areas from floor plans,
  height (drawing read, not a measurement), building lines (no ITM setback engine).
* 311-312 and 339-340: documents and rights COMPLETE; **land and infrastructure NONE** — the request form in both
  packages is an image-only scan and local OCR was too noisy to take parcel, owner or declared values from it, so they
  were left empty rather than guessed. Open: parcel identity, owner consent, areas (diagrams vs table, floor plans),
  floors, height, building lines, trees, wells/water lines, sewage.

Height read from the sheets: 319-320 ridge +6.05 (highest +8.85) PASS ≤ 9 m; 311-312 +6.85 PASS; 339-340 ridge +6.85
read twice with one stray +13.20 → **UNRESOLVED** (a single reading cannot confirm a violation — guard added after the
first run reported it as a confirmed defect).

Area sources: B (area diagrams) 319-320 = 311-312 = 366.101 / 125.247; 339-340 366.108 / 160.433. C (floor-plan
walls) 319-320 247.55 / 158.68; 311-312 and 339-340 fragmented outlines → UNRESOLVED (internal), not a discrepancy.

Metrics (last runs): wall 29–44 s, CPU 1.1–2.3 s, local tokens ≈5.2–5.4 k in / 0.3–0.5 k out, cost 0; document-text
cache 22–35 hits, 0 misses on re-runs. Drawing conversion/reading time is per file on the AI PC.

What went wrong on the way and was fixed:

* The first import sent preview field objects (gush/helka as dicts, placeholder case numbers) and only 2 documents;
  repaired in place: real case numbers, gush 2832, plan 633-0723718, all original files ingested, the two mis-split
  declaration pages archived (reversible). `.jpg` and legacy `.dwf` not ingested (no decoder).
* The repair ran as root → converted-PDF upload PermissionError; storage re-owned to `permit`, scripts now run as it.
* Before the drawings were converted, sections/elevations came out as confirmed missing → guard: an unconverted DWFX
  leaves those NOT_CHECKED.
* The first drawing reads failed (HTTP 500): the router kept the text model resident and the vision model could not
  load on the 6 GB GPU. The agent now unloads other models before a read; the two reads were re-queued and completed.

## 7. Deploy and rollback

* Deployed to the 37 server (health 200 on 127.0.0.1:8145): `backend/app`, `backend/migrations`, `knowledge/{coverage,rules,sources.d,rights,law}`,
  `scripts/unified.py`; `alembic upgrade head` (0004 → 0005); service restarted; health 200.
* Backup before migration: `/opt/permit-review-ai/var/bbp.sqlite3.pre-v9-202611260045`.
* Rollback: `alembic downgrade 0004` (drops only the two new tables), redeploy tag `pre-v9-baseline`, or restore the
  backup file. Old runs stay readable (new summary keys are optional).

## 8. Blockers (need input or authorisation)

1. The V9 bundle (V5–V8 code, `unified.py`) and `Zikim_Lot368_Local_AI_Knowledge_Base.zip` — not provided.
2. A licensed W2D decoder (DWF Toolkit / ODA) and a DWG reader — licence decision.
3. 20210885 original drawings — Rishui Zamin, applicant login only. 29 further complete cases with ground truth.
4. Production authentication (SSO/OIDC) for attestations outside staging.
