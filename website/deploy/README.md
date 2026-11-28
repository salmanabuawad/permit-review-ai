# Deploying the Permit360 website (permit360.kortexd.com)

**Live since 27.11.2026.** The website and the application share one host:

| Path on https://permit360.kortexd.com | Served by |
|---|---|
| `/he/` `/ar/` `/en/` `/ru/` and their guide pages | website — `/var/www/permit360.kortexd.com/current` |
| `/site/` (CSS, JS, fonts, share images, 404 page) | website |
| `/sitemap.xml` `/robots.txt` `/llms.txt` | website |
| `/` | signed out (no `bbp_session` cookie) → 302 to the website in the browser's language; signed in → application |
| `/api/public/` | application (website lookup and demo form), rate-limited in nginx and in the application |
| everything else (`/login`, `/apply`, `/cases/…`, `/api/…`, `/assets/…`) | application, unchanged |

permit.kortexd.com keeps serving the application as before (the AI PC's relay connects to it); website pages
requested on permit.kortexd.com redirect to permit360.kortexd.com. No DNS or certificate change.

```
/var/www/permit360.kortexd.com/releases/<stamp>/   website releases (website/dist)
/var/www/permit360.kortexd.com/current             symlink to the live release
/etc/nginx/sites-enabled/permit.kortexd.com        = website/deploy/nginx-permit360.kortexd.com.conf
/root/permit.kortexd.com.nginx.bak                 the configuration before the website (roll back with this)
```

## Each release

```bash
DEPLOY_HOST=root@185.229.226.37 bash website/deploy/deploy.sh
```

Builds, runs `website/tests/check_site.py`, uploads a new release, switches `current`, tests and reloads nginx,
keeps the last five releases.

## Changing the nginx site

```bash
scp website/deploy/nginx-permit360.kortexd.com.conf root@185.229.226.37:/etc/nginx/sites-enabled/permit.kortexd.com
ssh root@185.229.226.37 'nginx -t && systemctl reload nginx'
```

Roll back: `cp /root/permit.kortexd.com.nginx.bak /etc/nginx/sites-enabled/permit.kortexd.com`, `nginx -t`, reload.

## Checks

```bash
curl -sI https://permit360.kortexd.com/ | grep -i location                 # → /he/ (signed out)
curl -sI https://permit360.kortexd.com/he/ | head -1                       # 200
curl -sI https://permit360.kortexd.com/he/nope/ | head -1                  # 404
curl -s 'https://permit360.kortexd.com/api/public/committee?gush=2832&helka=27' | head -c 120
curl -sI https://permit360.kortexd.com/login | head -1                     # 200 (application)
```

## Search engines

The Search Console property https://permit360.kortexd.com/ is already verified; resubmit
`https://permit360.kortexd.com/sitemap.xml` (it now lists the 48 website pages, including the accessibility statement and privacy policy). The application's own pages are
`noindex` and disallowed in robots.txt.

## kortexd.com

Portfolio entry on branch `permit360` of `~/kortexd-website` (patch in `deploy/kortexd-com/`), linking to
https://permit360.kortexd.com/ — released with that site's own `deploy/deploy.sh site` after a full build.
