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
| Demo-request form, empty submit | shows the "required" message; no request sent |
| Share images (og-he/ar/en/ru.png) | rendered with correct Hebrew / Arabic shaping (comma glyph and Arabic line spacing fixed during testing) |

## Accessibility

- Skip link, landmarks (`header`, `nav`, `main`, `footer`), labelled navigation, one H1, labelled form fields,
  `aria-live` on the lookup result and demo screen, tabs with `role="tab"` / `aria-selected`, decorative SVGs
  `aria-hidden`, the hero drawing `role="img"` with a localized title, focus outlines, `prefers-reduced-motion`
  respected (all animation off).
- Colour contrast: an in-page script measured every text element. Three small-text colours below 4.5:1 were
  darkened (live badge green, section labels, demo step numbers) and the sidebar button colour was fixed. Hero
  texts flagged by the script are false positives (the script read the translucent glow, not the navy behind it).

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

Portfolio entry released and live on kortexd.com (links to https://permit360.kortexd.com/); the site's own i18n
check passes.

## Lighthouse 12.8 and axe-core 4 on the live site (27.11.2026)

Run from this PC (Node 24, Chrome 157, headless) against https://permit360.kortexd.com after deployment.
Full Lighthouse reports: `lighthouse/*.report.html` in the release ZIP.

| Page | Profile | Performance | Accessibility | Best practices | SEO | FCP | LCP | CLS | TBT |
|---|---|---|---|---|---|---|---|---|---|
| /he/ | desktop | 100 | 100 | 100 | 100 | 0.3 s | 0.3 s | 0.002 | 0 ms |
| /he/ | mobile | 100 | 100 | 100 | 100 | 1.3 s | 1.4 s | 0.018 | 30 ms |
| /ar/ | mobile | 97 | 100 | 100 | 100 | 1.8 s | 2.2 s | 0.069 | 50 ms |
| /en/ | mobile | 100 | 100 | 100 | 100 | 1.2 s | 1.5 s | 0.006 | 50 ms |
| /ru/ | mobile | 99 | 100 | 100 | 100 | 1.5 s | 1.6 s | 0.008 | 30 ms |
| /he/committee-lookup/ | mobile | 100 | 100 | 100 | 100 | 0.8 s | 0.9 s | 0.006 | 0 ms |
| /en/building-rights/ | mobile | 100 | 100 | 100 | 100 | 0.9 s | 1.2 s | 0.006 | 0 ms |

Fixed after the first run: text compression was off for the website's CSS / JS (gzip added in nginx, −33 KB per
page), one-year caching for the versioned stylesheet, script and fonts, minified CSS, and the logo link's
accessible name. Remaining notes are informational: the stylesheet is render-blocking (one 7 KB request), and the
Arabic page loads a 65 KB font (performance 97).

**axe-core** (all rules, WCAG 2.0 / 2.1 A–AA and best practices) on 16 pages — the four home pages, all nine
Hebrew guides and one guide each in Arabic, English and Russian — at 1366 px and 375 px, with the scroll
sections revealed, a live lookup result shown and the Authority demo open: **no violations**. The first run found
two (logo link name; the editions and lifecycle sections shared one heading) — both fixed and re-checked.

## Demo-request delivery (27.11.2026)

One test request sent from the live English page (https://permit360.kortexd.com/en/, contact form; marked
"Website test (please ignore)", contact address info@kortexd.com): the page showed its thank-you message, the
application answered `202` (it answers `503` when the mail server refuses), and the message arrived at
info@kortexd.com — confirmed by the recipient.

## Redesign (28.11.2026)

Light, institutional look after a review of Israeli permit portals, committee sites, permit consultancies and
international plan-review products: white header with a "request a demo" button and a compact language menu, light
hero with a shorter headline, an "official sources" strip (cadastre, planning areas, XPLAN, law and regulations),
accessibility statement and privacy policy in all four languages (`/<lang>/accessibility/`, `/<lang>/privacy/`),
and a footer note that Permit360 is not a government system and that the law and plans are the binding text.
`check_site.py`: 49 HTML files, 48 sitemap URLs, OK. Checked in the browser pane: Hebrew and English home at
1366 px, Hebrew home and mobile menu at 375 px (no horizontal scroll), Hebrew accessibility page.
axe-core and Lighthouse were not re-run for this release.
