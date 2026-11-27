# Permit360 — בדיקת היתרי בנייה בסיוע AI

מוצר של Kortex Digital Ltd · https://permit360.kortexd.com

מערכת תומכת החלטה לבדיקת בקשות להיתר בנייה עבור ועדות לתכנון ובנייה, ולהכנת בקשות והגשתן עבור מהנדסים, אדריכלים ובעלי נכסים (Permit360 Pro): קליטת PDF / DXF / DWG / Excel במצב Offline, מדידה דטרמיניסטית, מנוע כללים עם אסמכתאות, דוח שלמות, דוח זכויות ודוח בודק (כולל PDF עברי), Workflow, Audit, AI Gateway מקומי/ענן/היברידי.
**כל תוצר הוא המלצה בלבד; ההחלטה בסמכות בעל תפקיד מוסמך.**

## מסמכים
| # | מסמך |
|---|---|
| 00 | [סתירות וחוסרים במקורות](docs/00_status_contradictions_gaps.md) |
| 01 | [רשם מקורות](docs/01_source_register.md) |
| 03 | [SRS, ארכיטקטורה, ERD, אבטחה וסיכונים](docs/03_srs_architecture_security.md) |
| 04 | [מאגר כללים ובדיקות גבול](docs/04_rules_catalog.md) |
| 05 | [Backlog ובדיקות](docs/05_workplan_backlog.md) |
| 07 | [קליטת מסמכים — צנרת, מודל נתונים, בעיות פתוחות](docs/07_document_intake.md) |
| 08 | [סריקת מקורות לכללים ובדיקה חוזרת](docs/08_source_monitor.md) |

## הפעלה מקומית (Windows, ללא Docker)
```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt
.venv/Scripts/python scripts/make_fixtures.py
cd backend && ../.venv/Scripts/python -m app.seed --reset && cd ..
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
```
בחלון נוסף:
```bash
cd frontend && npm install && npm run dev
```
פתחו http://127.0.0.1:5173 · תיעוד API: http://127.0.0.1:8000/api/docs
החלפת משתמש (תפקיד) — בתפריט שבראש המסך (הדגמה בלבד).

בדיקות:
```bash
cd backend && ../.venv/Scripts/python -m pytest -q
```

Ubuntu: [deploy/README.md](deploy/README.md).

## תרחיש הדגמה (נתונים פיקטיביים)
| תיק | מה מדגים |
|---|---|
| DEMO-0001 | הרחבה שחורגת 18 מ"ר מקו הבניין ו־30 מ"ר > 25 (כלל הדגמה) → **לא עומד** + סימון על התשריט; אי-התאמה שרטוט↔טבלת שטחים (30 מול 26); מרפסת כבלוק עם קשת; מסמכים חסרים לפי הנחיות 30.6/30.9 → "דורש בדיקה" (כלל טרם אושר) |
| DEMO-0002 | הרחבה תקינה — עומד |
| DEMO-0003 | חדר גג לפי מדיניות 13.1.2026, נסיגה **2.49 מ׳** → תוצאה מחושבת "לא עומד" אך **מוצגת "דורש בדיקה"** כי הכלל טרם אושר. החליפו למשתמש "מהנדס העיר", אשרו את הכלל `BB-POL26-RR-SETBACK` במאגר הכללים, הריצו שוב → "לא עומד" בגרסה חדשה |
| DEMO-0004 | מרפסת סוכה 1.2 מ׳ מגבול המגרש (כלל הדגמה ≥ 1.5) |

## קליטת מסמכים
מסך "תיקי בקשות" ← **קליטת מסמכים**: גרירת קבצים או חבילת ZIP (PDF, DXF/DWG, Excel ו־index.csv/json). המערכת מסווגת כל מסמך לפי תוכנו (טופס בקשה, פרוטוקול ועדה, מסמך תכנוני, שרטוט, מסמך נלווה, אינדקס), מפצלת פרוטוקול לבקשות, מחלצת את הנתונים — כולל הערות גורמי המקצוע והחלטת הוועדה — עם מקור (קובץ, עמוד, עמוד בפרוטוקול המקורי) וודאות לכל ערך, ומציגה תצוגה מקדימה לעריכה. קובצי אינדקס אינם יוצרים בקשות. ייבוא חוזר אינו יוצר כפילויות.
פירוט: [docs/07_document_intake.md](docs/07_document_intake.md) · דוח בדיקה על 31 בקשות אמיתיות: [docs/reports/import_test_report.md](docs/reports/import_test_report.md).

## סריקת מקורות ובדיקה חוזרת
**מאגר כללים ← סריקת מקורות**: שליפת המסמכים הרשמיים מרשם המקורות (כולל המסמכים המקושרים מעמוד המדיניות של בני ברק), שמירת כל גרסה, סימון מסמכים חדשים ושינויים, והצעות לסעיפי כלל עם עמוד וציטוט — לאישור כותב כללים; שום כלל אינו משתנה אוטומטית. אתרים שחוסמים שליפה (gov.il) — העלאה ידנית.
**תיקי בקשות ← בדיקה חוזרת**: הרצה מחדש של בדיקת הכללים על תיקים נבחרים או על כולם. פירוט: [docs/08_source_monitor.md](docs/08_source_monitor.md).

## מבנה
```
backend/app/        FastAPI: ingest, intake (document import), source_monitor (rule-source crawl), geometry, rules engine, AI gateway, reports, audit, RBAC
backend/migrations/ Alembic migrations (0001 baseline, 0002 intake entities, 0003 source monitor)
backend/tests/      122 בדיקות pytest (SQLite ו־PostgreSQL)
frontend/src/       React + TypeScript, RTL
knowledge/          תוכן פרויקט: כללים, מקורות, בסיס ידע, מוסכמת שכבות, מדיניות AI, ממשקים
fixtures/demo/      קבצי הדגמה שנוצרו ע"י scripts/make_fixtures.py
db/                 סכמת PostgreSQL/PostGIS ליעד הייצור
deploy/             systemd + Nginx + env לדוגמה
docs/               אפיון ותיעוד (docs/permit360: ארכיטקטורה ותכנית פיתוח)
```
