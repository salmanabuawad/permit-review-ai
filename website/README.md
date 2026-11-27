# Permit360 by Kortex Digital — public website (permit.kortexd.com)

Static, four-language product website: Hebrew `/he/`, Arabic `/ar/`, English `/en/`, Russian `/ru/` — a home
page and nine guide pages per language. The authenticated application stays separate at
https://permit360.kortexd.com.

```
website/
  build.py            generator → dist/ (HTML, sitemap, robots, llms.txt, OG images)
  art.py              original SVG illustrations (cadastral / architectural linework)
  content/<lang>.json localized copy (original per language), FACTS.md (verified claims), SCHEMA.md
  assets/             site.css, site.js, self-hosted fonts (OFL)
  serve.py            local preview with /api/public/* forwarded to the application
  tests/check_site.py static checks (metadata, canonical, hreflang, sitemap, links, JSON-LD, labels)
  deploy/             nginx site, release script, deployment notes, kortexd.com patch
  SEO_STRATEGY.md · TEST_RESULTS.md
```

## Build and preview

```bash
.venv/bin/python website/build.py          # needs Pillow + fontTools (in the project venv)
python3 website/tests/check_site.py
python3 website/serve.py --port 8790        # http://127.0.0.1:8790/he/
```

## What is real and what is illustrated

- **Live:** the committee lookup on the home page calls `GET /api/public/committee` on the application —
  official cadastre and planning-area data. The demo-request form calls `POST /api/public/demo-request`, which
  e-mails info@kortexd.com (consent required, honeypot, rate limits; nothing stored).
- **Illustrated (labelled on the page):** the interactive Pro / Authority workspace, the hero drawing and the
  share images use example data.

## Editing content

Change `content/<lang>.json` (structure in `content/SCHEMA.md`). Every product claim must be in
`content/FACTS.md`; update that file first when the product changes. Rebuild and run the checks.

## Deployment

See `deploy/README.md`. Nothing has been deployed; DNS is unchanged.
