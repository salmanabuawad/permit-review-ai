"""Parser for municipal planning-committee protocols (Complot export format).

A protocol holds front matter, plan discussions (TBPIRUT… blocks — NOT permit applications) and
permit-application items (BAKPIRUT… blocks). Each application item has a fixed set of labelled
sections (request number, building file, type, address, block/parcel, zone, plans, description,
areas, deviations, objections, departmental comments, decision). Labels are matched on their
letters (tolerant of bidi damage); values are the text up to the next label. Nothing is invented:
a section that is not found stays empty.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import text as T
from .schemas import (ApplicationExtraction, AreaItem, Comment, Decision, Extracted,
                      PlanningItem, SourceRef)

APP_MARK = re.compile(r"BAKPIRUT\d+")
PLAN_MARK = re.compile(r"TBPIRUT\d+")
NOT_HEB_BEFORE = r"(?<![֐-׿])"

# (key, aliases, colon_required) — searched in this order through the item header
HEADER = [
    ("application_number", ["מספר בקשה"], False),
    ("building_file", ["תיק בניין", "תיק ןי בני"], False),
    ("meeting_number", ["ישיבה מספר"], False),
    ("meeting_date", ["בתאריך"], False),
    ("applicant", ["מבקש"], True),                  # boundary only — never extracted (personal data)
    ("editor", ["עורך"], True),                     # boundary only
    ("checker", ["בודק אחראי", "בודק"], False),     # boundary only
    ("application_type", ["סוג בקשה", "וג ס בקשה"], False),
    ("address", ["כתובת הבניין"], False),
    ("plot_area", ["שטח מגרש"], False),
    ("gush_helka", ["גוש וחלקה"], False),
    ("zone", ["יעוד", "ייעוד"], True),
    ("plans", ["תכנית", "תוכנית"], True),
    ("description", ["מהות ופרוט הבקשה", "מהות ופירוט הבקשה", "מהות הבקשה"], False),
]
BODY = [
    ("areas", ["שטחים"], True),
    ("deviations", ["ראה פרסום בהקלות הבאות", "פרסום בהקלות", "פרסום הקלות"], False),
    ("objections", ["התנגדויות"], True),
]
DEPARTMENTS = [
    ("licensing_department", "מחלקת רישוי", ["מחלקת רישוי", "מחלקת רשוי", "מח רישוי", "מח רשוי", "מחלק רישוי"]),
    ("city_appearance_architect", "אדריכל חזות העיר", ["אדריכל חזות העיר", "אדר חזות העיר", "אד חזות העיר"]),
    ("city_engineer", "מהנדס העיר", ["מהנדס העיר"]),
    ("licensing_architect", "אדריכל רישוי", ["אדריכל רישוי", "אדר רישוי", "אדר רשוי", "אד רישוי", "אד רשוי"]),
    ("planning_department", 'מחלקת תב"ע', ["מחלקת תבע", "מח תבע"]),
    ("legal_advisor", "היועץ המשפטי", ["היועץ המשפטי", "היועמש", "יועמש"]),
    ("fire_authority", "רשות הכבאות", ["רשות הכבאות", "כבאות"]),
    ("traffic", "תנועה וחניה", ["אגף התנועה", "תנועה וחניה"]),
]
DECISION_VERBS = (r"לאשר|לחדש|לקבל|לדחות|לשוב|לסרב|לבטל|לא\s*לאשר|הבקשה\s*הובאה|א\s*\.\.?\s*לדחות|"
                  r"הועדה\s*חזרה|חזרה\s*הועדה|הועדה\s*מחליטה|הוחלט")
NOT_DECISION_AFTER = re.compile(r"^[\s.:,]*(?:זו|זאת|כוחה|יפה)")
ADDRESS_CITY = re.compile(r"\s*" + T.tol("בני ברק") + r"\s*$")


@dataclass
class Hit:
    key: str
    a: int
    b: int
    extra: str | None = None


def _find(text: str, aliases: list[str], start: int = 0, colon: bool = False) -> tuple[int, int] | None:
    best = None
    for alias in aliases:
        pat = NOT_HEB_BEFORE + T.tol(alias) + (r"\s*:" if colon else "")
        m = re.compile(pat).search(text, start)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.end())
    return best


def split_items(pages_raw: list[str]) -> tuple[list[tuple[str, list[int]]], list[int]]:
    """-> ([("application"|"planning", [page_no...])], front_matter_pages). Pages are 1-based."""
    items: list[tuple[str, list[int]]] = []
    front: list[int] = []
    for i, raw in enumerate(pages_raw, 1):
        if APP_MARK.search(raw):
            items.append(("application", [i]))
        elif PLAN_MARK.search(raw):
            items.append(("planning", [i]))
        elif items:
            items[-1][1].append(i)
        else:
            front.append(i)
    if not items and any(_find(p, ["מספר בקשה"]) for p in pages_raw):
        items = [("application", list(range(1, len(pages_raw) + 1)))]
        front = []
    return items, front


# ------------------------------------------------------------------ value parsers

def _src(file: str, sha: str | None, flat: T.Flat, a: int, b: int, method: str, conf: float,
         page_map: dict[int, int] | None = None) -> SourceRef:
    p = flat.page_at(a)
    return SourceRef(file=file, file_sha256=sha, page=p, original_page=(page_map or {}).get(p),
                     quote=T.quote(flat, a, b), method=method, confidence=conf)


def _iso(d: str) -> str | None:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", d)
    if not m:
        return None
    dd, mm, yy = (int(x) for x in m.groups())
    yy = yy + 2000 if yy < 100 else yy
    return f"{yy:04d}-{mm:02d}-{dd:02d}"


PERMIT_RULES = [   # on compact (letters-only) description text; first match is the primary category
    ("new_building", r"הריסת.{0,80}ובניית|בניית(?:בניין|בית|מבנה|חניון)|בניינחדש|ביתמגוריםחדש|בנייהחדשה|בניהחדשה"),
    ("parcel_unification", r"איחודחלקות|איחודוחלוקת|חלוקתחלקות"),
    ("permit_changes", r"שינוייםלתו?כניתהיתר|תו?כניתשינויים"),
    ("roof_room_addition", r"חדריגג|חדרגג|חדריםבגג|חדרייציאהלגג|דירתגג"),
    ("addition_sukkah", r"סוכ"),
    ("addition_balcony", r"מרפס"),
    ("addition_extension", r"תוספת|הרחבת|הרחבה|אגף|ממד|מיגון|שטחעיקרי"),
]
PERMIT_HE = {"new_building": "בנייה חדשה", "parcel_unification": "איחוד חלקות", "permit_changes": "שינויים להיתר",
             "roof_room_addition": "חדרי גג", "addition_sukkah": "סוכה", "addition_balcony": "מרפסת",
             "addition_extension": "תוספת בנייה"}
PROCEDURES = [
    ("renewal", "חידוש אישור", r"חידושאישור|לחדשאישור|חידושהיתר"),
    ("rediscussion", "דיון חוזר", r"דיוןחוזר"),
    ("appeal_followup", "בעקבות ועדת ערר", r"ו?ועדתערר"),
    ("permit_changes", "שינויים להיתר קיים", r"שינוייםלתו?כניתהיתר"),
    ("applicant_change", "שינוי שם המבקש", r"שינוישםהמבקש"),
]


def infer_permit_type(description: str) -> tuple[str | None, list[str]]:
    c = T.compact(description)
    found = [k for k, pat in PERMIT_RULES if re.search(pat, c)]
    return (found[0] if found else None), found


def procedures(*texts: str) -> list[str]:
    c = T.compact(" ".join(t for t in texts if t))
    return [he for _, he, pat in PROCEDURES if re.search(pat, c)]


def classify_decision(text: str) -> str:
    c = T.compact(text)
    order = [("objection_partially_accepted", r"לקבלה?התנגדו"), ("renewed", r"לחדשאישור|לחדשאת"),
             ("deferred", r"לדחותדיון|לדחותאתהדיון|לשובולדון|להוריד"), ("objection_rejected", r"לדחותההתנגדו"),
             ("rejected", r"לאלאשר|לסרב|לדחותאתהבקשה|לדחותהבקשה"), ("approved", r"לאשר")]
    hits = [(m.start(), k) for k, pat in order for m in [re.search(pat, c)] if m]
    if not hits:
        return "other"
    k = min(hits)[1]
    if k == "approved" and re.search(r"בהערות|בתנאים|בכפוף|ובתאום", c):
        return "approved_with_conditions"
    return k


def split_numbered(seg: str) -> list[tuple[str | None, str]]:
    """'intro 9. a 10 . b' -> [(None,'intro'), ('9','a'), ('10','b')]."""
    parts = re.split(r"(?:(?<=\s)|^)(\d{1,2})\s*\.{1,2}(?=\s)", " " + seg)
    out = []
    head = T.tidy(parts[0])
    if head and len(head) > 2:
        out.append((None, head))
    for i in range(1, len(parts) - 1, 2):
        t = re.sub(r"^[.\s]+", "", T.tidy(parts[i + 1]))
        if t:
            out.append((parts[i], t))
    return out


AREA_NUM = re.compile(r"(\d{1,6}(?:\.\d{1,3})?)")
FLOOR = re.compile(r"(קומ[הת]\s*[^\s:]{1,6}'?|קומת\s*הגג|קומת\s*גג|קומת\s*קרקע|קומת\s*מרתף)")
STATUS = re.compile(r"(קיים|מוצע)")


def parse_areas(seg: str) -> list[tuple[str | None, str | None, str, float]]:
    """Best-effort: [(floor, status, label, m2)] from the 'שטחים' section."""
    out = []
    chunks = [(m.start(), m.group(1)) for m in FLOOR.finditer(seg)]
    if not chunks:
        chunks = [(0, None)]
    bounds = [c[0] for c in chunks] + [len(seg)]
    for (start, floor), end in zip(chunks, bounds[1:]):
        chunk = seg[start:end]
        status_pos = [(m.start(), "existing" if m.group(1) == "קיים" else "proposed") for m in STATUS.finditer(chunk)]
        prev_end = len(floor) if floor else 0
        for m in AREA_NUM.finditer(chunk):
            if m.start() < prev_end:
                continue
            num = m.group(1)
            before, after = chunk[max(0, m.start() - 9):m.start()], chunk[m.end():m.end() + 9]
            if before[-1:] in "/%" or after[:1] in "/%" or re.fullmatch(r"(?:19|20)\d\d", num):
                continue                                   # dates, percentages, years
            if "." not in num and not re.search(r"מ\s*[\"״.]\s*\.?\s*ר", before + " " + after):
                continue                                   # a bare integer without a m² unit is not an area
            val = float(num)
            st = None
            for p, s in status_pos:
                if p < m.start():
                    st = s
            label = chunk[prev_end:m.start()]
            label = re.sub(r"(קיים|מוצע|מ\s*[\"״.]\s*\.?\s*ר(?![֐-׿])|\+|-|–|:|\.|,|')", " ", label)
            label = re.sub(r"\s+", " ", label).strip()
            label = label or "שטח"
            prev_end = m.end()
            if re.match(r"\s*\.?\s*יח", chunk[m.end():]):      # "3 .יח\"ד" is a unit count, not an area
                continue
            if 0 < val < 100000:
                out.append((T.tidy(floor) if floor else None, st, label[:40], val))
    return out


# ------------------------------------------------------------------ application item

def parse_application(pages: list[tuple[int, str]], file: str, sha: str | None,
                      page_map: dict[int, int] | None = None) -> ApplicationExtraction:
    flat = T.flatten(pages)
    t = flat.text
    res = ApplicationExtraction(pages=[p for p, _ in pages])
    S = lambda a, b, method, conf: _src(file, sha, flat, a, b, method, conf, page_map)  # noqa: E731

    m = re.search(NOT_HEB_BEFORE + T.tol("סעיף") + r"\s*(\d{1,3})", t)
    if m:
        res.item_number = m.group(1)

    hits: list[Hit] = []
    pos = 0
    for key, aliases, colon in HEADER:
        f = _find(t, aliases, pos, colon)
        if f:
            hits.append(Hit(key, *f))
            pos = f[1]
    desc_hit = next((h for h in hits if h.key == "description"), None)
    body_start = desc_hit.b if desc_hit else pos

    # decision label: standalone "החלטה" (letters may be split, e.g. "החלט ה"), not "החלטה זו / כוחה יפה".
    # Prefer the first one followed by a decision verb; otherwise the last one in the item.
    dec = None
    cands = []
    for m in re.finditer(NOT_HEB_BEFORE + T.tol("החלטה") + r"(?![֐-׿])", t, ):
        if m.start() < body_start or NOT_DECISION_AFTER.match(t[m.end():m.end() + 12]):
            continue
        cands.append(m)
    with_verb = [m for m in cands if re.search(DECISION_VERBS, t[m.end():m.end() + 160])]
    pick = with_verb[0] if with_verb else (cands[-1] if cands else None)
    if pick:
        dec = Hit("decision", pick.start(), pick.end())
    body_end = dec.a if dec else len(t)
    for key, aliases, colon in BODY:
        f = _find(t[:body_end], aliases, body_start, colon)
        if f:
            hits.append(Hit(key, *f))
    for key, he, aliases in DEPARTMENTS:
        for alias in aliases:
            pat = re.compile(NOT_HEB_BEFORE + T.tol("הערות") + T.SEP + T.tol(alias))
            for mm in pat.finditer(t[:body_end], body_start):
                if not any(h.a <= mm.start() < h.b for h in hits):
                    hits.append(Hit("comments", mm.start(), mm.end(), key))
    if dec:
        hits.append(dec)
    hits.sort(key=lambda h: h.a)
    seg = {}
    for i, h in enumerate(hits):
        end = hits[i + 1].a if i + 1 < len(hits) else len(t)
        seg.setdefault((h.key, h.extra, h.a), (h.b, end))

    def first(key):
        for (k, _, _), v in seg.items():
            if k == key:
                return v
        return None

    def put(field, value, a, b, method, conf):
        if value not in (None, "", []):
            setattr(res, field, Extracted(value=value, source=S(a, b, method, conf)))

    if (r := first("application_number")) and (m := re.search(r"\d{4,12}", t[r[0]:r[1]])):
        put("application_number", m.group(0), r[0] + m.start(), r[0] + m.end(), "תווית 'מספר בקשה'", 0.95)
    if (r := first("building_file")) and (m := re.search(r"\d{5,12}", t[r[0]:r[1]])):
        put("building_file_number", m.group(0), r[0] + m.start(), r[0] + m.end(), "תווית 'תיק בניין'", 0.9)
    if (r := first("meeting_number")) and (m := re.search(r"\d{6,10}", t[r[0]:r[1]])):
        res.meeting_number = m.group(0)
    if (r := first("meeting_date")) and (m := re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", t[r[0]:r[1]])):
        res.meeting_date = _iso(m.group(0))
    if r := first("application_type"):
        put("application_type", T.tidy(t[r[0]:r[1]]), *r, "תווית 'סוג בקשה'", 0.9)
    if r := first("address"):
        addr = T.split_letters_digits(T.tidy(t[r[0]:r[1]]))
        addr = ADDRESS_CITY.sub("", addr)
        put("address", addr, *r, "תווית 'כתובת הבניין'", 0.85)
    if (r := first("plot_area")) and (m := re.search(r"\d{2,6}(?:\.\d{1,2})?", t[r[0]:r[1]])):
        res.plot_area_m2 = Extracted(value=float(m.group(0)), source=S(r[0] + m.start(), r[0] + m.end(), "תווית 'שטח מגרש'", 0.85))
    if r := first("gush_helka"):
        g = re.search(r"גוש\s*:?\s*(\d{3,6})", t[r[0]:r[1]])
        h = re.search(r"חלקה\s*:?\s*(\d{1,5})", t[r[0]:r[1]])
        if g:
            put("gush", g.group(1), r[0] + g.start(), r[0] + g.end(), "תווית 'גוש'", 0.95)
        if h:
            put("helka", h.group(1), r[0] + h.start(), r[0] + h.end(), "תווית 'חלקה'", 0.95)
    if r := first("zone"):
        put("zone", T.tidy(t[r[0]:r[1]]), *r, "תווית 'יעוד'", 0.85)
    if r := first("plans"):
        raw = T.tidy(t[r[0]:r[1]])
        put("applicable_plans", raw, *r, "תווית 'תכנית' — נוסח גולמי, סדר הסימנים עלול להשתבש בייצוא", 0.5)
    if r := first("description"):
        desc = T.tidy(t[r[0]:r[1]])
        put("description", desc, *r, "תווית 'מהות ופרוט הבקשה'", 0.8)
        ptype, found = infer_permit_type(desc)
        if ptype:
            res.permit_type = Extracted(value=ptype, source=S(*r, "סיווג לפי מילות מפתח במהות הבקשה"
                                                             + (f" (נמצאו גם: {', '.join(PERMIT_HE[x] for x in found[1:])})" if len(found) > 1 else ""), 0.7))
    if r := first("deviations"):
        put("deviations", T.tidy(t[r[0]:r[1]]), *r, "סעיף 'פרסום הקלות'", 0.75)
    area_src = first("areas")
    area_method = "סעיף 'שטחים' — פענוח מבני, נדרש אימות"
    if area_src is None and (d := first("description")) and re.search(r"קיים|מוצע", t[d[0]:d[1]])             and re.search(r"קומ[הת]", t[d[0]:d[1]]):
        area_src, area_method = d, "שטחים מתוך מהות הבקשה (אין סעיף 'שטחים') — נדרש אימות"
    if area_src:
        for floor, status, label, val in parse_areas(t[area_src[0]:area_src[1]]):
            res.areas.append(AreaItem(floor=floor, status=status, label=label, value_m2=val,
                                      source=S(*area_src, area_method, 0.6 if area_src == first("areas") else 0.5)))

    for (k, dept, a), (sa, sb) in sorted(seg.items(), key=lambda kv: kv[0][2]):
        if k != "comments":
            continue
        he = next(h for key, h, _ in DEPARTMENTS if key == dept)
        for no, txt in split_numbered(t[sa:sb]):
            try:
                res.comments.append(Comment(department=dept, department_he=he, item_no=no, text=txt,
                                            source=S(sa, sb, f"סעיף 'הערות {he}'", 0.85)))
            except ValueError:
                pass

    if dec:
        sa, sb = dec.b, len(t)
        dtext = T.tidy(t[sa:sb])
        outcome = classify_decision(dtext)
        conds = [x for no, x in split_numbered(dtext) if no]
        res.decision = Decision(outcome=outcome, text=dtext, conditions=conds, meeting_number=res.meeting_number,
                                meeting_date=res.meeting_date, item_number=res.item_number,
                                source=S(sa, sb, "סעיף 'החלטה'", 0.85 if outcome != "other" else 0.5))
    else:
        res.warnings.append("לא נמצאה החלטת ועדה בפריט")
    res.procedure = procedures(res.description.value if res.description else "",
                               res.decision.text if res.decision else "")
    if not res.application_number:
        res.warnings.append("לא נמצא מספר בקשה בפריט")
    return res


def parse_planning(pages: list[tuple[int, str]]) -> PlanningItem:
    flat = T.flatten(pages)
    t = flat.text
    item = PlanningItem(pages=[p for p, _ in pages])
    m = re.search(NOT_HEB_BEFORE + T.tol("סעיף") + r"\s*(\d{1,3})", t)
    item.item_number = m.group(1) if m else None
    m = re.search(r"\d{3}-\d{7}|בב/[֐-׿/\d']+", t)
    item.plan_number = m.group(0) if m else None
    m = re.search(r"שם\s*:\s*(.{3,120}?)\s*(?:שטח|סמכות|מטרת|$)", t)
    item.title = T.tidy(m.group(1)) if m else None
    m = re.search(NOT_HEB_BEFORE + r"החלטה\s*:?\s*(.{2,300})", t)
    item.decision_text = T.tidy(m.group(1)) if m else None
    return item
