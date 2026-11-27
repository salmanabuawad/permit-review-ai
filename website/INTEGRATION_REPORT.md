# Integration report — Permit360 by Kortex Digital website

Answers to the 17 items of the supplied `CLAUDE_UPDATE.md`, plus what changed from the supplied script.

## From the supplied script to this release

The supplied `build_permit360_website.py` was run unchanged (13 files: four one-page versions, CSS, SVG, demo
script, sitemap, robots, llms.txt). It was used as the starting brief; this release replaces it:

- **Domain:** the script used `permit360.kortexd.com` for canonicals; the brief puts the public site on
  **permit.kortexd.com** and keeps the application separate at permit360.kortexd.com. This release follows the brief.
- **Accuracy:** the script called committee discovery by block and parcel "a planned workflow" and the product
  "in development" with planned capabilities. Committee discovery, the request wizard with confirmation numbers,
  the AI assistant, the rule engine and the local-AI policy are implemented — the copy now says so, and only
  Rishuy Zamin / GIS integrations and OCR are presented as planned (`content/FACTS.md`).
- **Scale:** 4 one-page sites → 4 × (home + 9 guides) = 40 localized pages + chooser + 404.
- **Live functionality:** real committee lookup and a working demo-request form.

## The 17 items

| # | Item | Status |
|---|---|---|
| 1 | Add Permit360 to the corporate portfolio | Done on branch `permit360` of `~/kortexd-website` (commit dde4fbe, patch in `deploy/kortexd-com/`). Not pushed or released. Uses the existing "building" artwork motif with a teal accent — no logo image was invented. |
| 2 | Prepare permit.kortexd.com as the product website | Done: `website/`, `deploy/nginx-permit.kortexd.com.conf` (passes `nginx -t`), `deploy/deploy.sh`. Not installed. |
| 3 | Four translated, server-readable pages | Done, as static HTML (no client rendering needed for content). |
| 4 | Graphics, verified screenshots where available | Original SVG illustrations. Real application screenshots were not used: the live workspaces contain real case data and applicant names. Add approved, anonymised screenshots later. |
| 5 | Illustrative demos clearly labelled | Done: badge "illustration / example data" on the demo and a note under the hero drawing; the live lookup is badged "live data". |
| 6 | Localized pages (engineers, committees, rights, preparation, review, parcel search, security) | Done — 9 guides per language (also planning regulations, CAD & GIS). |
| 7 | Demo-request endpoint with consent and spam protection | Done in the application: `POST /api/public/demo-request` — consent required, honeypot, 3/hour per address and per e-mail, nginx rate limit; e-mailed to info@kortexd.com, not stored. |
| 8 | Parcel discovery only through verified authorised data | Done: `GET /api/public/committee` uses the application's own copy of the Survey of Israel cadastre and the Planning Administration planning areas (the same data the product uses); no third-party API calls from the browser. |
| 9 | No private application data or proprietary algorithms | The public endpoint returns only public facts (committee name, planning area, code, district, locality, parcel area, shares) — no internal IDs, no case data. |
| 10 | Reciprocal hreflang, canonical URLs, sitemap | Done and checked automatically (`tests/check_site.py`). |
| 11 | Localized Open Graph images | Done: `assets/og/og-{he,ar,en,ru}.png`, 1200×630, correct RTL shaping. |
| 12 | Accessibility, responsive, genuine RTL | Done and tested (see `TEST_RESULTS.md`); logical CSS properties, per-script fonts. |
| 13 | Lighthouse and link validation | Link validation done. **Lighthouse not run** — no Node/Chrome toolchain on this machine, and loading axe-core from a CDN was blocked. Run before launch. |
| 14 | Verify factual claims against the code | Done: `content/FACTS.md` (checked against the code and the live database: 131 committees, ≈ 1.1 M parcels); writers were limited to it; a final scan removed two unsupported phrasings. |
| 15 | Search Console and indexing configuration | Prepared (sitemap, robots, structured data, steps in `deploy/README.md`). The Search Console property for permit.kortexd.com must be added by you after launch. |
| 16 | Document blockers, no fabricated results | `TEST_RESULTS.md` lists what was and was not run. |
| 17 | No production DNS changes | None made. None needed. |

## Open items before launch

1. Approve installing the nginx site and the first release (`deploy/README.md`).
2. Run Lighthouse and axe on the live URLs.
3. Send one real demo request after launch and confirm delivery.
4. Approve `npm ci` for a full kortexd.com build, then release the portfolio entry.
5. After launch: Search Console property for permit.kortexd.com; point the application's public landing page and
   `about.html` to the website and mark application pages `noindex`.
