# Knowledge Base Strategy

## Today

| Store | Content | State |
|---|---|---|
| source register | 265 sources (`knowledge/sources.yaml`, `sources.d/`), with jurisdiction for national sources | I |
| curated KB passages | 50 passages with citations (`knowledge/kb/*.yaml`), BM25 search | I |
| source texts | extracted texts of key documents (`knowledge/source_texts/`) | I |
| rights / lots / building provisions | Hof Ashkelon plan rights, lot 2832/368 ledger, provisions for 633-0928358 | I (one authority) |
| source monitor | crawled official documents, versions by SHA-256, numeric clause drafts (16 documents, 188 drafts live) | I |
| uploads | laws, plans and guidelines as unverified candidate passages | I |
| regulatory registry | professionally approved scope and limits with exact quotes (V10) | P (empty) |
| committee register | 131 committees, settlements, sites, vendor, candidate sources from the site probe | I (probe running 2026-11-26) |

## Target

1. **One clause model.** Every document version is split by legal structure (chapter, section, clause, definition,
   exception, table row, appendix). A requirement is never separated from its conditions. Each clause keeps the
   original Hebrew, normalised text, page, parent and children, topics, components, scope, dates, verification status
   and embedding model version.
2. **Hierarchy.** NATIONAL → DISTRICT → PLANNING_COMMITTEE → LOCAL_AUTHORITY → STATUTORY_PLAN → PROPERTY →
   APPLICATION. National knowledge is stored once. A committee's knowledge serves all its settlements (the committee
   register already models this).
3. **Pre-building for all 131 committees.** The committee register plus the site probe give, per committee: its site,
   request-search system, vendor and candidate sources. The next step is fetching those candidates through the
   crawler into versioned snapshots and clause extraction. Status moves NOT_STARTED → SITE_PROBED / SOURCES_FOUND →
   (candidates fetched) → (clauses extracted) → (professionally verified). Nothing is verified automatically.
4. **Provenance classes kept apart:** verified regulatory fact · extracted information · AI interpretation ·
   historical precedent · professional decision · unverified assumption. Retrieval results show their class.
5. **No false "new".** Every incoming document is compared by SHA-256, normalised text and clause hashes against what
   exists before it is called new or changed.
6. **Hybrid retrieval.** Exact clause and plan lookup, metadata filters (jurisdiction, date, tenant), trigram / BM25,
   vectors (e5-small, after a Hebrew benchmark), relationship expansion (definitions, exceptions, amendments), and an
   optional reranker. Mandatory checks come from the full applicable rule inventory, never from top-K retrieval.
7. **Terminology ontology.** Hebrew synonyms, spellings and abbreviations (חניה / חנייה, קו בניין / קו בנין / נסיגה,
   שטח עיקרי, שטח שירות, תכסית, …), and explicitly distinct concepts (internal versus external height). Used for
   query expansion and classification, and extendable by administrators.
8. **Change handling.** A new version gets a clause diff, then a change classification, then conflict detection, then
   impact analysis (affected unlocked applications, per tenant). New regulations are never applied retroactively to
   locked reviews.

## Sources of truth by priority

Official publication (gov.il, Reshumot, the committee's own site, mavat / XPLAN) comes first, then an authorised
upload by the authority, then secondary sources (marked as such). Committee decisions and past permits are precedent
only.
