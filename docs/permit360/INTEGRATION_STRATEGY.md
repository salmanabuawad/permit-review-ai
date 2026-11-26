# Integration Strategy and Feasibility Matrix

Rule: no integration is described as working unless it has been tested against the real system. Development adapters
are labelled MOCK in code and in the UI. Today every external integration is `PLANNED` (`knowledge/integrations.yaml`,
Integrations page).

## Connector architecture

Each connector implements `discover()`, `read(query)`, an optional `write(payload)`, and `health()`. It declares its
authentication, data classification and rate limits, and runs in the crawler process when it needs the public
internet (network isolation). Credentials live in the env file, never in the database or the code. Every call is
audited.

## Feasibility matrix (what is known on 2026-11-26)

| System | Public access | Official API known? | Read / write | What we do today | Status |
|---|---|---|---|---|---|
| רישוי זמין (national licensing portal) | logged-in portal | not known to us | — | import of the exported request PDF: form number and declared fields with page citations (`batch_import.py`) | file import IMPLEMENTED; API UNKNOWN (ask the Planning Administration) |
| מבא"ת / mavat (plans) | public website (JavaScript app) | no documented public API found | read | plan numbers kept as text; documents uploaded by hand | MANUAL |
| XPLAN (ArcGIS REST, Planning Administration) | public map service | ArcGIS REST (public) | read | `plan_discovery.py` written and tested with mocks; disabled; the live endpoint was unreachable during V10 | NOT VERIFIED |
| gov.il pages | public | none (refuses automated requests, HTTP 403) | read | read through a browser by an operator (committee list 2026-11-26) | MANUAL |
| Committee sites, BarTech | public pages per committee (44 identified so far) | not known; public pages only | read | site probe: vendor, request-search link, candidate sources | IMPLEMENTED (public pages) |
| Committee sites, Complot | public pages (31 identified so far) | not known | read | same | IMPLEMENTED (public pages) |
| OneCity | — | not known | — | — | NOT STARTED |
| Municipal GIS / GovMap | varies | varies (GovMap has public layers) | read | — | NOT STARTED |
| Municipal ERP / DMS | per authority | per vendor | read / write | — | NOT STARTED, needs authority partnership |
| Control institutes / external approvers | — | — | — | statuses tracked by hand (waiting external) | MANUAL |
| AutoCAD / Revit | desktop | plugin APIs exist | read (design) | DWG / DXF / DWFX files only | FILE FORMATS IMPLEMENTED; plugins PROPOSED |
| Digital signature | — | national ID-card signatures, vendor services | — | internal HMAC-signed review attestations | INTERNAL ONLY |

## Per-integration record (to fill before building)

For each integration record: availability; authentication; authorisation and legal basis; read and write scope; data
ownership; field mapping; licensing and terms of use; rate limits; technical limits; test environment; and status. A
written agreement with the data owner comes before any write integration or any non-public read.

## Order

1. XPLAN live verification (public, read-only) through the crawler process.
2. Committee candidate sources: fetch, then snapshot, then clauses (public).
3. רישוי זמין: ask the Planning Administration about an official interface; keep the PDF import until then.
4. BarTech / Complot: ask the vendors about data access for client committees; public pages only until then.
