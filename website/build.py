#!/usr/bin/env python3
"""Build the Permit360 public website (permit360.kortexd.com, next to the application) into website/dist.

    python website/build.py [--base https://permit360.kortexd.com] [--api ""] [--app ""]

The website shares its host with the application: pages under /he/ /ar/ /en/ /ru/, its files under /site/
(the application owns /site/ and every other path).

Four localized versions (/he/, /ar/, /en/, /ru/), each with a home page and nine guide pages, built from
content/<lang>.json (original copy per language, facts from content/FACTS.md). Static HTML, one stylesheet, one
script, self-hosted fonts, inline SVG illustrations, JSON-LD, canonical + reciprocal hreflang, sitemap, robots,
llms.txt and per-language Open Graph images (Pillow with RTL shaping)."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from html import escape as e
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import art  # noqa: E402

HERE = Path(__file__).resolve().parent
LANGS = ["he", "ar", "en", "ru"]
LANG_NAME = {"he": "עברית", "ar": "العربية", "en": "English", "ru": "Русский"}
LANG_SHORT = {"he": "עב", "ar": "ع", "en": "EN", "ru": "RU"}
DIR = {"he": "rtl", "ar": "rtl", "en": "ltr", "ru": "ltr"}
SLUGS = ["building-permit-preparation", "building-permit-review", "engineers-architects", "planning-committees",
         "building-rights", "committee-lookup", "planning-regulations", "cad-gis", "local-ai-security"]
LEGAL = ["accessibility", "privacy"]   # statement pages (footer links), in every language
ART = {"building-permit-preparation": "documents", "building-permit-review": "review", "engineers-architects": "parcel",
       "planning-committees": "review", "building-rights": "rights", "committee-lookup": "committee",
       "planning-regulations": "law", "cad-gis": "drawing", "local-ai-security": "shield"}
ICON = {"building-permit-preparation": "evidence", "building-permit-review": "drawing", "engineers-architects": "users",
        "planning-committees": "committee", "building-rights": "rights", "committee-lookup": "search",
        "planning-regulations": "law", "cad-gis": "drawing", "local-ai-security": "shield"}
DISTRICTS = {"דרום": {"he": "דרום", "ar": "الجنوب", "en": "Southern", "ru": "Южный"},
             "מרכז": {"he": "מרכז", "ar": "المركز", "en": "Central", "ru": "Центральный"},
             "צפון": {"he": "צפון", "ar": "الشمال", "en": "Northern", "ru": "Северный"},
             "חיפה": {"he": "חיפה", "ar": "حيفا", "en": "Haifa", "ru": "Хайфа"},
             "ירושלים": {"he": "ירושלים", "ar": "القدس", "en": "Jerusalem", "ru": "Иерусалимский"},
             "תל אביב": {"he": "תל אביב", "ar": "تل أبيب", "en": "Tel Aviv", "ru": "Тель-Авивский"}}

# Micro-labels inside the illustrated demo screens (example data — every screen is labelled as an illustration).
MOCK = {
 "he": dict(gush="גוש", helka="חלקה", lot="מגרש", find="איתור הוועדה", committee="ועדה מקומית לתכנון ובנייה — דוגמה",
   other="ועדה שכנה — דוגמה", resolved="זוהתה לפי גבול מרחב התכנון", area="מרחב תכנון", plans="תכניות חלות", covers="חלה על כל החלקה",
   part="חלה על חלק", inforce="בתוקף", deposited="בהפקדה", rights="זכויות בנייה למגרש", main="שטח עיקרי", service="שטחי שירות",
   floors="קומות", height="גובה", front="קו בניין קדמי", side="קו בניין צדי", permitted="מותר", source="מקור", q="מה קו הבניין הקדמי במגרש?",
   a="לפי הוראות התכנית החלה, קו הבניין הקדמי הוא 4.00 מ׳. תכנית בהפקדה עשויה לשנות זאת — כדאי לבדוק מול הוועדה.",
   src="תקנון התכנית, סעיף 6.2, עמ׳ 14 · הנחיות מרחביות, עמ׳ 3", docs="מסמכי הבקשה", form="טופס בקשה", survey="מפת מדידה",
   plan="תכנית הגשה (DWG)", areas="טבלת שטחים", sections="חתכים וחזיתות", uploaded="הועלה", missing="חסר", ready="מוכנות להגשה",
   blockers="חסמים לתיקון", b1="קו בניין צדי 2.62 מ׳ — נדרש 3.00 מ׳", b2="חסרים חתכים וחזיתות", submit="הגשה ומספר אישור",
   inbox="בקשות שהתקבלו", recv="התקבלה דרך Permit360 Pro", files="קבצים", classified="סווגו לפי תוכן", reg="הוראות חלות",
   law="חוק התכנון והבנייה", regs="תקנות הרישוי 2016", taba="התכנית החלה", guide="הנחיות הוועדה", layer="שכבת BUILDING · DXF",
   setback="קו בניין 3.00 מ׳", measured="נמדד", required="נדרש", uncertainty="אי-ודאות מדידה", finding="ממצאים", ok="עומד",
   bad="לא עומד", review="דורש בדיקה", na="לא חל", f1="קו בניין צדי", f2="גובה המבנה", f3="מספר קומות", f4="ממ״ד",
   decision="החלטת הבודק/ת", v1="גרסה 1", v2="גרסה 2 — לאחר תיקון", fixed="תוקן", returned="הוחזר להשלמות", alt="דוגמה להמחשה",
   card1_k="ועדה מוסמכת", card1_v="זוהתה לפי גוש וחלקה", card1_s="קדסטר · מרחבי תכנון רשמיים", card2_k="מוכנות להגשה",
   card2_a="✓ 14 בדיקות עומדות", card2_b="! 2 דורשות תיקון", card3_k="ממצאים עם מקור", card3_s="סעיף · עמוד · מסמך"),
 "ar": dict(gush="الحوض", helka="القسيمة", lot="القطعة", find="تحديد اللجنة", committee="لجنة تخطيط وبناء محلية — مثال",
   other="لجنة مجاورة — مثال", resolved="حُددت حسب حدود منطقة التخطيط", area="منطقة التخطيط", plans="المخططات السارية",
   covers="يسري على كامل القسيمة", part="يسري على جزء", inforce="ساري المفعول", deposited="قيد الإيداع", rights="حقوق البناء للقسيمة",
   main="المساحة الرئيسية", service="مساحات الخدمة", floors="الطوابق", height="الارتفاع", front="خط البناء الأمامي",
   side="خط البناء الجانبي", permitted="المسموح", source="المصدر", q="ما هو خط البناء الأمامي في القسيمة؟",
   a="وفق تعليمات المخطط الساري، خط البناء الأمامي 4.00 م. قد يغيّر مخطط قيد الإيداع ذلك — يُنصح بالتحقق مع اللجنة.",
   src="تعليمات المخطط، البند 6.2، ص 14 · التعليمات المكانية، ص 3", docs="مستندات الطلب", form="نموذج الطلب", survey="خارطة مساحة",
   plan="مخطط التقديم (DWG)", areas="جدول المساحات", sections="المقاطع والواجهات", uploaded="تم الرفع", missing="ناقص",
   ready="الجاهزية للتقديم", blockers="عوائق للتصحيح", b1="خط بناء جانبي 2.62 م — المطلوب 3.00 م", b2="المقاطع والواجهات ناقصة",
   submit="التقديم ورقم التأكيد", inbox="طلبات واردة", recv="وصل عبر Permit360 Pro", files="ملفات", classified="صُنّفت حسب المحتوى",
   reg="الأحكام السارية", law="قانون التخطيط والبناء", regs="أنظمة الترخيص 2016", taba="المخطط الساري", guide="تعليمات اللجنة",
   layer="طبقة BUILDING · DXF", setback="خط بناء 3.00 م", measured="المقاس", required="المطلوب", uncertainty="عدم يقين القياس",
   finding="النتائج", ok="مطابق", bad="غير مطابق", review="يتطلب مراجعة", na="لا ينطبق", f1="خط البناء الجانبي", f2="ارتفاع المبنى",
   f3="عدد الطوابق", f4="غرفة محصنة", decision="قرار المراجِع", v1="النسخة 1", v2="النسخة 2 — بعد التصحيح", fixed="صُحّح",
   returned="أُعيد للاستكمال", alt="مثال توضيحي", card1_k="اللجنة المختصة", card1_v="حُددت حسب الحوض والقسيمة",
   card1_s="مساحة رسمية · مناطق تخطيط", card2_k="الجاهزية للتقديم", card2_a="✓ 14 فحصاً مطابقاً", card2_b="! 2 تتطلب تصحيحاً",
   card3_k="نتائج مع مصدرها", card3_s="بند · صفحة · مستند"),
 "en": dict(gush="Block", helka="Parcel", lot="Lot", find="Find committee", committee="Local Planning and Building Committee — example",
   other="Neighbouring committee — example", resolved="Found from the planning-area boundary", area="Planning area", plans="Applicable plans",
   covers="Covers the whole parcel", part="Covers part", inforce="In force", deposited="Deposited", rights="Building rights for the plot",
   main="Main area", service="Service area", floors="Floors", height="Height", front="Front building line", side="Side building line",
   permitted="Permitted", source="Source", q="What is the front building line on this plot?",
   a="Under the applicable plan's provisions, the front building line is 4.00 m. A deposited plan may change this — check with the committee.",
   src="Plan provisions, clause 6.2, p. 14 · Spatial guidelines, p. 3", docs="Application documents", form="Application form",
   survey="Survey map", plan="Submission drawing (DWG)", areas="Area table", sections="Sections and elevations", uploaded="Uploaded",
   missing="Missing", ready="Submission readiness", blockers="Blockers to fix", b1="Side building line 2.62 m — 3.00 m required",
   b2="Sections and elevations missing", submit="Submit and get a confirmation number", inbox="Incoming applications",
   recv="Received via Permit360 Pro", files="files", classified="classified by content", reg="Applicable provisions",
   law="Planning and Building Law", regs="Licensing Regulations 2016", taba="Applicable plan", guide="Committee guidelines",
   layer="BUILDING layer · DXF", setback="Building line 3.00 m", measured="Measured", required="Required", uncertainty="Measurement uncertainty",
   finding="Findings", ok="Complies", bad="Does not comply", review="Requires review", na="Not applicable", f1="Side building line",
   f2="Building height", f3="Number of floors", f4="Safe room (mamad)", decision="Reviewer decision", v1="Version 1", v2="Version 2 — corrected",
   fixed="Fixed", returned="Returned for completion", alt="Illustrative example", card1_k="Responsible committee",
   card1_v="Found by block and parcel", card1_s="Cadastre · official planning areas", card2_k="Submission readiness",
   card2_a="✓ 14 checks comply", card2_b="! 2 need correction", card3_k="Findings with sources", card3_s="Clause · page · document"),
 "ru": dict(gush="Блок", helka="Участок", lot="Лот", find="Найти комиссию", committee="Местная комиссия по планированию — пример",
   other="Соседняя комиссия — пример", resolved="Определена по границе района планирования", area="Район планирования",
   plans="Действующие планы", covers="Распространяется на весь участок", part="На часть участка", inforce="Действует", deposited="На утверждении",
   rights="Права застройки участка", main="Основная площадь", service="Служебная площадь", floors="Этажи", height="Высота",
   front="Передняя линия застройки", side="Боковая линия застройки", permitted="Разрешено", source="Источник",
   q="Какая передняя линия застройки на участке?",
   a="По положениям действующего плана передняя линия застройки — 4,00 м. План на утверждении может это изменить — уточните в комиссии.",
   src="Положения плана, п. 6.2, с. 14 · Пространственные указания, с. 3", docs="Документы заявки", form="Бланк заявки",
   survey="Топосъёмка", plan="Чертёж подачи (DWG)", areas="Таблица площадей", sections="Разрезы и фасады", uploaded="Загружено",
   missing="Нет", ready="Готовность к подаче", blockers="Что исправить", b1="Боковая линия 2,62 м — требуется 3,00 м",
   b2="Нет разрезов и фасадов", submit="Подача и номер подтверждения", inbox="Входящие заявки", recv="Получено через Permit360 Pro",
   files="файлов", classified="классифицированы по содержанию", reg="Применимые положения", law="Закон о планировании и строительстве",
   regs="Правила лицензирования 2016", taba="Действующий план", guide="Указания комиссии", layer="Слой BUILDING · DXF",
   setback="Линия застройки 3,00 м", measured="Измерено", required="Требуется", uncertainty="Погрешность измерения",
   finding="Выводы", ok="Соответствует", bad="Не соответствует", review="Требует проверки", na="Не применимо",
   f1="Боковая линия застройки", f2="Высота здания", f3="Число этажей", f4="Защищённая комната", decision="Решение проверяющего",
   v1="Версия 1", v2="Версия 2 — исправлена", fixed="Исправлено", returned="Возвращено на доработку", alt="Иллюстративный пример",
   card1_k="Ответственная комиссия", card1_v="Определена по блоку и участку", card1_s="Кадастр · официальные районы",
   card2_k="Готовность к подаче", card2_a="✓ 14 проверок пройдено", card2_b="! 2 требуют исправления",
   card3_k="Выводы с источником", card3_s="Пункт · страница · документ"),
}


def chip(kind: str, text: str) -> str:
    return f'<span class="chip {kind}">{e(text)}</span>'


def num(x) -> str:
    return f'<span class="m-num">{e(str(x))}</span>'


def mock_screens(m: dict) -> dict:
    """HTML for the 6 + 6 illustrated demo screens (example data)."""
    pro = [
        f'<div class="m-stack"><div class="m-row"><div style="flex:1 1 120px"><span class="m-label">{e(m["gush"])}</span><div class="m-input">6650</div></div>'
        f'<div style="flex:1 1 120px"><span class="m-label">{e(m["helka"])}</span><div class="m-input">112</div></div>'
        f'<div style="flex:1 1 120px"><span class="m-label">{e(m["lot"])}</span><div class="m-input">27</div></div></div>'
        f'<div class="m-row"><span class="chip info">{e(m["find"])} →</span></div>{art.mini_map(m["committee"], m["other"])}</div>',
        f'<div class="m-stack"><div class="m-card"><small>{e(m["resolved"])}</small><b>{e(m["committee"])}</b></div>'
        f'<div class="m-row"><div class="m-card"><small>{e(m["area"])}</small><b>{num("000")}</b></div><div class="m-card"><small>{e(m["gush"])} / {e(m["helka"])}</small><b>{num("6650 / 112")}</b></div></div>'
        f'{art.mini_map(m["committee"], m["other"])}</div>',
        f'<div class="m-stack"><table class="m-table"><thead><tr><th>{e(m["plans"])}</th><th></th><th></th></tr></thead><tbody>'
        f'<tr><td>{num("101-0000001")}</td><td>{e(m["covers"])}</td><td>{chip("ok", m["inforce"])}</td></tr>'
        f'<tr><td>{num("101-0000002")}</td><td>{e(m["part"])}</td><td>{chip("warn", m["deposited"])}</td></tr></tbody></table>'
        f'<table class="m-table"><thead><tr><th>{e(m["rights"])}</th><th>{e(m["permitted"])}</th><th>{e(m["source"])}</th></tr></thead><tbody>'
        f'<tr><td>{e(m["main"])}</td><td>{num("120%")}</td><td>{num("6.1")}</td></tr><tr><td>{e(m["floors"])}</td><td>{num("3")}</td><td>{num("6.3")}</td></tr>'
        f'<tr><td>{e(m["front"])}</td><td>{num("4.00 m")}</td><td>{num("6.2")}</td></tr><tr><td>{e(m["side"])}</td><td>{num("3.00 m")}</td><td>{num("6.2")}</td></tr></tbody></table></div>',
        f'<div class="m-stack"><div class="m-msg q">{e(m["q"])}</div><div class="m-msg a">{e(m["a"])}<span class="m-src">↳ {e(m["src"])}</span></div></div>',
        f'<div class="m-stack"><b>{e(m["docs"])}</b><ul class="m-list">'
        + "".join(f'<li><span>{e(m[k])}</span>{chip("ok" if ok else "warn", m["uploaded"] if ok else m["missing"])}</li>'
                  for k, ok in (("form", 1), ("survey", 1), ("plan", 1), ("areas", 1), ("sections", 0))) + "</ul></div>",
        f'<div class="m-stack"><div class="m-row" style="align-items:center"><div style="flex:1 1 220px"><span class="m-label">{e(m["ready"])}</span>'
        f'<div class="m-progress"><i style="width:86%"></i></div></div><b class="m-num" style="font-size:26px;color:#0b6f6b">86%</b></div>'
        f'<b>{e(m["blockers"])}</b><ul class="m-list"><li><span>{e(m["b1"])}</span>{chip("bad", m["bad"])}</li><li><span>{e(m["b2"])}</span>{chip("warn", m["missing"])}</li></ul>'
        f'<div class="m-row"><span class="chip info">{e(m["submit"])} · {num("P360-2026-000123")}</span></div></div>',
    ]
    auth = [
        f'<div class="m-stack"><b>{e(m["inbox"])}</b><ul class="m-list">'
        f'<li><span>{num("P360-2026-000123")} · {e(m["recv"])}</span>{chip("info", "INTAKE")}</li>'
        f'<li><span>{num("38")} {e(m["files"])} · {e(m["classified"])}</span>{chip("ok", "PDF · DWG · XLSX")}</li></ul>'
        f'<table class="m-table"><tbody><tr><td>{e(m["form"])}</td><td>{chip("ok", "PDF")}</td></tr><tr><td>{e(m["plan"])}</td><td>{chip("ok", "DWG")}</td></tr>'
        f'<tr><td>{e(m["areas"])}</td><td>{chip("ok", "XLSX")}</td></tr></tbody></table></div>',
        f'<div class="m-stack"><b>{e(m["reg"])}</b><ul class="m-list"><li><span>{e(m["law"])}</span>{chip("na", "1965")}</li>'
        f'<li><span>{e(m["regs"])}</span>{chip("na", "2016")}</li><li><span>{e(m["taba"])} · {num("101-0000001")}</span>{chip("ok", m["inforce"])}</li>'
        f'<li><span>{e(m["guide"])}</span>{chip("info", "PDF · p. 3")}</li></ul></div>',
        f'<div class="m-stack">{art.plan_drawing(m)}</div>',
        f'<div class="m-stack">{art.plan_drawing(m)}<div class="m-row"><div class="m-card"><small>{e(m["measured"])}</small><b>{num("2.62 m")}</b></div>'
        f'<div class="m-card"><small>{e(m["required"])}</small><b>{num("≥ 3.00 m")}</b></div><div class="m-card"><small>{e(m["uncertainty"])}</small><b>{num("± 0.02 m")}</b></div></div></div>',
        f'<div class="m-stack"><table class="m-table"><thead><tr><th>{e(m["finding"])}</th><th></th><th>{e(m["source"])}</th></tr></thead><tbody>'
        f'<tr><td>{e(m["f1"])}</td><td>{chip("bad", m["bad"])}</td><td>{num("6.2 · p. 14")}</td></tr><tr><td>{e(m["f2"])}</td><td>{chip("ok", m["ok"])}</td><td>{num("6.3 · p. 15")}</td></tr>'
        f'<tr><td>{e(m["f3"])}</td><td>{chip("ok", m["ok"])}</td><td>{num("6.3 · p. 15")}</td></tr><tr><td>{e(m["f4"])}</td><td>{chip("warn", m["review"])}</td><td>{num("2016")}</td></tr></tbody></table></div>',
        f'<div class="m-stack"><ul class="m-list"><li><span>{e(m["v1"])} · {e(m["f1"])}</span>{chip("bad", m["returned"])}</li>'
        f'<li><span>{e(m["v2"])} · {e(m["f1"])} {num("3.05 m")}</span>{chip("ok", m["fixed"])}</li>'
        f'<li><span>{e(m["decision"])}</span>{chip("info", "✓")}</li></ul></div>',
    ]
    return {"pro": pro, "authority": auth}


# ---------------------------------------------------------------- page shell

def jsonld(obj) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def data_block(id_: str, obj) -> str:
    return f'<script type="application/json" id="{id_}">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def url(cfg, lang: str, slug: str | None = None) -> str:
    return f"{cfg.base}/{lang}/" + (f"{slug}/" if slug else "")


def head(cfg, lang: str, c: dict, title: str, desc: str, slug: str | None, extra_ld: list) -> str:
    alts = "\n".join(f'<link rel="alternate" hreflang="{l}" href="{url(cfg, l, slug)}">' for l in LANGS)
    alts += f'\n<link rel="alternate" hreflang="x-default" href="{url(cfg, "he", slug)}">'
    og = f"{cfg.base}/site/og/og-{lang}.png"
    locales = "".join(f'<meta property="og:locale:alternate" content="{json.load(open(HERE / "content" / f"{l}.json"))["meta"]["og_locale"]}">'
                      for l in LANGS if l != lang)
    return f"""<!doctype html>
<html lang="{lang}" dir="{DIR[lang]}" class="no-js" data-api="{e(cfg.api)}" data-app="{e(cfg.app)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="theme-color" content="#071a2b">
<link rel="canonical" href="{url(cfg, lang, slug)}">
{alts}
<meta property="og:type" content="website">
<meta property="og:site_name" content="Permit360 by Kortex Digital">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{url(cfg, lang, slug)}">
<meta property="og:image" content="{og}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:locale" content="{c['meta']['og_locale']}">{locales}
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/site/favicon.svg" type="image/svg+xml">
<link rel="preload" href="/site/fonts/{'heebo-hebrew' if lang == 'he' else 'noto-sans-arabic-400' if lang == 'ar' else 'inter-cyrillic' if lang == 'ru' else 'inter-latin'}{'-wght-normal.woff2' if lang != 'ar' else '.woff'}" as="font" type="font/{'woff' if lang == 'ar' else 'woff2'}" crossorigin>
<link rel="stylesheet" href="/site/site.css?v={cfg.version}">
<script src="/site/site.js?v={cfg.version}" defer></script>
{''.join(jsonld(x) for x in extra_ld)}
</head>"""


BRAND_MARK = ('<svg class="brand-mark" viewBox="0 0 36 36" aria-hidden="true" xmlns="http://www.w3.org/2000/svg"><rect width="36" height="36" rx="9" fill="#0f8a85"/>'
              '<path d="M8 22 18 16l10 6-10 6z" fill="#5fd6c8" fill-opacity=".35" stroke="#e8fbf8" stroke-width="1.4" stroke-linejoin="round"/>'
              '<path d="M13 21V11h6.5a4 4 0 0 1 0 8H13" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>')


GLOBE = ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">'
         '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.8 3.8 5.8 3.8 9s-1.2 6.2-3.8 9c-2.6-2.8-3.8-5.8-3.8-9S9.4 5.8 12 3z"/></svg>')


def header(cfg, lang: str, c: dict, slug: str | None) -> str:
    u = c["ui"]
    home = f"/{lang}/"
    guides = "".join(f'<a href="/{lang}/{s}/">{e(c["pages"][s]["nav"])}<small>{e(c["pages"][s]["h1"])}</small></a>' for s in SLUGS)
    langs = "".join(f'<a href="/{l}/{(slug + "/") if slug else ""}" hreflang="{l}" lang="{l}"' + (' aria-current="page"' if l == lang else "")
                    + f' title="{e(LANG_NAME[l])}">{e(LANG_NAME[l])}</a>' for l in LANGS)
    return f"""<body>
<a class="skip" href="#main">{e(u['skip'])}</a>
<header class="site-header">
 <nav class="wrap nav" aria-label="{e(u['nav_product'])}">
  <a class="brand" href="{home}">{BRAND_MARK}<span><b>Permit<span>360</span></b><small>by Kortex Digital</small></span></a>
  <button class="menu-btn" type="button" aria-expanded="false" aria-controls="nav-links"><span></span><span class="sr-only">{e(u['menu'])}</span></button>
  <div class="nav-links" id="nav-links">
   <a href="/{lang}/engineers-architects/">{e(u['nav_pro'])}</a>
   <a href="/{lang}/planning-committees/">{e(u['nav_authority'])}</a>
   <div class="nav-drop"><button type="button" aria-expanded="false" aria-haspopup="true">{e(u['nav_guides'])}</button><div class="drop-panel">{guides}</div></div>
   <a href="{home}#contact">{e(u['nav_contact'])}</a>
  </div>
  <div class="nav-actions">
   <div class="lang-drop"><button type="button" aria-expanded="false" aria-haspopup="true" aria-label="{e(u['language'])}: {e(LANG_NAME[lang])}">{GLOBE}<span>{e(LANG_SHORT[lang])}</span></button>
    <div class="lang-switch" role="navigation" aria-label="{e(u['language'])}">{langs}</div></div>
   <a class="nav-signin" href="{cfg.app}/login?lang={lang}">{e(u['signin'])}</a>
   <a class="btn btn-primary btn-sm" href="/{lang}/#contact">{e(u['request_demo'])}</a>
  </div>
 </nav>
</header>"""


def footer(cfg, lang: str, c: dict) -> str:
    f, u = c["footer"], c["ui"]
    prod = (f'<li><a href="/{lang}/engineers-architects/">{e(u["nav_pro"])}</a></li><li><a href="/{lang}/planning-committees/">{e(u["nav_authority"])}</a></li>'
            f'<li><a href="/{lang}/#demo">{e(c["home"]["demo"]["title"])}</a></li><li><a href="{cfg.app}/login?lang={lang}">{e(u["signin"])}</a></li>')
    guides = "".join(f'<li><a href="/{lang}/{s}/">{e(c["pages"][s]["nav"])}</a></li>' for s in SLUGS)
    langs = "".join(f'<li><a href="/{l}/" hreflang="{l}" lang="{l}">{e(LANG_NAME[l])}</a></li>' for l in LANGS)
    return f"""<footer class="site-footer">
 <div class="wrap">
  <div class="foot-grid">
   <div class="foot-brand"><a class="brand" href="/{lang}/">{BRAND_MARK}<span><b>Permit<span>360</span></b><small>by Kortex Digital</small></span></a>
    <p>{e(f['tagline'])}</p><p>{e(f['status'])}</p></div>
   <div><h2>{e(f['product'])}</h2><ul>{prod}</ul></div>
   <div><h2>{e(f['guides'])}</h2><ul>{guides}</ul></div>
   <div><h2>{e(f['company'])}</h2><ul><li><a href="https://kortexd.com/">Kortex Digital</a></li><li><a href="/{lang}/#contact">{e(u['request_demo'])}</a></li>{langs}</ul></div>
  </div>
  <p class="foot-disclaimer">{e(f['disclaimer'])}</p>
  <div class="foot-bottom"><span dir="ltr">© {date.today().year} Kortex Digital Ltd · Permit360</span>
   <nav class="foot-legal" aria-label="{e(f['company'])}"><a href="/{lang}/accessibility/">{e(f['accessibility'])}</a><a href="/{lang}/privacy/">{e(f['privacy_policy'])}</a><a href="mailto:info@kortexd.com" dir="ltr">info@kortexd.com</a></nav></div>
 </div>
</footer>
</body>
</html>"""


def org_ld(cfg):
    return {"@type": "Organization", "@id": "https://kortexd.com/#organization", "name": "Kortex Digital Ltd", "alternateName": "Kortex Digital",
            "url": "https://kortexd.com/"}


def app_ld(cfg, lang, c):
    return {"@type": "SoftwareApplication", "@id": f"{cfg.base}/#software", "name": "Permit360", "alternateName": ["Permit360 Pro", "Permit360 Authority"],
            "applicationCategory": "BusinessApplication", "applicationSubCategory": "Building permit preparation and review",
            "operatingSystem": "Web browser", "url": f"{cfg.base}/", "inLanguage": LANGS, "areaServed": {"@type": "Country", "name": "Israel"},
            "description": c["meta"]["home_description"], "publisher": {"@id": "https://kortexd.com/#organization"},
            "audience": [{"@type": "BusinessAudience", "audienceType": c["ui"]["nav_pro"]}, {"@type": "BusinessAudience", "audienceType": c["ui"]["nav_authority"]}]}


def faq_ld(items):
    return {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": q["a"]}} for q in items]}


# ---------------------------------------------------------------- home

def home(cfg, lang: str, c: dict) -> str:
    h, u, m = c["home"], c["ui"], MOCK[lang]
    ld = {"@context": "https://schema.org", "@graph": [org_ld(cfg), app_ld(cfg, lang, c),
          {"@type": "WebSite", "@id": f"{cfg.base}/#website", "url": f"{cfg.base}/", "name": "Permit360 by Kortex Digital", "inLanguage": LANGS,
           "publisher": {"@id": "https://kortexd.com/#organization"}},
          {"@type": "WebPage", "url": url(cfg, lang), "name": c["meta"]["home_title"], "description": c["meta"]["home_description"], "inLanguage": lang,
           "isPartOf": {"@id": f"{cfg.base}/#website"}, "about": {"@id": f"{cfg.base}/#software"}}, faq_ld(h["faq"])]}
    L = h["lookup"]
    lookup_i18n = {k: L[k] for k in ("checking", "resolved", "ambiguous", "not_found", "unlinked", "invalid", "error", "rate", "share", "area", "code",
                                    "district", "locality", "parcel_area", "sqm", "note", "continue", "gush", "helka")}
    lookup_i18n["districts"] = {k: v[lang] for k, v in DISTRICTS.items()}
    D = h["demo"]
    demo_i18n = {"steps_pro": D["steps_pro"], "steps_authority": D["steps_authority"], "step": D["step"]}
    F = c["form"]
    form_i18n = {k: F[k] for k in ("sending", "ok", "error", "rate", "required")}
    proof = "".join(f"<li>{e(x)}</li>" for x in h["proof"])
    def edition(key, cls, slug):
        x = h[key]
        return (f'<article class="edition {cls} reveal" id="{key}"><span class="edition-label">{e(x["label"])}</span><h3>{e(x["title"])}</h3><p>{e(x["text"])}</p>'
                f'<ul class="checks">{"".join(f"<li>{e(b)}</li>" for b in x["bullets"])}</ul>'
                f'<a class="btn btn-outline" href="/{lang}/{slug}/">{e(u["read_more"])} <span class="arrow" aria-hidden="true">→</span></a></article>')
    lifecycle = "".join(f'<li class="reveal"><b>{e(x["title"])}</b><span>{e(x["text"])}</span></li>' for x in h["lifecycle"]["items"])
    picons = ["evidence", "people", "local", "israel"]
    principles = "".join(f'<div class="principle reveal">{art.icon(picons[i])}<h3>{e(x["title"])}</h3><p>{e(x["text"])}</p></div>'
                         for i, x in enumerate(h["principles"]["items"]))
    guides = "".join(f'<a class="guide reveal" href="/{lang}/{s}/"><b>{e(c["pages"][s]["nav"])}</b><span>{e(c["pages"][s]["description"])}</span>'
                     f'<span class="more">{e(u["read_more"])} <span class="arrow" aria-hidden="true">→</span></span></a>' for s in SLUGS)
    faq = "".join(f'<details><summary>{e(x["q"])}</summary><p>{e(x["a"])}</p></details>' for x in h["faq"])
    roles = "".join(f'<option value="{k}">{e(v)}</option>' for k, v in F["roles"].items())
    hero_art = art.hero({"alt": m["alt"], **{k: m[k] for k in ("card1_k", "card1_v", "card1_s", "card2_k", "card2_a", "card2_b", "card3_k", "card3_s")}},
                       rtl=DIR[lang] == "rtl")
    return head(cfg, lang, c, c["meta"]["home_title"], c["meta"]["home_description"], None, [ld]) + header(cfg, lang, c, None) + f"""
<main id="main">
<section class="hero">
 <div class="wrap hero-grid">
  <div>
   <span class="eyebrow"><i aria-hidden="true"></i>{e(h['eyebrow'])}</span>
   <h1>{e(h['h1'])} <span class="accent">{e(h['h1_accent'])}</span></h1>
   <p class="lead">{e(h['lead'])}</p>
   <div class="hero-actions">
    <a class="btn btn-primary" href="#contact">{e(u['request_demo'])} <span class="arrow" aria-hidden="true">→</span></a>
    <a class="btn btn-ghost" href="{cfg.app}/login?register=1&amp;lang={lang}">{e(h['cta_primary'])}</a>
    <a class="btn-link" href="#demo">{e(h['cta_secondary'])} <span class="arrow" aria-hidden="true">→</span></a>
   </div>
   <ul class="proof" aria-label="Permit360">{proof}</ul>
  </div>
  <div class="hero-visual"><div class="frame">{hero_art}</div><p class="visual-note">{e(m['alt'])}</p></div>
 </div>
</section>

<section class="sources-strip" aria-labelledby="src-title">
 <div class="wrap"><b id="src-title">{e(h['sources']['title'])}</b><ul>{"".join(f"<li>{e(x)}</li>" for x in h['sources']['items'])}</ul></div>
</section>

<section class="lookup wrap" aria-labelledby="lookup-title">
 <div class="lookup-card">
  <form class="lookup-form" id="lookup-form" novalidate>
   <span class="badge live">{e(u['live'])}</span>
   <h2 id="lookup-title" style="margin-top:12px">{e(L['title'])}</h2>
   <p>{e(L['text'])}</p>
   <div class="fields">
    <label class="field">{e(L['gush'])}<input name="gush" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="off" dir="ltr" required></label>
    <label class="field">{e(L['helka'])}<input name="helka" inputmode="numeric" pattern="[0-9]*" maxlength="5" autocomplete="off" dir="ltr" required></label>
    <button class="btn btn-dark" type="submit">{e(L['button'])}</button>
   </div>
  </form>
  <div class="lookup-result" id="lookup-result" aria-live="polite"><div class="lr-empty">{art.lookup_empty()}<span>{e(L['note'])}</span></div></div>
 </div>
 {data_block('lookup-i18n', lookup_i18n)}
</section>

<section class="section" aria-labelledby="ed-title">
 <div class="wrap">
  <div class="section-head center reveal"><span class="kicker">Permit360</span><h2 id="ed-title">{e(h['pro']['label'])} · {e(h['authority']['label'])}</h2></div>
  <div class="editions">{edition('pro', 'pro', 'engineers-architects')}{edition('authority', 'authority', 'planning-committees')}</div>
 </div>
</section>

<section class="statement"><div class="wrap reveal"><h2>{e(h['advantage']['title'])}</h2><p>{e(h['advantage']['text'])}</p></div></section>

<section class="section alt" id="demo" aria-labelledby="demo-title">
 <div class="wrap">
  <div class="section-head reveal"><h2 id="demo-title">{e(D['title'])}</h2><p>{e(D['text'])}</p></div>
  <div class="demo-shell reveal">
   <div class="demo-top">
    <div class="tabs" role="tablist" aria-label="{e(D['title'])}">
     <button type="button" role="tab" id="tab-pro" aria-selected="true" aria-controls="demo-panel" data-role="pro">{e(D['tab_pro'])}</button>
     <button type="button" role="tab" id="tab-authority" aria-selected="false" aria-controls="demo-panel" tabindex="-1" data-role="authority">{e(D['tab_authority'])}</button>
    </div>
    <span class="badge sim">{e(u['simulated'])}</span>
   </div>
   <div class="demo-body" id="demo-panel" role="tabpanel" aria-labelledby="tab-pro">
    <ol class="steps" aria-label="{e(D['title'])}"></ol>
    <div class="stage">
     <div class="screen" aria-live="polite"><div class="screen-bar"><i></i><i></i><i></i><span></span></div><div class="screen-body"></div></div>
     <div class="stage-nav"><button class="btn btn-outline btn-sm prev" type="button"><span class="arrow" aria-hidden="true" style="transform:scaleX(-1)">→</span> {e(D['prev'])}</button><span></span>
      <button class="btn btn-dark btn-sm next" type="button">{e(D['next'])} <span class="arrow" aria-hidden="true">→</span></button></div>
    </div>
   </div>
   <noscript><div style="padding:20px"><ol>{''.join(f"<li><b>{e(s['title'])}</b> — {e(s['text'])}</li>" for s in D['steps_pro'])}</ol><ol>{''.join(f"<li><b>{e(s['title'])}</b> — {e(s['text'])}</li>" for s in D['steps_authority'])}</ol></div></noscript>
  </div>
  {data_block('demo-i18n', demo_i18n)}{data_block('demo-mock', mock_screens(m))}
 </div>
</section>

<section class="section" aria-labelledby="lc-title">
 <div class="wrap">
  <div class="section-head reveal"><h2 id="lc-title">{e(h['lifecycle']['title'])}</h2></div>
  <ol class="lifecycle">{lifecycle}</ol>
 </div>
</section>

<section class="section dark" aria-labelledby="pr-title">
 <div class="wrap">
  <div class="section-head reveal"><h2 id="pr-title">{e(h['principles']['title'])}</h2></div>
  <div class="principles">{principles}</div>
 </div>
</section>

<section class="section" aria-labelledby="gd-title">
 <div class="wrap">
  <div class="section-head reveal"><span class="kicker">{e(u['nav_guides'])}</span><h2 id="gd-title">{e(u['related'])}</h2></div>
  <div class="guides">{guides}</div>
 </div>
</section>

<section class="section alt" aria-labelledby="faq-title">
 <div class="wrap">
  <div class="section-head center reveal"><h2 id="faq-title">{e(u['faq'])}</h2></div>
  <div class="faq">{faq}</div>
 </div>
</section>

<section class="section" id="contact" aria-labelledby="ct-title">
 <div class="wrap contact-grid">
  <div class="reveal"><h2 id="ct-title">{e(h['contact']['title'])}</h2><p class="lead" style="color:var(--ink-2)">{e(h['contact']['text'])}</p>
   <ul class="contact-points">
    <li>{art.icon('mail', '#0f8a85')}<a href="mailto:info@kortexd.com" dir="ltr">info@kortexd.com</a></li>
    <li>{art.icon('globe', '#0f8a85')}<a href="https://kortexd.com/" dir="ltr">kortexd.com</a></li>
    <li>{art.icon('users', '#0f8a85')}<a href="{cfg.app}/login?register=1&amp;lang={lang}">{e(u['register'])}</a></li>
   </ul></div>
  <form class="form-card reveal" id="demo-form" novalidate>
   <h3>{e(F['title'])}</h3>
   <div class="form-grid">
    <label class="field">{e(F['name'])}<input name="name" required maxlength="120" autocomplete="name"></label>
    <label class="field">{e(F['email'])}<input name="email" type="email" required maxlength="254" autocomplete="email" dir="ltr"></label>
    <label class="field">{e(F['organization'])}<input name="organization" maxlength="200" autocomplete="organization"></label>
    <label class="field">{e(F['role'])}<select name="role">{roles}</select></label>
    <label class="field full">{e(F['phone'])}<input name="phone" type="tel" maxlength="40" autocomplete="tel" dir="ltr"></label>
    <label class="field full">{e(F['message'])}<textarea name="message" maxlength="3000"></textarea></label>
    <label class="hp" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
    <label class="consent full"><input type="checkbox" name="consent" required><span>{e(F['consent'])}</span></label>
   </div>
   <div style="margin-top:16px"><button class="btn btn-dark" type="submit">{e(F['submit'])}</button></div>
   <p class="form-msg" role="status"></p>
   {data_block('form-i18n', form_i18n)}
  </form>
 </div>
</section>
</main>
""" + footer(cfg, lang, c)


# ---------------------------------------------------------------- guide pages

def page(cfg, lang: str, c: dict, slug: str) -> str:
    p, u = c["pages"][slug], c["ui"]
    crumbs = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Permit360", "item": url(cfg, lang)},
        {"@type": "ListItem", "position": 2, "name": p["nav"], "item": url(cfg, lang, slug)}]}
    graph = [org_ld(cfg), {"@type": "WebPage", "url": url(cfg, lang, slug), "name": p["title"], "headline": p["h1"], "description": p["description"],
             "inLanguage": lang, "isPartOf": {"@id": f"{cfg.base}/#website"}, "about": {"@id": f"{cfg.base}/#software"},
             "publisher": {"@id": "https://kortexd.com/#organization"}, "dateModified": cfg.today}, crumbs]
    if p.get("faq"):
        graph.append(faq_ld(p["faq"]))
    ld = {"@context": "https://schema.org", "@graph": graph}
    secs, toc = [], []
    for i, s in enumerate(p["sections"], 1):
        sid = f"s{i}"
        toc.append(f'<li><a href="#{sid}">{e(s["h2"])}</a></li>')
        body = "".join(f"<p>{e(x)}</p>" for x in s.get("paragraphs", []))
        if s.get("bullets"):
            body += "<ul>" + "".join(f"<li>{e(b)}</li>" for b in s["bullets"]) + "</ul>"
        secs.append(f'<section id="{sid}"><h2>{e(s["h2"])}</h2>{body}</section>')
    faq = ""
    if p.get("faq"):
        faq = f'<section id="faq"><h2>{e(u["faq"])}</h2><div class="faq" style="margin:0">' + "".join(
            f'<details><summary>{e(x["q"])}</summary><p>{e(x["a"])}</p></details>' for x in p["faq"]) + "</div></section>"
        toc.append(f'<li><a href="#faq">{e(u["faq"])}</a></li>')
    sources = ""
    if p.get("sources"):
        sources = f'<aside class="sources"><h2>{e(u["sources"])}</h2><ul>' + "".join(
            f'<li><a href="{e(s["url"])}" rel="noopener" target="_blank">{e(s["label"])}</a></li>' for s in p["sources"]) + "</ul></aside>"
    i = SLUGS.index(slug)
    rel = [SLUGS[(i + k) % len(SLUGS)] for k in (1, 2, 3)]
    if slug != "committee-lookup" and "committee-lookup" not in rel:
        rel[-1] = "committee-lookup"
    related = "".join(f'<a class="guide" href="/{lang}/{s}/"><b>{e(c["pages"][s]["nav"])}</b><span>{e(c["pages"][s]["description"])}</span>'
                      f'<span class="more">{e(u["read_more"])} <span class="arrow" aria-hidden="true">→</span></span></a>' for s in rel)
    return head(cfg, lang, c, p["title"], p["description"], slug, [ld]) + header(cfg, lang, c, slug) + f"""
<main id="main">
<section class="page-hero">
 <div class="wrap">
  <div>
   <nav class="crumbs" aria-label="breadcrumb"><a href="/{lang}/">Permit360</a><span aria-hidden="true">/</span><span>{e(p['nav'])}</span></nav>
   <h1>{e(p['h1'])}</h1>
   <p class="lead">{e(p['lead'])}</p>
  </div>
  <div class="page-art">{art.page_art(ART[slug])}</div>
 </div>
</section>
<div class="wrap article">
 <article class="prose">{''.join(secs)}{faq}{sources}</article>
 <aside class="toc" aria-label="{e(u['on_this_page'])}"><b>{e(u['on_this_page'])}</b><ol>{''.join(toc)}</ol>
  <a class="btn btn-dark btn-sm" href="/{lang}/#contact">{e(u['request_demo'])}</a>
  <a class="btn btn-outline btn-sm" style="margin-top:8px" href="/{lang}/#lookup-title">{e(c['home']['lookup']['title'])}</a></aside>
</div>
<section class="section alt" aria-labelledby="rel-title" style="padding-block:56px">
 <div class="wrap"><h2 id="rel-title" style="font-size:26px">{e(u['related'])}</h2><div class="related">{related}</div></div>
</section>
<section class="cta-band">
 <div class="wrap">
  <div><h2>{e(c['home']['advantage']['title'])}</h2><p>{e(c['home']['contact']['text'])}</p></div>
  <div class="hero-actions"><a class="btn btn-dark" href="/{lang}/#contact">{e(u['request_demo'])}</a>
   <a class="btn btn-outline" href="{cfg.app}/login?register=1&amp;lang={lang}">{e(u['register'])}</a></div>
 </div>
</section>
</main>
""" + footer(cfg, lang, c)


# ---------------------------------------------------------------- statements (accessibility, privacy)

def legal(cfg, lang: str, c: dict, slug: str) -> str:
    p = c["legal"][slug]
    crumbs = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Permit360", "item": url(cfg, lang)},
        {"@type": "ListItem", "position": 2, "name": p["nav"], "item": url(cfg, lang, slug)}]}
    ld = {"@context": "https://schema.org", "@graph": [org_ld(cfg), {"@type": "WebPage", "url": url(cfg, lang, slug), "name": p["title"],
          "description": p["description"], "inLanguage": lang, "isPartOf": {"@id": f"{cfg.base}/#website"},
          "publisher": {"@id": "https://kortexd.com/#organization"}, "dateModified": cfg.today}, crumbs]}
    secs = []
    for s in p["sections"]:
        body = "".join(f"<p>{mail(e(x))}</p>" for x in s.get("paragraphs", []))
        if s.get("bullets"):
            body += "<ul>" + "".join(f"<li>{e(b)}</li>" for b in s["bullets"]) + "</ul>"
        secs.append(f'<section><h2>{e(s["h2"])}</h2>{body}</section>')
    return head(cfg, lang, c, p["title"], p["description"], slug, [ld]) + header(cfg, lang, c, slug) + f"""
<main id="main">
<section class="page-hero legal-hero">
 <div class="wrap"><div>
  <nav class="crumbs" aria-label="breadcrumb"><a href="/{lang}/">Permit360</a><span aria-hidden="true">/</span><span>{e(p['nav'])}</span></nav>
  <h1>{e(p['h1'])}</h1>
  <p class="lead">{e(p['lead'])}</p>
 </div></div>
</section>
<div class="wrap legal-body"><article class="prose">{''.join(secs)}</article></div>
</main>
""" + footer(cfg, lang, c)


def mail(html: str) -> str:
    return html.replace("info@kortexd.com", '<a href="mailto:info@kortexd.com" dir="ltr">info@kortexd.com</a>')


# ---------------------------------------------------------------- root, 404, sitemap, robots, llms, OG

def root(cfg, contents) -> str:
    cards = "".join(f'<a class="guide" href="/{l}/" hreflang="{l}" lang="{l}" dir="{DIR[l]}"><b>{e(LANG_NAME[l])}</b>'
                    f'<span>{e(contents[l]["meta"]["home_description"])}</span></a>' for l in LANGS)
    alts = "\n".join(f'<link rel="alternate" hreflang="{l}" href="{url(cfg, l)}">' for l in LANGS)
    return f"""<!doctype html>
<html lang="he" dir="rtl" class="no-js" data-api="{e(cfg.api)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Permit360 by Kortex Digital — היתרי בנייה · Building permits · رخص البناء · Разрешения на строительство</title>
<meta name="description" content="{e(contents['he']['meta']['home_description'])}">
<link rel="canonical" href="{cfg.base}/">
{alts}
<link rel="alternate" hreflang="x-default" href="{cfg.base}/">
<link rel="icon" href="/site/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/site/site.css?v={cfg.version}">
</head>
<body>
<main id="main" class="section"><div class="wrap" style="max-width:980px">
<div style="display:flex;justify-content:center;margin-bottom:28px"><span class="brand" style="color:var(--navy-900)">{BRAND_MARK}<span><b style="color:var(--navy-900)">Permit<span style="color:var(--teal-600)">360</span></b><small style="color:var(--muted)">by Kortex Digital</small></span></span></div>
<h1 style="text-align:center;font-size:clamp(26px,3.4vw,38px)">Permit360 — <span lang="he">היתרי בנייה</span> · <span lang="en" dir="ltr">Building permits</span> · <span lang="ar">رخص البناء</span> · <span lang="ru" dir="ltr">Разрешения на строительство</span></h1>
<div class="guides" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-top:28px">{cards}</div>
</div></main>
</body></html>"""


def not_found(cfg, contents) -> str:
    links = " · ".join(f'<a href="/{l}/" lang="{l}">{e(LANG_NAME[l])}</a>' for l in LANGS)
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>404 — Permit360</title><meta name="robots" content="noindex"><link rel="stylesheet" href="/site/site.css?v={cfg.version}"></head>
<body><main class="section"><div class="wrap" style="text-align:center"><h1>404</h1><p>הדף לא נמצא · Page not found · الصفحة غير موجودة · Страница не найдена</p><p>{links}</p></div></main></body></html>"""


def sitemap(cfg) -> str:
    rows = []
    for slug in [None, *SLUGS, *LEGAL]:
        for l in LANGS:
            alts = "".join(f'<xhtml:link rel="alternate" hreflang="{x}" href="{url(cfg, x, slug)}"/>' for x in LANGS)
            alts += f'<xhtml:link rel="alternate" hreflang="x-default" href="{url(cfg, "he", slug)}"/>'
            rows.append(f"<url><loc>{url(cfg, l, slug)}</loc><lastmod>{cfg.today}</lastmod>{alts}</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(rows) + "\n</urlset>\n")


def llms(cfg, contents) -> str:
    out = ["# Permit360 by Kortex Digital", "",
           "> " + contents["en"]["llms_summary"], "",
           f"Public website: {cfg.base}/ · Application (sign-in): {cfg.app}/ · Company: Kortex Digital Ltd, https://kortexd.com/", ""]
    for l in LANGS:
        c = contents[l]
        out += [f"## {LANG_NAME[l]} ({l})", "", c["llms_summary"], "", f"- [{c['meta']['home_title']}]({url(cfg, l)})"]
        out += [f"- [{c['pages'][s]['title']}]({url(cfg, l, s)}): {c['pages'][s]['description']}" for s in SLUGS]
        out.append("")
    out += ["## Notes", "", "- Permit360 does not issue building permits; statutory decisions belong to planning committees.",
            "- Integration with Rishuy Zamin (the national online permit system) is planned, not available.", ""]
    return "\n".join(out)


def og_images(cfg, out: Path, contents):
    """1200×630 share images per language (Pillow + libraqm for Hebrew / Arabic shaping)."""
    from PIL import Image, ImageDraw, ImageFont
    fonts = {"he": "/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf", "ar": "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
             "en": "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "ru": "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"}
    reg = {"he": "/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf", "ar": "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
           "en": "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "ru": "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"}
    import tempfile

    from fontTools import subset
    from fontTools.merge import Merger
    tmp = Path(tempfile.mkdtemp())
    for name, script, lat in (("he-b", fonts["he"], "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
                              ("he-r", reg["he"], "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf")):
        # Noto Sans Hebrew has no Latin punctuation (comma, digits): merge them in from Noto Sans
        o = subset.Options()
        o.layout_features = ["*"]
        a = subset.load_font(script, o)
        sub = subset.Subsetter(o)
        sub.populate(unicodes=list(range(0x0590, 0x0600)) + [0x20])
        sub.subset(a)
        a.save(tmp / "a.ttf")
        b = subset.load_font(lat, o)
        sub = subset.Subsetter(o)
        sub.populate(unicodes=range(0x21, 0x7F))
        sub.subset(b)
        b.save(tmp / "b.ttf")
        Merger().merge([str(tmp / "a.ttf"), str(tmp / "b.ttf")]).save(tmp / f"{name}.ttf")
    fonts["he"], reg["he"] = str(tmp / "he-b.ttf"), str(tmp / "he-r.ttf")
    latin = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", 46)
    small = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", 24)
    (out / "site" / "og").mkdir(parents=True, exist_ok=True)
    for l in LANGS:
        c = contents[l]
        im = Image.new("RGB", (1200, 630), "#071a2b")
        d = ImageDraw.Draw(im)
        for x in range(0, 1200, 40):
            d.line([(x, 0), (x, 630)], fill="#0c2539")
        for y in range(0, 630, 40):
            d.line([(0, y), (1200, y)], fill="#0c2539")
        rtl = DIR[l] == "rtl"
        # parcel motif on the far side from the text
        cx = 230 if rtl else 970
        d.polygon([(cx - 170, 330), (cx, 230), (cx + 170, 330), (cx, 430)], outline="#2d5f70", width=2)
        d.polygon([(cx - 70, 330), (cx, 290), (cx + 70, 330), (cx, 370)], fill="#0f4a50", outline="#5fd6c8", width=3)
        lx = 60 if not rtl else 1200 - 60 - 64
        d.rounded_rectangle([lx, 56, lx + 64, 120], 14, fill="#0f8a85")
        d.polygon([(lx + 14, 98), (lx + 32, 88), (lx + 50, 98), (lx + 32, 108)], fill="#2fa89f", outline="#e8fbf8")
        d.text((lx + 32, 82), "P", font=ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", 40), fill="#ffffff", anchor="mm")
        d.text((60 + 84 if not rtl else 1200 - 60 - 84, 62), "Permit360", font=latin, fill="#ffffff", anchor="la" if not rtl else "ra")
        d.text((60 + 86 if not rtl else 1200 - 60 - 86, 122), "by Kortex Digital", font=small, fill="#9fb7c4", anchor="la" if not rtl else "ra")
        title = c["home"]["h1"] + " " + c["home"]["h1_accent"]
        fb = ImageFont.truetype(fonts[l], 54)
        fr = ImageFont.truetype(reg[l], 28)
        # wrap the title to the text column
        words, lines, cur = title.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=fb, direction="rtl" if rtl else None) > 640 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = t
        lines.append(cur)
        x = 60 if not rtl else 1140
        y = 230
        step = 82 if l == "ar" else 70
        for ln in lines[:4]:
            d.text((x, y), ln, font=fb, fill="#ffffff", anchor="la" if not rtl else "ra", direction="rtl" if rtl else None)
            y += step
        d.text((x, y + 26), "permit360.kortexd.com", font=small, fill="#5fd6c8", anchor="la" if not rtl else "ra")
        im.save(out / "site" / "og" / f"og-{l}.png", optimize=True)


def minify_css(css: str) -> str:
    """Comments and whitespace out (no rewriting of values)."""
    import re
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{};,>])\s*", r"\1", css)
    return css.replace(";}", "}").strip()


FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36"><rect width="36" height="36" rx="9" fill="#0f8a85"/>'
           '<path d="M8 22 18 16l10 6-10 6z" fill="#5fd6c8" fill-opacity=".35" stroke="#e8fbf8" stroke-width="1.4" stroke-linejoin="round"/>'
           '<path d="M13 21V11h6.5a4 4 0 0 1 0 8H13" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://permit360.kortexd.com")
    ap.add_argument("--api", default="", help="API origin for the lookup and the form ('' = same origin)")
    ap.add_argument("--app", default="", help="application origin for sign-in links ('' = same host)")
    ap.add_argument("--out", default=str(HERE / "dist"))
    cfg = ap.parse_args()
    cfg.base = cfg.base.rstrip("/")
    cfg.today = date.today().isoformat()
    cfg.version = cfg.today.replace("-", "")
    out = Path(cfg.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "site").mkdir(parents=True)
    contents = {l: json.load(open(HERE / "content" / f"{l}.json", encoding="utf-8")) for l in LANGS}
    for l in LANGS:
        (out / l).mkdir()
        (out / l / "index.html").write_text(home(cfg, l, contents[l]), encoding="utf-8")
        for s in SLUGS:
            (out / l / s).mkdir()
            (out / l / s / "index.html").write_text(page(cfg, l, contents[l], s), encoding="utf-8")
        for s in LEGAL:
            (out / l / s).mkdir()
            (out / l / s / "index.html").write_text(legal(cfg, l, contents[l], s), encoding="utf-8")
    (out / "site" / "404.html").write_text(not_found(cfg, contents), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(cfg), encoding="utf-8")
    app_paths = ["/api/", "/llm-relay/", "/login", "/apply", "/cases", "/projects", "/architect", "/rules", "/sources", "/committees",
                 "/knowledge", "/users", "/audit", "/tasks", "/authorities", "/learning", "/ai", "/integrations"]
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\n" + "".join(f"Disallow: {p}\n" for p in app_paths)
                                    + f"\nSitemap: {cfg.base}/sitemap.xml\n", encoding="utf-8")
    (out / "llms.txt").write_text(llms(cfg, contents), encoding="utf-8")
    (out / "site" / "site.css").write_text(minify_css((HERE / "assets" / "site.css").read_text(encoding="utf-8").replace("/assets/fonts/", "/site/fonts/")),
                                          encoding="utf-8")
    shutil.copy(HERE / "assets" / "site.js", out / "site" / "site.js")
    shutil.copytree(HERE / "assets" / "fonts", out / "site" / "fonts")
    (out / "site" / "favicon.svg").write_text(FAVICON, encoding="utf-8")
    og_images(cfg, out, contents)
    n = sum(1 for _ in out.rglob("*.html"))
    print(f"built {n} pages into {out}")


if __name__ == "__main__":
    main()
