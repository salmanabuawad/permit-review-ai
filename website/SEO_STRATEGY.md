# Permit360 — multilingual SEO and AI-discovery strategy

## Structure

| | Hebrew | Arabic | English | Russian |
|---|---|---|---|---|
| Home | `/he/` | `/ar/` | `/en/` | `/ru/` |
| Guides (9 each) | `/he/<slug>/` | `/ar/<slug>/` | `/en/<slug>/` | `/ru/<slug>/` |

Root `/` is a language chooser and the `x-default`. Every page has its own canonical URL, reciprocal `hreflang`
links to its three counterparts plus `x-default`, localized `<title>`, meta description, Open Graph tags and
a language-specific share image (`/assets/og/og-<lang>.png`). `sitemap.xml` lists all 41 URLs with the same
alternates; `robots.txt` allows everything except `/api/`.

## Search intent per page

| Slug | Intent | Hebrew focus | Arabic focus | English focus | Russian focus |
|---|---|---|---|---|---|
| (home) | product | מערכת להכנה ובדיקה של בקשות להיתר בנייה | منظومة لإعداد وفحص طلبات رخص البناء | building permit software Israel | разрешение на строительство в Израиле |
| building-permit-preparation | how-to | הכנת בקשה להיתר בנייה | إعداد طلب ترخيص بناء | building permit preparation | подготовка заявления на разрешение |
| building-permit-review | B2G | בדיקת בקשות להיתר / מערכת לבודקי היתרים | فحص طلبات الترخيص | automated plan review | проверка строительных планов |
| engineers-architects | audience | למהנדסים ואדריכלים | للمهندسين والمعماريين | engineers and architects | инженерам и архитекторам |
| planning-committees | audience | ועדה מקומית לתכנון ובנייה | لجان التخطيط والبناء | planning committees Israel | комиссии по планированию и строительству |
| building-rights | informational | בדיקת זכויות בנייה / תב״ע | حقوق البناء | building rights Israel | права застройки |
| committee-lookup | tool | איתור ועדה לפי גוש וחלקה | تحديد اللجنة حسب الحوض والقسيمة | gush helka committee lookup | комиссия по гушу и хельке |
| planning-regulations | informational | תקנות התכנון והבנייה (רישוי בנייה) | أنظمة التخطيط والبناء | Israeli planning regulations | нормативы планирования Израиля |
| cad-gis | technical | בדיקת שרטוטים DWG / GIS | تحليل المخططات CAD وGIS | CAD and GIS plan analysis | анализ чертежей CAD и ГИС |
| local-ai-security | trust | בינה מלאכותית מקומית ואבטחת מידע | الذكاء الاصطناعي المحلي وأمن المعلومات | local AI, data security | локальный ИИ и безопасность |

Each language was written originally from the same verified fact sheet (`content/FACTS.md`), for its own
audience: Hebrew for Israeli practitioners and committee staff; Arabic for engineers, architects and committees
in Arab localities (explaining local vs regional committees and Arabic terms such as الحوض والقسيمة); English for
international developers, investors and GovTech readers (Israeli terms explained); Russian for Russian-speaking
engineers and architects, with the Hebrew terms they meet in practice (гуш/хелька, ТАБА, ваада).

## Trust and AI discovery

- Structured data: `Organization` (Kortex Digital Ltd), `WebSite`, `SoftwareApplication` (Permit360), `WebPage`,
  `BreadcrumbList` and `FAQPage` (home and every guide) — all generated from the visible content.
- `llms.txt`: a factual summary per language with links to every page, and the two key limits (Permit360 does
  not issue permits; Rishuy Zamin integration is planned).
- Every product claim comes from `content/FACTS.md`, verified against the code. Official sources are linked
  (Planning Administration licensing pages, Mavat). No testimonials, customer counts, accuracy or time-saving
  numbers, no hidden text, no keyword lists.
- The home page offers a real, useful tool — committee lookup by block and parcel on official data — which
  gives search engines and people a reason to link.

## Next steps (content)

1. Approved product screenshots (no case data) for the guide pages — the current illustrations are drawn.
2. A short, sourced glossary page per language (גוש/חלקה, תב״ע, הקלה, היתר, ועדה מקומית/מרחבית).
3. One article per month answering a real practitioner question (e.g. "which committee handles my parcel when
   it crosses two planning areas"), written per language.
4. After launch: Search Console per language (queries, CTR), fix pages with impressions but low clicks.
