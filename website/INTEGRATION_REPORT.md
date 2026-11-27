# Integration report — Permit360 by Kortex Digital website

Answers to the 17 items of the supplied `CLAUDE_UPDATE.md`, plus what changed from the supplied script.

## From the supplied script to this release

The supplied `build_permit360_website.py` was run unchanged (13 files: four one-page versions, CSS, SVG, demo
script, sitemap, robots, llms.txt). It was used as the starting brief; this release replaces it:

- **Domain:** the website is at **permit360.kortexd.com** (as in the script), on the same host as the application:
  website pages under `/he/ /ar/ /en/ /ru/`, website files under `/site/`, the application everywhere else.
- **Accuracy:** the script called committee discovery by block and parcel "a planned workflow" and the product
  "in development" with planned capabilities. Committee discovery, the request wizard with confirmation numbers,
  the AI assistant, the rule engine and the local-AI policy are implemented — the copy now says so, and only
  Rishuy Zamin / GIS integrations and OCR are presented as planned (`content/FACTS.md`).
- **Scale:** 4 one-page sites → 4 × (home + 9 guides) = 40 localized pages + chooser + 404.
- **Live functionality:** real committee lookup and a working demo-request form.

## The 17 items

| # | Item | Status |
|---|---|---|
| 1 | Add Permit360 to the corporate portfolio | Done and live on kortexd.com (patch in `deploy/kortexd-com/`). Uses the existing "building" artwork motif with a teal accent — no logo image was invented. |
| 2 | Product website | Live at https://permit360.kortexd.com/ (website paths beside the application; `deploy/nginx-permit360.kortexd.com.conf`). |
| 3 | Four translated, server-readable pages | Done, as static HTML (no client rendering needed for content). |
| 4 | Graphics, verified screenshots where available | Original SVG illustrations. Real application screenshots were not used: the live workspaces contain real case data and applicant names. Add approved, anonymised screenshots later. |
| 5 | Illustrative demos clearly labelled | Done: badge "illustration / example data" on the demo and a note under the hero drawing; the live lookup is badged "live data". |
| 6 | Localized pages (engineers, committees, rights, preparation, review, parcel search, security) | Done — 9 guides per language (also planning regulations, CAD & GIS). |
| 7 | Demo-request endpoint with consent and spam protection | Done in the application: `POST /api/public/demo-request` — consent required, honeypot, 3/hour per address and per e-mail, nginx rate limit; e-mailed to info@kortexd.com, not stored. Delivery tested from the live site. |
| 8 | Parcel discovery only through verified authorised data | Done: `GET /api/public/committee` uses the application's own copy of the Survey of Israel cadastre and the Planning Administration planning areas (the same data the product uses); no third-party API calls from the browser. |
| 9 | No private application data or proprietary algorithms | The public endpoint returns only public facts (committee name, planning area, code, district, locality, parcel area, shares) — no internal IDs, no case data. |
| 10 | Reciprocal hreflang, canonical URLs, sitemap | Done and checked automatically (`tests/check_site.py`). |
| 11 | Localized Open Graph images | Done: `assets/og/og-{he,ar,en,ru}.png`, 1200×630, correct RTL shaping. |
| 12 | Accessibility, responsive, genuine RTL | Done and tested (see `TEST_RESULTS.md`); logical CSS properties, per-script fonts. |
| 13 | Lighthouse and link validation | Done: link validation, Lighthouse 12.8 and axe-core 4 on the live site — accessibility, best practices, SEO 100; performance 97–100; no axe violations (`TEST_RESULTS.md`). |
| 14 | Verify factual claims against the code | Done: `content/FACTS.md` (checked against the code and the live database: 131 committees, ≈ 1.1 M parcels); writers were limited to it; a final scan removed two unsupported phrasings. |
| 15 | Search Console and indexing configuration | Done: the permit360.kortexd.com property is verified and the website sitemap (40 pages) resubmitted. |
| 16 | Document blockers, no fabricated results | `TEST_RESULTS.md` lists what was and was not run. |
| 17 | No production DNS changes | None made. None needed. |

## Open items

None. All four launch items are done: Lighthouse and axe on the live site, a real demo request delivered to
info@kortexd.com, the kortexd.com portfolio entry released, and the sitemap resubmitted in Search Console.
