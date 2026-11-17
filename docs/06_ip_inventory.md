# 06 — IP Inventory (טיוטה לנספח ה5) — **לבדיקת עו"ד לפני הגשה/חתימה**

> זה אינו ייעוץ משפטי. הניתוח מבוסס על לשון ההסכם (עמ׳ 38 סע׳ 8; עמ׳ 45 נספח ה5).

## 1. מה ההסכם קובע
- **סע׳ 8.1:** בבעלות החברה והעירייה — מאגר הידע, מסמכי מקור, וקטורים, תוצרי אימון/כיול, **מנועי הכללים וכללי הבדיקה שהוגדרו לפרויקט**, לוחות בקרה, מבני דוחות, מטא-דאטה, לוגים, מדדים ותיעוד.
- **סע׳ 8.2:** לספק נשארות **רק** זכויות ברכיבים גנריים שפותחו **טרם ההתקשרות ושלא במסגרת הפרויקט**, עם רישיון שימוש בלתי מוגבל לעירייה.
- **סע׳ 8.3:** העירייה רשאית לפתח, להחליף ספק ולהעביר לרשויות אחרות; שיווק ע"י הספק — בהסכמה בכתב.
- **ה5 §1:** רכיב שלא נרשם ברשימה — **חזקה שהוא תוצר פרויקט בבעלות החברה והעירייה**.

**משמעות:** אין להניח שקוד גנרי חדש שייכתב בתקופת הפרויקט יישאר של הספק. מה שקיים היום (לפני חתימה) יכול להיחשב "קודם", בתנאי שהוא מתועד ונרשם בנספח.

## 2. הפרדה מבנית במאגר

| שכבה | נתיב | אופי | סיווג מוצע (לאישור עו"ד) |
|---|---|---|---|
| ליבה גנרית | `backend/app/rules/engine.py`, `geometry.py`, `units.py`, `ingest/*`, `ai/gateway.py`, `audit.py`, `security.py`, `reports.py`, `knowledge.py` (מנוע אחזור), `frontend/src/components/*` | אינו תלוי בבני ברק | **Pre-existing generic** — אם נרשם בה5 עם חותמת זמן |
| תוכן פרויקט | `knowledge/rules/bnei_brak.yaml`, `knowledge/kb/*`, `knowledge/sources.yaml`, `knowledge/layer_convention.yaml`, כל כלל/ידע שיוגדר בפרויקט | ספציפי לעירייה | **בבעלות העירייה** (סע׳ 8.1) |
| נתוני הדגמה | `fixtures/demo/*`, `knowledge/rules/demo.yaml` | פיקטיבי | Pre-existing generic |
| מסמכי מכרז | `docs/*` | — | לפי הסכם; לא קוד |

## 3. רשימת רכיבים (למילוי בנספח ה5)

| רכיב | תיאור | תאריך יצירה (commit) | רישיון | תלויות | ממשק |
|---|---|---|---|---|---|
| Rule engine | מנוע כללים דטרמיניסטי עם תחולה, אי-ודאות, gating ו־conflicts | ראו `git log` — commit ראשון 16.11.2026 | קנייני (הספק) | PyYAML | `evaluate(rules, facts, sources)` |
| Geometry service | מדידות CAD במטרים | כנ"ל | קנייני | Shapely (BSD-3) | `standard_measurements(entities)` |
| CAD ingest | DXF/DWG → ישויות | כנ"ל | קנייני | ezdxf (MIT); ODA File Converter (רישיון ODA — **נדרש לבירור**) | `parse_dxf(path)` |
| PDF ingest | טקסט ותיבות | כנ"ל | קנייני | PyMuPDF (**AGPL-3.0 או רישיון מסחרי של Artifex** — ⚠ לבירור) | `parse_pdf(path)` |
| Excel ingest | טבלת שטחים | כנ"ל | קנייני | openpyxl (MIT) | `parse_area_table(path)` |
| AI Gateway | ניתוב ספקים לפי מדיניות | כנ"ל | קנייני | — | `AIGateway.route()` |
| Audit | hash chain | כנ"ל | קנייני | — | `record()`, `verify_chain()` |
| Reports | PDF עברי RTL | כנ"ל | קנייני | reportlab (BSD), python-bidi (LGPL-3.0) | `render_pdf()` |
| Document intake | סיווג לפי תוכן, פענוח פרוטוקולי ועדה, חילוץ מובנה עם עיגון, ייבוא אידמפוטנטי | 17.11.2026 | קנייני (הספק) | PyMuPDF, Pydantic, Alembic (MIT) | `/api/import/*` |
| Source monitor | סריקת מקורות רשמיים, ניהול גרסאות, הצעות לסעיפי כלל | 17.11.2026 | קנייני (הספק) | PyMuPDF | `/api/source-monitor/*` |
| Web UI | React RTL | כנ"ל | קנייני | React (MIT), react-router (MIT), Vite (MIT) | — |
| API | FastAPI | כנ"ל | קנייני | FastAPI (MIT), SQLAlchemy (MIT), Uvicorn (BSD) | OpenAPI |

## 4. פעולות נדרשות
1. **commit מיידי** של המצב הנוכחי (חותמת זמן לפני ההגשה) ושמירת hash ה־commit.
2. החלטה על PyMuPDF: רישיון מסחרי מ־Artifex או החלפה ב־pypdf/pdfplumber (MIT) — AGPL עלול לחייב פתיחת קוד.
3. בירור רישיון ODA File Converter לשימוש בשרת.
4. ייעוץ עו"ד: האם "שיפור" לרכיב קיים במהלך הפרויקט נחשב תוצר פרויקט; נוסח רישיון; Escrow.
5. לאחר החתימה — כל פיתוח חדש יסומן בענף/תיקייה נפרדים, כדי שהסיווג יהיה ברור.
