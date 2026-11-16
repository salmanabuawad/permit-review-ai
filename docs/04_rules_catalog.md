# 04 — מאגר כללים ראשוני

הקובץ המחייב: `knowledge/rules/*.yaml`. כאן תמצית לקריאה, עם בדיקות הגבול והבחנה בין אי-התאמה ודאית לחוסר נתונים.
**אף כלל אינו `PROFESSIONALLY_APPROVED`.** אישור — במסך "מאגר כללים" (מהנדס העיר/מנהל אגף), עם נימוק, ונרשם ביומן הביקורת.

## מצבי כלל
`SOURCE_MISSING` (אין מקור — לא ניתן לאשר) → `SOURCE_LOCATED` → `SOURCE_VERIFIED` (נקרא, עמוד וסעיף) → `PROFESSIONALLY_APPROVED` (מחייב). בנוסף: `DESIGN_ASSUMPTION` (בקרה פנימית), `DEMO_FIXTURE` (פעיל רק ברשות הדגמה), `RETIRED`.

## איך נקבעת התוצאה
| מצב | תוצאה |
|---|---|
| סוג בקשה / שלב / תוקף / תכנית / תנאי תחולה לא מתקיימים | **N/A** |
| חסר נתון לקביעת תחולה | **UNCERTAIN** + `APPLICABILITY_UNKNOWN` |
| חסרה מדידה / שכבה / נתון | **UNCERTAIN** + `INCOMPLETE` (לא "לא חוקי") |
| ערך הסף חסר במקור | **UNCERTAIN** + `THRESHOLD_SOURCE_MISSING` |
| הערך בתוך תחום אי-הוודאות של המדידה | **UNCERTAIN** + `WITHIN_UNCERTAINTY_BAND` |
| הנחיה איכותנית | **UNCERTAIN** + `REVIEW_REQUIRED` |
| תנאי למתן היתר | **UNCERTAIN** + `CONDITION_FOR_PERMIT` |
| חישוב FAIL בכלל שלא אושר | `computed_result=FAIL`, **status=UNCERTAIN** + `RULE_NOT_APPROVED` |
| חישוב FAIL בכלל מאושר / בקרה פנימית / הדגמה ברשות הדגמה | **FAIL** (המלצה לבודק) |
| שני כללים חלים עם ספים שונים לאותו נתון | ממצא **CONFLICT** נוסף, ללא הכרעה |

השוואה: ללא עיגול לטובת מבקש; סבילות נומרית בלבד 1e-6 (רעש חישובי). אי-ודאות מדידה נפרדת מסבילות משפטית (שחייבת להגיע מהמקור; ברירת מחדל 0).

## כללי בני ברק

| מזהה | כלל | מקור (עמ׳/סעיף) | סוג | תנאי | תחולה | מצב |
|---|---|---|---|---|---|---|
| BB-POL26-RR-SETBACK | נסיגת חדר גג חדש מחזית שפת הגג של קומת דירות הגג | מדיניות 13.1.2026, עמ׳ 3, סע׳ 4ג׳ | compare | **נסיגה ≥ 2.5 מ׳** (בנוסף לנסיגה בתכנית הגגות) | רק: תכנית לתוספת זכויות לפי המדיניות, שלב בדיקת תכנית, בניין קיים | SOURCE_VERIFIED; נקודת מדידה UNVERIFIED |
| BB-POL26-FLOORS | קומות טיפוסיות מעל קומת הכניסה (ללא התוספת וקומת דירות הגג) | שם, סע׳ 4ב׳ | compare לפי אזור | ב׳, ג׳: ≤ 5 · א׳, ב׳1: ≤ 4 | כנ"ל | SOURCE_VERIFIED |
| BB-POL26-RR-NO-SEPARATE-ACCESS | גישה לחדר הגג רק מתוך דירת הגג | שם, סע׳ 3ב׳, 4ו׳ | declared_bool | גישה נפרדת = לא | כנ"ל | SOURCE_VERIFIED |
| BB-POL26-CONSENT | הסכמות בכתב (תנאי סף) | שם, סע׳ 4ז׳ | compare לפי הצמדה | גג רכוש משותף: ≥ 100% · גג צמוד לדירת הגג: ≥ 75% | כנ"ל | SOURCE_VERIFIED |
| BB-POL26-BETTERMENT | היטל השבחה / הבטחתו — תנאי להיתר | שם, סע׳ 4ח׳ | condition | — | כנ"ל | SOURCE_VERIFIED |
| BB-SG16-30.5 | תוספת לכמה קומות לכל גובה הבניין (אגף) עפ"י בב/מק/105/אגפים | הנחיות 2016, עמ׳ 15 | qualitative | — | הרחבה בכמה קומות | SOURCE_VERIFIED (סתירה S4) |
| BB-SG16-30.6-PHOTOS | תמונות הבניין הקיים | שם, 30.6 | doc_required | — | כל התוספות | SOURCE_VERIFIED |
| BB-SG16-30.8-FACADE | חזית רחוב אחידה, אגפים שלמים | שם, 30.8 | qualitative | — | הרחבה/מרפסת/סוכה | SOURCE_VERIFIED |
| BB-SG16-30.9-MASTERPLAN | תכנית כוללנית לכל הבניין עם תוספות עתידיות | שם, 30.9 | doc_required | — | הרחבה/מרפסת | SOURCE_VERIFIED |
| BB-SG16-31.2-RAILING | מעקה בנוי בקומה שלא בונים בה | שם, 31.2 | compare (נתון מהחתך) | ≥ 1.05 מ׳ | קיימת קומה באגף שלא בונים בה | SOURCE_VERIFIED |
| BB-SG16-31.7-9 | אשפה/גז, תכנית פיתוח, שיפוץ לובי | שם, 31.7–31.9 | qualitative | — | הרחבה | SOURCE_VERIFIED |
| BB-B105-BUILDING-LINES | התאמה לקווי בניין | בב/105 — **חסר** | compare | שטח מחוץ למעטפת ≤ 0 | תכנית בב/105 חלה | SOURCE_MISSING |
| BB-B105-MAX-HEIGHT | גובה מרבי | בב/105 — **חסר** | compare | **חסר במקור** | כנ"ל | SOURCE_MISSING |
| BB-B105-RIGHTS-AREA | שטחי בנייה מותרים | בב/105 — **חסר** | compare | **חסר במקור** | כנ"ל | SOURCE_MISSING |
| BB-SERV24-NEW-ONLY | הנחיות שימושי שירות | הנחיות 08/2024 | qualitative | — | **בנייה חדשה בלבד** ⇒ N/A לתוספות | SOURCE_LOCATED |

## בקרה פנימית ומסמכים נדרשים
| מזהה | בדיקה | סף | מצב |
|---|---|---|---|
| QA-AREA-CAD-VS-TABLE | שטח מוצע בשרטוט מול טבלת השטחים | הפרש ≤ 1% (הנחה לכיול) | DESIGN_ASSUMPTION |
| QA-CAD-LAYERS | שכבות נדרשות לפי סוג בקשה | לפי `layer_convention.yaml` | DESIGN_ASSUMPTION |
| QA-REQ-* | טופס בקשה, מפת מדידה, טבלת שטחים, תכנית הגשה, מידע להיתר | נוכחות מסמך | SOURCE_LOCATED (לא פוסל אוטומטית עד אימות תקנות 2016) |

## בדיקות גבול (ב־`backend/tests/test_rules_engine.py`)
- נסיגה (כלל מאושר, מדידה מדויקת): **2.49 → FAIL · 2.50 → PASS · 3.00 → PASS** · 2.4999999 → PASS (רעש) · 2.4989 → FAIL.
- אותו כלל: מסלול רגיל → N/A · שלב בקשה להיתר → N/A · מרפסת → N/A · לפני 13.1.2026 → N/A.
- כלל לא מאושר, 2.49 → computed FAIL, status UNCERTAIN.
- אי-ודאות ±0.05: 2.52 → UNCERTAIN · 2.60 → PASS · 2.40 → FAIL.
- קומות: ב׳ 5 → PASS, 6 → FAIL; א׳ 4 → PASS, 5 → FAIL; ב׳1 5 → FAIL; אזור לא ידוע → UNCERTAIN.
- הסכמות: משותף 100 → PASS, 99 → FAIL; צמוד 75 → PASS, 74 → FAIL; הצמדה לא ידועה → UNCERTAIN.
- שני מקורות עם 2.5 ו־3.0 → CONFLICT.

**תצוגה:** בממשק ובדוח הסימן נשמר לוגית כ־"≥"; בהקשר RTL הדפדפן ו־python-bidi מציגים את הגליף המשוקף לפי Unicode (Bidi_Mirrored), כך שהקריאה מימין לשמאל נשארת "נסיגה ≥ 2.5". נבדק ב־`test_numbers_and_symbols_survive_bidi`.
