# פריסה על Ubuntu 24.04 (ללא Docker)

> POC: SQLite + קבצים מקומיים. לייצור — PostgreSQL+PostGIS (`db/postgres_schema.sql`), SSO/MFA, הצפנת דיסק, גיבויים. אין להעלות נתוני תיקים אמיתיים לסביבת POC.

```bash
sudo apt update && sudo apt install -y python3.12-venv nginx fonts-noto-core clamav clamav-daemon
sudo useradd --system --create-home --home-dir /opt/bbp bbp
sudo -u bbp git clone <repo> /opt/bbp/app
cd /opt/bbp/app
sudo -u bbp python3 -m venv .venv
sudo -u bbp .venv/bin/pip install -r backend/requirements.txt
sudo -u bbp .venv/bin/python scripts/make_fixtures.py
sudo cp deploy/bbp.env.example /etc/bbp.env && sudo chmod 600 /etc/bbp.env   # edit values
sudo -u bbp bash -c 'set -a; . /etc/bbp.env; cd backend && ../.venv/bin/python -m app.seed --reset'
# frontend build (Node 20+)
cd frontend && npm ci && npm run build && sudo mkdir -p /var/www/bbp && sudo cp -r dist/* /var/www/bbp/
sudo cp ../deploy/bbp-api.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now bbp-api
sudo cp ../deploy/nginx-bbp.conf /etc/nginx/sites-available/bbp && sudo ln -s /etc/nginx/sites-available/bbp /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

אופציונלי: ODA File Converter (DWG→DXF) — הגדרת `BBP_ODA_CONVERTER`; Tesseract (`tesseract-ocr-heb`); Ollama להפעלת `local_ollama` (לאחר benchmark).

**הערה:** `BBP_ENV=production` חוסם את התחברות ההדגמה (X-User) — יש לחבר SSO לפני עלייה לייצור.
