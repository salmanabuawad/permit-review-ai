# פריסה על Ubuntu 24.04 (ללא Docker)

> POC: SQLite + קבצים מקומיים. לייצור — PostgreSQL+PostGIS (`db/postgres_schema.sql`), SSO/MFA, הצפנת דיסק, גיבויים. אין להעלות נתוני תיקים אמיתיים לסביבת POC.

```bash
sudo apt update && sudo apt install -y python3.12-venv nginx fonts-dejavu-core clamav clamav-daemon
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

אופציונלי: ODA File Converter (DWG→DXF) — הגדרת `BBP_ODA_CONVERTER`; Tesseract (`tesseract-ocr-heb`); מודל שפה ל־`local_ollama` — במחשב ה־AI דרך ה־relay (להלן), או Ollama מקומי (`BBP_LLM_BASE_URL=http://127.0.0.1:11434/v1`).

**מיגרציות:** סכמת המסד מנוהלת ב־Alembic ורצה אוטומטית בעליית השירות (`backend/migrations`). מסד קיים שנוצר לפני המיגרציות מסומן בגרסת הבסיס ומשודרג — הנתונים נשמרים. הרצה ידנית: `cd backend && ../.venv/bin/alembic upgrade head`.

**PostgreSQL:** `BBP_DATABASE_URL=postgresql+psycopg://user:pass@host/db` — המיגרציות והבדיקות נבדקו על PostgreSQL 16.

**הערה:** `BBP_ENV=production` חוסם את התחברות ההדגמה (X-User) — יש לחבר SSO לפני עלייה לייצור.

## מודל השפה במחשב ה־AI (LLM relay — כמו muniflow.kortexd.com)

לשרת אין GPU. מודל השפה רץ במחשב ה־AI (RTX 3050), שמושך את העבודות מהשרת. שום דבר לא מתחבר אל המחשב.

- **בשרת:** השירות `bbp-llm-relay` (`backend/app/ai/relay.py`, ‏`127.0.0.1:18112`, תהליך אחד) מחזיק כל קריאת מודל בזיכרון עד שהסוכן לוקח אותה ומחזיר את התשובה. ה־API פונה אליו כמו לכל שרת OpenAI-compatible: `BBP_LLM_BASE_URL=http://127.0.0.1:18112/v1`. Nginx חושף רק את `/llm-relay/agent/`.
- **במחשב ה־AI:** הסוכן `agent/bbp_ai_agent.py` (ספרייה סטנדרטית בלבד) מושך את `https://<host>/llm-relay/agent/next`, מריץ את הבקשה על ה־llama.cpp router ‏(:8081, אותו router שמשרת את muniflow) ומעלה את התשובה. הוא מעביר רק `/v1/chat/completions` ו־`/v1/models`.
- **המודל:** `local_ollama.model_version` ב־`knowledge/ai_policy.yaml` = ‏`ministral-3-8b-iq4xs`, אותו מודל ש־muniflow משתמש בו, כך שה־router לא מחליף מודלים בין שתי המערכות (החלפה = 10–60 שנ׳). מודל אחר חייב להיות section ב־`~/muniflow/.local/models.ini`.
- **בלי סוכן מחובר:** ה־relay עונה 503 מיד, והשער עובר לספק הבא במדיניות (מסווג מילות מפתח / חילוץ כללים / תבנית). המערכת ממשיכה לעבוד, רק בלי LLM. הסוכן נחשב מנותק אחרי שלוש משיכות שהוחמצו + 5 שנ׳.

**התקנה בשרת:**
```bash
# /etc/bbp.env: BBP_LLM_BASE_URL=http://127.0.0.1:18112/v1, BBP_LLM_RELAY_TOKEN=<python3 -c "import secrets; print(secrets.token_urlsafe(32))">
sudo cp deploy/bbp-llm-relay.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now bbp-llm-relay
sudo systemctl restart bbp-api
sudo cp deploy/nginx-bbp.conf /etc/nginx/sites-available/bbp && sudo nginx -t && sudo systemctl reload nginx   # כולל /llm-relay/agent/
```

**התקנה במחשב ה־AI:**
```bash
cp deploy/bbp-ai-agent.service ~/.config/systemd/user/
cp deploy/bbp-ai-agent.env.example ~/.config/bbp-ai-agent.env && chmod 600 ~/.config/bbp-ai-agent.env   # כתובת + אותו טוקן
systemctl --user daemon-reload && systemctl --user enable --now bbp-ai-agent
journalctl --user -u bbp-ai-agent -f
```

**בדיקה בשרת:** `curl -s 127.0.0.1:18112/health` (`"ok": true` = המחשב מחובר). `local_ollama` מופעל ב־`knowledge/ai_policy.yaml` (`enabled: true`). מסך "הגדרות AI" קובע רק את סדר הספקים. ב־gunicorn עם `--timeout 120` יש להגדיר `BBP_LLM_TIMEOUT` נמוך מ־120.

**מדיניות מידע:** `local_ollama` מוגדר `location: ON_PREM`, ולכן מותר לו לעבד מסמכי תיק. זה נכון רק אם מחשב ה־AI נמצא ברשת הרשות ובאחריותה.
