# Deploying the Permit360 website (permit.kortexd.com)

Nothing here has been applied to production. Every step below needs an explicit go-ahead.

## Layout on the server (185.229.226.37)

```
/var/www/permit.kortexd.com/releases/<stamp>/   static site (website/dist), one folder per release
/var/www/permit.kortexd.com/current             symlink to the live release
/etc/nginx/sites-available/permit.kortexd.com   website/deploy/nginx-permit.kortexd.com.conf
```

The application keeps running at https://permit360.kortexd.com (unchanged). Today both host names serve the
application from one nginx server block; the new configuration gives permit.kortexd.com its own block.
**No DNS change is needed** — both names already point to this server and the existing certificate
(`/etc/letsencrypt/live/permit.kortexd.com`) covers both.

## One-time installation (after approval)

```bash
# 1. upload a first release without switching anything
DEPLOY_HOST=root@185.229.226.37 bash website/deploy/deploy.sh --no-switch
ssh root@185.229.226.37 'ln -sfn $(ls -1dt /var/www/permit.kortexd.com/releases/* | head -1) /var/www/permit.kortexd.com/current'

# 2. replace the shared server block (keep a copy of the current one)
ssh root@185.229.226.37 'cp /etc/nginx/sites-available/permit.kortexd.com /root/permit.kortexd.com.nginx.bak'
scp website/deploy/nginx-permit.kortexd.com.conf root@185.229.226.37:/etc/nginx/sites-available/permit.kortexd.com
ssh root@185.229.226.37 'nginx -t && systemctl reload nginx'
```

Roll back: copy `/root/permit.kortexd.com.nginx.bak` back and reload nginx.

What the new configuration keeps working on permit.kortexd.com:
- `/llm-relay/agent/` and `/api/agent/` — the AI PC's relay and drawing-conversion agent connect to this host name.
- `/api/public/committee` and `/api/public/demo-request` — the website's live lookup and demo form (proxied to
  the application, rate-limited in nginx and in the application).
- Old application links (`/login`, `/cases/…`, `/apply`, …) and any other `/api/` call are redirected to
  permit360.kortexd.com.

## Each release

```bash
DEPLOY_HOST=root@185.229.226.37 bash website/deploy/deploy.sh
```

Builds, runs `website/tests/check_site.py`, uploads a new release, switches `current`, reloads nginx and keeps the
last five releases.

## Checks after deploying

```bash
curl -sI https://permit.kortexd.com/he/ | head -1                       # 200
curl -sI https://permit.kortexd.com/he/nope/ | head -1                  # 404
curl -s 'https://permit.kortexd.com/api/public/committee?gush=2832&helka=27' | head -c 200
curl -sI https://permit.kortexd.com/login | grep -i location            # → permit360.kortexd.com/login
curl -sI https://permit360.kortexd.com/ | head -1                       # application still 200
```

Then send one real demo request from https://permit.kortexd.com/en/#contact and confirm it reaches
info@kortexd.com (the form shows an error, never a false success, if mail is not configured).

## After the website is live (search engines)

1. Google Search Console: add the property `https://permit.kortexd.com/` (verify with an HTML file placed in
   `website/dist` or a DNS TXT record) and submit `https://permit.kortexd.com/sitemap.xml`.
2. Bing Webmaster Tools (optional): import from Search Console.
3. In the application (permit360.kortexd.com): point its public landing page and `about.html` to the website,
   and mark application pages `noindex`, so the two sites do not compete for the same searches.
4. kortexd.com: release the portfolio entry (branch `permit360` in `~/kortexd-website`, patch in
   `deploy/kortexd-com/`) with that site's own `deploy/deploy.sh site`.
