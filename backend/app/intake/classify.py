"""Content-based document classification (not by file name or extension alone).

Rules look for structural signals in the text: protocol headers and decision sections, plan
instructions, application-form fields, drawing characteristics. Each class gets a score; the
best score wins and the signals are returned for transparency. An AI classifier can be plugged
in through the AI gateway for low-confidence cases; the rules stay the default and the fallback.
"""
from __future__ import annotations

import re

from . import text as T
from .schemas import Classification

INDEX_COLUMNS = re.compile(r"מספר\s*בקשה|request.?(?:id|number)|case.?number", re.I)
FILE_COLUMN = re.compile(r"(?<![֐-׿])קובץ|file|תיקי(?:י)?ה|folder", re.I)


def looks_like_index(header_cells: list[str]) -> bool:
    joined = " | ".join(str(c) for c in header_cells if c is not None)
    return bool(INDEX_COLUMNS.search(joined))


def classify_pdf(pages_text: list[str], drawings_per_page: list[int] | None = None) -> Classification:
    raw = "\n".join(pages_text)
    c = T.compact(raw)
    n_pages = max(len(pages_text), 1)
    chars = sum(len(p.strip()) for p in pages_text)
    signals: dict[str, list[str]] = {k: [] for k in ("committee_protocol", "permit_application", "planning_regulation",
                                                     "architectural_drawing", "supporting_document")}
    score = dict.fromkeys(signals, 0.0)

    def hit(cls, w, why):
        score[cls] += w
        signals[cls].append(why)

    if re.search(r"פרוטוקול", c):
        hit("committee_protocol", 2, "המילה 'פרוטוקול'")
    if re.search(r"ועדתמשנה|הועדההמקומית|ועדהמקומית", c):
        hit("committee_protocol", 2, "אזכור ועדת תכנון")
    if re.search(r"ישיבהמספר|לישיבת", c):
        hit("committee_protocol", 1.5, "מספר ישיבה")
    if re.search(r"(?<![֐-׿])החלטה(?![֐-׿])", raw) or "הוחלט" in c:
        hit("committee_protocol", 1.5, "סעיף החלטה")
    if re.search(r"BAKPIRUT\d+|TBPIRUT\d+", raw):
        hit("committee_protocol", 3, "סימון פריט פרוטוקול (מערכת רישוי)")
    if re.search(r"הערותמהנדסהעיר|הערותמחלקתרישוי|הערותאדר", c):
        hit("committee_protocol", 1, "הערות גורמי מקצוע")

    if re.search(r"טופסבקשהלהיתר|בקשהלהיתרבנייה", c):
        hit("permit_application", 3, "כותרת טופס בקשה להיתר")
    if re.search(r"(?<![֐-׿])גוש", raw) and re.search(r"חלקה", raw):
        hit("permit_application", 1, "גוש וחלקה")
    if re.search(r"מהותהבקשה|תיאורהבקשה", c):
        hit("permit_application", 1, "מהות הבקשה")
    if re.search(r"חתימת(?:המבקש|עורך|בעל)|הצהרת", c):
        hit("permit_application", 1.5, "חתימות/הצהרות")

    if re.search(r"הוראותהתכנית|הוראותהתוכנית|תקנוןהתכנית", c):
        hit("planning_regulation", 3, "הוראות תכנית/תקנון")
    if re.search(r"מטרותהתכנית|מטרתהתכנית|שטחהתכנית|שטחהתוכנית", c):
        hit("planning_regulation", 1.5, "מטרות/שטח התכנית")
    if re.search(r"\d{3}-\d{7}", raw) or re.search(r"תכניתמתאר|תכניתמפורטת|תבע", c):
        hit("planning_regulation", 1, "מספר תכנית / תכנית מתאר")
    if re.search(r"הנחיותמרחביות", c):
        hit("planning_regulation", 1.5, "הנחיות מרחביות")

    if drawings_per_page and max(drawings_per_page) > 300 and chars / n_pages < 600:
        hit("architectural_drawing", 3, "דף שרטוט וקטורי עם מעט טקסט")
    if re.search(r"קנמ1|1:(?:50|100|200|250|500)\b", raw.replace('"', "")):
        hit("architectural_drawing", 1, "קנה מידה")
    if re.search(r"חתך|חזית(?:צפונית|דרומית|מזרחית|מערבית)|תכניתקומה", c):
        hit("architectural_drawing", 1, "חתכים/חזיתות")

    if re.search(r"מפתמדידה|נסחטאבו|הסכמ|תצהיר|צילום|אישור", c):
        hit("supporting_document", 1, "מסמך נלווה (מדידה/נסח/הסכמה/אישור)")

    # a protocol excerpt also contains "בקשה להיתר" and "גוש/חלקה" — protocol signals dominate
    if score["committee_protocol"] >= 5:
        score["permit_application"] *= 0.3
        score["planning_regulation"] *= 0.5
    best = max(score, key=score.get)
    if score[best] < 1.5:
        if chars < 50:
            return Classification(doc_class="supporting_document", confidence=0.3,
                                  method="ללא שכבת טקסט — נדרש OCR או סיווג ידני", signals=["אין טקסט"])
        return Classification(doc_class="supporting_document", confidence=0.4, method="לא נמצאו סימנים מובהקים",
                              signals=[])
    total = sum(score.values()) or 1
    conf = round(min(0.99, 0.5 + 0.5 * score[best] / total * min(1.0, score[best] / 5)), 2)
    return Classification(doc_class=best, confidence=conf, method="סיווג לפי תוכן", signals=signals[best])


def classify_file(name: str, kind: str, pages_text: list[str] | None = None,
                  drawings: list[int] | None = None, table_header: list[str] | None = None) -> Classification:
    if kind in ("dxf", "dwg"):
        return Classification(doc_class="architectural_drawing", confidence=0.95, method="קובץ CAD (שרטוט וקטורי)",
                              signals=[kind.upper()])
    if kind in ("csv", "json", "html", "xlsx") and table_header is not None and looks_like_index(table_header):
        return Classification(doc_class="metadata_index", confidence=0.95, method="טבלה עם עמודת מספר בקשה",
                              signals=[str(c) for c in table_header[:6] if c])
    if kind == "xlsx":
        return Classification(doc_class="supporting_document", confidence=0.7, method="גיליון שאינו אינדקס (טבלת שטחים)",
                              signals=[])
    if kind == "pdf":
        return classify_pdf(pages_text or [], drawings)
    return Classification(doc_class="supporting_document", confidence=0.3, method="סוג קובץ לא מזוהה", signals=[])
