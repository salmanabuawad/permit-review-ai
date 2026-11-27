# Permit360 website — test results (27.11.2026)

Build: `python website/build.py` → 41 HTML pages (4 home pages, 36 guide pages, 404). Live at https://permit360.kortexd.com/he/ since 27.11.2026.
All tests below were run on that build, served locally by `website/serve.py` (static files + `/api/public/*`
forwarded to the live application).

## Automated static checks — `python website/tests/check_site.py` → **OK, 0 errors, 0 warnings**

- 41 HTML files, 40 sitemap URLs, every page in the sitemap and every sitemap URL has a page.
- `lang` / `dir` correct on every page (he, ar → rtl; en, ru → ltr).
- Title 10–70 characters and meta description 70–170 characters on every page (content limits: ≤ 60 / 120–155).
- Exactly one `<h1>` per page; no skipped heading levels.
- Canonical = the page's own URL; `hreflang` he/ar/en/ru + `x-default` on every page, and every alternate links
  back (reciprocal).
- Every internal link and in-page anchor resolves.
- Every JSON-LD block parses (Organization, WebSite, SoftwareApplication, WebPage, BreadcrumbList, FAQPage).
- Every form field has a label.
- No stray Hebrew text in the Arabic, English or Russian pages (Hebrew proper names are marked `lang="he"`).

## Browser (built-in Chromium pane)

| Check | Result |
|---|---|
| Hebrew home, desktop 1366 px | layout correct, RTL, illustration labels inside their cards (fixed during testing) |
| English home, desktop | correct, LTR |
| Arabic home, 375 px | correct, RTL, no horizontal page scroll (`scrollWidth` = 375) |
| Russian guide page, 375 px | correct, no horizontal page scroll |
| Live committee lookup (he): block 2832 parcel 27 | real answer from the application: Hof Ashkelon, code 633, Southern district, 119,105 m² |
| Interactive demo | both editions, all 6 steps each, previous / next, keyboard arrows on the tabs; labelled "illustration" |
| Mobile menu and guides dropdown | open / close, `aria-expanded` updated, Escape closes the dropdown |
| Demo-request form, empty submit | shows the "required" message; no request sent. A real submission was **not** sent (it would e-mail info@kortexd.com) |
| Share images (og-he/ar/en/ru.png) | rendered with correct Hebrew / Arabic shaping (comma glyph and Arabic line spacing fixed during testing) |

## Accessibility

- Skip link, landmarks (`header`, `nav`, `main`, `footer`), labelled navigation, one H1, labelled form fields,
  `aria-live` on the lookup result and demo screen, tabs with `role="tab"` / `aria-selected`, decorative SVGs
  `aria-hidden`, the hero drawing `role="img"` with a localized title, focus outlines, `prefers-reduced-motion`
  respected (all animation off).
- Colour contrast: an in-page script measured every text element. Three small-text colours below 4.5:1 were
  darkened (live badge green, section labels, demo step numbers) and the sidebar button colour was fixed. Hero
  texts flagged by the script are false positives (the script read the translucent glow, not the navy behind it).
- **Not run:** axe-core / Lighthouse. Loading axe-core from a CDN into the page was blocked by the session's
  safety policy, and this machine has no Node/Chrome toolchain for Lighthouse. Run both before launch
  (`npx lighthouse https://permit360.kortexd.com/he/ --view`, axe DevTools).

## Performance (gzip sizes)

| Language | Home HTML | CSS | JS | Main font | Home total |
|---|---|---|---|---|---|
| he | 13 KB | 7 KB | 3 KB | 11 KB | ≈ 36 KB |
| ar | 14 KB | 7 KB | 3 KB | 65 KB (WOFF) | ≈ 90 KB |
| en | 13 KB | 7 KB | 3 KB | 47 KB | ≈ 71 KB |
| ru | 14 KB | 7 KB | 3 KB | 18 KB | ≈ 43 KB |

Guide pages ≈ 5 KB HTML. No raster images on pages (inline SVG), no third-party requests, fonts self-hosted
with `font-display: swap` and the main font preloaded, script deferred.

## Backend (application) — public endpoints

`backend/tests/test_projects.py::test_public_committee_lookup_and_demo_request` and the full suite:
**453 passed, 9 skipped** (local SQLite). Covered: resolved / ambiguous / not-found lookups, invalid input (422),
per-address rate limit (429), no internal IDs in the response; demo request needs consent, honeypot silently
drops bots, e-mail sent, per-address limit.

## Deployment (27.11.2026)

`website/deploy/nginx-permit360.kortexd.com.conf` installed (identical application part, website paths added),
`nginx -t` passed. Checked live: all four home pages and guide pages 200, unknown guide page 404 (website 404 page),
`/site/*`, sitemap, robots, llms.txt 200; `/` signed out → 302 to `/he/` (or `/ru/` etc. by Accept-Language),
signed in → application; `/login`, `/apply`, `/api/health` unchanged; Search Console verification file still
served; website pages on permit.kortexd.com → 301 to permit360.kortexd.com; the AI relay keeps polling
(`POST /llm-relay/agent/next` 204); live lookup returns Hof Ashkelon for 2832/27; no console errors under the
Content-Security-Policy.

## kortexd.com

Portfolio entry added on branch `permit360` (commit `dde4fbe`, not pushed). The site's own i18n check passes.
A full build of kortexd.com was **not** run: its `node_modules` on this PC is incomplete (Vite missing) and a clean
`npm ci` downloads packages — waiting for approval.
