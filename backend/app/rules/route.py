"""Licensing Route Validation Engine.

A request can meet the aggregate rights (total main / service area) and still break a floor-specific or a basement
limit; and a request filed in the regular route (no reliefs) must have no deviation from the plan at all. This engine
validates, per application:

1. the plans that apply on the submission date (knowledge/rights/*.yaml, effective_from / effective_to);
2. floor-specific rights and basement limits of those plans, including transfers the plan allows;
3. the proposed floors — from measured drawings or a declared per-floor table; without them the floor checks are
   NOT_CHECKED, never assumed;
4. each deviation classified by the deviation regulations (knowledge/law/deviation_regulations_2002.yaml): within the
   plan / relief needed (הקלה) / a substantial deviation (סטייה ניכרת — cannot be approved by relief) / a deviation that
   the encoded law does not settle;
5. the route the application needs against the route it was filed in.

Strict evidence policy: a CONFIRMED result needs the inputs it rests on (drawings or a declared per-floor table) and a
plan in force on the submission date. A "prohibited" classification is confirmed only when the deviation regulations
are verified for that date (their consolidated text covers it). Committee decisions are never an input.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import settings

ROUTES_HE = {"REGULAR": "רישוי רגיל (ללא הקלות)", "RELIEF": "בקשה כולל הקלות", "SHORT": "רישוי מקוצר"}
REGISTER_ROUTE = {"81": "REGULAR", "82": "RELIEF", "83": "SHORT"}      # committee register: application type code
STATUS_ORDER = ("WITHIN", "NOT_CHECKED", "POSSIBLE_DEVIATION", "RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED")
# a contradiction between the applicant's own fields (e.g. net vs gross area): needs clarification, never a deviation
DOCUMENT_STATUSES = ("DOCUMENT_DISCREPANCY",)
# the request adds to / regularises an existing building: the register's areas may be only the addition
ADDITION = re.compile(r"תוספת|הרחבת|בדיעבד|הסדרת|תכנית שינויים|גרמושקת שינויים|קיים בהיתר")
MAIN_USES = re.compile(r"מגורים|חדר שינה|סלון|חדר עבודה|משרד|מטבח|יחידת דיור")


@dataclass
class Floor:
    name: str                                   # as drawn / declared: "מרתף", "קומת קרקע", "קומה א" ...
    main_m2: float = 0.0
    service_m2: float = 0.0
    below_entrance: bool = False                # below the entrance (±0.00) level
    ceiling_above_ground_m: float | None = None  # for the regulation's basement definition
    service_used_as_main_m2: float = 0.0        # area counted as service but drawn with a main use
    source: str = ""                            # "drawings" | "declared table"


@dataclass
class Setback:
    side: str                                   # front | side | rear
    plan_m: float
    proposed_m: float
    element: str = "wall"                       # wall | balcony
    openings: bool | None = None
    height_m: float | None = None               # balcony height above final ground


@dataclass
class Proposal:
    application_id: str
    submission_date: dt.date
    plans: list[str]
    land_use: str | None = None
    lot_area_m2: float | None = None
    selected_route: str | None = None           # REGULAR | RELIEF | SHORT
    route_source: str = ""
    total_main_m2: float | None = None
    total_service_m2: float | None = None
    floors: list[Floor] | None = None           # None: no per-floor data (drawings not available)
    floors_source: str = ""
    setbacks: list[Setback] = field(default_factory=list)
    request_text: str = ""
    zero_level_change_m: float | None = None    # proposed ±0.00 minus the building plan's, when known
    # short track (רישוי מקוצר): the work item filed and its own size limit, as worded in the form's item list
    short_item: str | None = None
    short_item_limit_m2: float | None = None
    short_item_limit_source: str = ""
    declared_addition_m2: float | None = None   # the form's "addition area" field
    gross_added_m2: float | None = None         # new construction (gross), from drawings or the applicant's description
    gross_added_source: str = ""                # "drawings" | "applicant description"
    cancelled_unbuilt_m2: float | None = None   # approved earlier but never built, removed by this request
    lot: str | None = None                      # the lot number, to pick the plan's zone
    main_use: str | None = None                 # the register's main use (residential rights do not apply to a barn)
    # "total": the declared areas are the whole building; "addition": they may be only what this request adds
    areas_scope: str = "total"


@dataclass
class Check:
    topic: str
    topic_he: str
    status: str                                 # one of STATUS_ORDER
    explanation_he: str
    measured: float | None = None
    limit: float | None = None
    unit: str = "מ\"ר"
    reg: str | None = None
    source_id: str | None = None
    needs: list[str] = field(default_factory=list)   # what is missing to decide
    confirmable: bool = False                   # rests on drawings / a declared table and a plan in force


@dataclass
class RouteResult:
    application_id: str
    selected_route: str | None
    route_needed: str                           # REGULAR | NOT_REGULAR | PROHIBITED | UNKNOWN
    verdict: str                                # ROUTE_OK | WRONG_ROUTE | PROHIBITED_DEVIATION | INSUFFICIENT_EVIDENCE | NO_RIGHTS
    confirmed: bool
    checks: list[Check]
    law_notes: list[str]
    rights_source: str | None = None

    def as_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


# ------------------------------------------------------------------ knowledge

def _date(s) -> dt.date | None:
    if not s:
        return None
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(str(s))


HALF_LOT = re.compile(r"\s*(\d+)\s*[א-ת]['׳]?\s*")      # "653 ב'", "615א": one unit's part of a two-unit lot


def _lot_in(lot: str | None, ranges: list) -> bool:
    if lot is None:
        return False
    m = re.fullmatch(r"\s*(\d+)\s*", str(lot)) or HALF_LOT.fullmatch(str(lot))
    if not m:
        return False                              # "246 B" or unknown: never guessed into a range
    n = int(m.group(1))
    for rg in ranges:
        a, _, b = str(rg).partition("-")
        if int(a) <= n <= int(b or a):
            return True
    return False


def _select(r: dict, lot: str | None, use: str | None, land_use: str | None, lot_area: float | None,
            on: dt.date | None = None, folder: Path | None = None) -> tuple[dict | None, str]:
    """The rights that apply to this lot and use inside a plan file: by-reference plans, use limits, zones by lot range
    or land use, and rights given as a percentage of the lot area."""
    plan = r["plan"]
    if r.get("rights_by_reference"):
        return None, f"תכנית {plan} אינה קובעת זכויות בנייה בעצמה — הזכויות לפי {r['rights_by_reference']}, שאינה במאגר הידע"
    uses = r.get("applies_to_uses")
    if uses and use and not any(u in use for u in uses):
        return None, f"בקובץ הזכויות של תכנית {plan} אין זכויות לשימוש \"{use}\""
    zones = r.get("zones")
    if not zones:
        return r, ""
    zone = next((z for z in zones if z.get("lots") and _lot_in(lot, z["lots"])), None)
    if zone is None and land_use:
        zone = next((z for z in zones if any(u in land_use or land_use in u for u in z.get("land_use", []))), None)
    if zone is None and use:                      # the plan's only zone for this use (e.g. every residential lot it
        zone = next((z for z in zones if z.get("default_for_use") and z["default_for_use"] in use), None)   # defines)
    if zone is None:
        why = f"המגרש {lot} אינו באף אזור שזכויותיו במאגר" if lot and any(z.get("lots") for z in zones) \
            else "האזור שבו נמצא המגרש אינו ידוע (נדרש תשריט התכנית או נתוני GIS)"
        return None, f"תכנית {plan}: {why}"
    if zone.get("rights_by_reference"):
        return None, f"תכנית {plan}, {zone['name']}: הזכויות לפי {zone['rights_by_reference']}, שאינה במאגר הידע"
    ref = zone.get("rights_from")
    if ref:                                       # the plan defers to another plan's zone (e.g. the outline plan)
        got, note = load_rights([ref["plan"]], ref["zone"], on, folder, use=use)
        if got is None:
            return None, f"תכנית {plan}, {zone['name']}: הזכויות לפי {ref['plan']} — {note}"
        return {**got, "zone": f"{zone['name']} → {got.get('zone', '')}", "via_plan": plan}, \
            f"{zone['name']}; הזכויות לפי {ref['plan']} ({got.get('zone', '')})"
    merged = {**r, **{k: v for k, v in zone.items() if k not in ("lots", "name")}, "zone": zone["name"]}
    if lot and HALF_LOT.fullmatch(str(lot)) and (zone.get("units_max") or 1) > 1:
        merged["part_of_lot"] = str(lot).strip()  # rights are per lot; this request is one unit's part of it
    over = next((o for o in zone.get("main_overrides") or [] if _lot_in(lot, o["lots"])), None)
    if over:                                      # the plan sets the main area lot by lot
        merged["rights"] = {**merged.get("rights", {}), "main_m2": over["main_m2"]}
    pct = zone.get("rights_pct")
    if pct:
        if lot_area is None:
            return None, f"תכנית {plan}, {zone['name']}: הזכויות באחוזים משטח המגרש, ושטח המגרש אינו ידוע"
        merged["rights"] = {**(zone.get("rights") or {}), **{k[:-4] + "_m2": round(v * lot_area / 100, 2)
                                                              for k, v in pct.items() if k.endswith("_pct")}}
    return merged, f"{zone['name']}"


def building_provisions(p: "Proposal", zone: str | None = None, folder: Path | None = None) -> tuple[dict | None, str]:
    """Building provisions (not rights) that apply to the lot on the submission date — e.g. a council-wide plan that
    changes the residential lots of listed plans. (provisions, note)"""
    folder = folder or Path(settings.knowledge_dir, "building_provisions")
    norm = lambda s: re.sub(r"[\s\"״׳']", "", s or "")
    if not folder.exists() or not p.main_use or "מגורים" not in p.main_use:
        return None, ""
    for path in sorted(folder.glob("*.yaml")):
        b = yaml.safe_load(path.read_text(encoding="utf-8"))
        frm = _date(b.get("effective_from"))
        if frm and p.submission_date < frm:
            continue
        if zone and any(x in zone for x in b.get("excludes", [])):
            continue
        for e in b.get("changes_plans", []):
            plan, lots = (e, None) if isinstance(e, str) else (e["plan"], e.get("lots"))
            if any(norm(plan) == norm(q) for q in p.plans) and (lots is None or _lot_in(p.lot, lots)):
                return b, (f"מ־{frm:%d.%m.%Y} חלות על המגרש הוראות הבינוי של תכנית {b['plan']} (שינוי לתכנית {plan}); "
                           "התכנית אינה מוסיפה שטחי בנייה")
    return None, ""


def _provisions_check(b: dict) -> "Check":
    v = b["provisions"]
    return Check("building_provisions", f"הוראות בינוי (תכנית {b['plan']})", "NOT_CHECKED",
                 f"גובה עד {v['height']['sloped_ridge_max_m']} מ׳ (גג משופע) / {v['height']['flat_with_railing_max_m']} מ׳ "
                 f"(גג שטוח) ממפלס הכניסה; מפלס כניסה עד {v['entrance_level']['above_sidewalk_mean_max_m']} מ׳ מעל המדרכה; "
                 f"מחסן עד {v['storage']['area_max_m2']} מ\"ר וגובה פנימי {v['storage']['inner_height_max_m']} מ׳; חניה מקורה "
                 f"עד {v['covered_parking']['area_max_m2']} מ\"ר; מרתף בגובה עד {v['basement']['height_max_m']} מ׳; גדרות "
                 f"עד {v['fences']['between_lots_max_m']} מ׳ — נבדקים מול החתכים, החזיתות ותכנית הפיתוח; חריגה טעונה הקלה.",
                 source_id=b["source_id"], needs=["חתכים וחזיתות עם מפלסים", "תכנית פיתוח וגדרות"])


def load_rights(plans: list[str], land_use: str | None, on: dt.date, folder: Path | None = None, *, lot: str | None = None,
                use: str | None = None, lot_area: float | None = None) -> tuple[dict | None, str]:
    """The rights file of a plan that applies on the date, for the lot's land use. (rights, note)"""
    folder = folder or Path(settings.knowledge_dir, "rights")
    norm = lambda s: re.sub(r"[\s\"״׳']", "", s or "")
    for path in sorted(folder.glob("*.yaml")):
        r = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not any(norm(p) in {norm(a) for a in [r["plan"], *r.get("aliases", [])]} for p in plans):
            continue
        if land_use and r.get("land_use") and not any(norm(u) in norm(land_use) or norm(land_use) in norm(u) for u in r["land_use"]):
            continue
        frm, to = _date(r.get("effective_from")), _date(r.get("effective_to"))
        if frm and on < frm:
            return None, f"התכנית {r['plan']} נכנסה לתוקף ב־{frm:%d.%m.%Y}, אחרי מועד הגשת הבקשה"
        if to and on >= to:
            return None, f"התכנית {r['plan']} לא הייתה בתוקף במועד הגשת הבקשה"
        sel, why = _select(r, lot, use, land_use, lot_area, on, folder)
        if sel is None:
            return None, why
        return sel, f"תכנית {r['plan']} בתוקף מ־{frm:%d.%m.%Y}" + (f" ({why})" if why else "") + \
            (f"; {r['amendment_check']}" if r.get("amendment_check") else "")
    return None, "לא נמצא קובץ זכויות לתכנית החלה"


def load_law(on: dt.date, path: Path | None = None) -> tuple[dict, bool, str]:
    """(law, verified_for_date, note): verified when the encoded text is the version in force on the date."""
    path = path or Path(settings.knowledge_dir, "law", "deviation_regulations_2002.yaml")
    law = yaml.safe_load(path.read_text(encoding="utf-8"))
    frm, cons = _date(law["in_force_from"]), _date(law.get("consolidated_as_of"))
    if on < frm:
        return law, False, f"התקנות נכנסו לתוקף ב־{frm:%d.%m.%Y} — לבקשה קודמת חלות התקנות מ־1967 (לא מקודדות)"
    if cons and on > cons:
        return law, False, (f"נוסח התקנות במאגר מעודכן עד {cons:%d.%m.%Y}; תיקונים מאוחרים עד מועד ההגשה "
                            f"({on:%d.%m.%Y}) לא אומתו — סיווג 'סטייה ניכרת' לא ייקבע כוודאי")
    return law, True, f"נוסח התקנות המעודכן ל־{cons:%d.%m.%Y} חל במועד ההגשה"


# ------------------------------------------------------------------ inputs from the committee register (blind facts)

def proposal_from_register(facts: dict, gis: dict | None = None) -> Proposal:
    """A Proposal from what the applicant submitted, as published in the committee register (no status, decision or
    reviewer comment). The route is the application type the applicant filed (type code in the page URL)."""
    m = re.search(r"Definement_Entity_Type=(\d+)", facts.get("source_url", ""))
    code = facts.get("application_type_code") or (m.group(1) if m else None)
    num = lambda s: float(re.search(r"[\d.]+", s).group(0)) if s and re.search(r"[\d.]+", s) else None
    land = (facts.get("land") or [{}])[0]
    lot_area, land_use = None, None
    for pl in (gis or {}).get("plans", []):
        for q in pl.get("doc33") or []:
            if str(q.get("lotName")) == str(land.get("מספר מגרש")):
                lot_area, land_use = q.get("qArea"), q.get("LandUseName")
    d, mth, y = facts["submission_date"].split("/")
    return Proposal(
        application_id=facts["application_id"], submission_date=dt.date(int(y), int(mth), int(d)),
        plans=[land.get("תוכנית קובעת מגרש")] if land.get("תוכנית קובעת מגרש") else [p["planName"] for p in (gis or {}).get("plans", [])],
        land_use=land_use, lot_area_m2=lot_area, selected_route=REGISTER_ROUTE.get(str(code)),
        route_source=f"סוג הבקשה במאגר הוועדה (קוד {code})" if code else "",
        total_main_m2=num(facts.get("primary_area")), total_service_m2=num(facts.get("service_area")),
        floors=None, floors_source="אין תכניות קומות זמינות", request_text=facts.get("request_text") or "",
        lot=land.get("מספר מגרש"), main_use=facts.get("main_use"),
        areas_scope="addition" if ADDITION.search(facts.get("request_text") or "") or facts.get("description") not in (
            None, "בנייה חדשה") else "total")


# ------------------------------------------------------------------ classification

def classify_setback(sb: Setback, law: dict) -> Check:
    """Building-line deviation per reg. 2(5)-(7): relief-eligible only within the listed exceptions."""
    over = round(sb.plan_m - sb.proposed_m, 2)
    he = {"front": "קדמי", "side": "צדדי", "rear": "אחורי"}[sb.side]
    if over <= 0:
        return Check(f"setback_{sb.side}", f"קו בניין {he}", "WITHIN", f"המרחק {sb.proposed_m} מ׳ ≥ {sb.plan_m} מ׳ בתכנית.",
                     sb.proposed_m, sb.plan_m, "מ׳", confirmable=True)
    rule = law["building_lines"][sb.side]
    pct = over / sb.plan_m * 100 if sb.plan_m else 100.0
    ok = False
    for ex in rule["relief_only"]:
        if ex["kind"] == "balcony" and sb.element == "balcony":
            ok = (sb.height_m or 0) >= ex["min_height_m"] and over <= ex["max_m"] and pct <= ex["max_pct"]
        elif ex["kind"] == "wall_with_openings" and sb.element == "wall" and sb.openings is True:
            ok = pct <= ex["max_pct"] and sb.proposed_m >= ex.get("min_distance_m", 0)
        elif ex["kind"] == "wall_without_openings" and sb.element == "wall" and sb.openings is False:
            ok = pct <= ex.get("max_pct", 100) and sb.proposed_m >= ex.get("min_distance_m", 0)
        if ok:
            break
    status = "RELIEF" if ok else "PROHIBITED"
    return Check(f"setback_{sb.side}", f"קו בניין {he}", status,
                 f"חריגה של {over} מ׳ ({pct:.0f}%) מקו הבניין ה{he} ({sb.plan_m} מ׳ בתכנית); "
                 + ("בתחום החריגות המותרות בהקלה" if ok else "מעבר לחריגות המותרות בהקלה — סטייה ניכרת") + f" (תקנה {rule['reg']}).",
                 sb.proposed_m, sb.plan_m, "מ׳", reg=rule["reg"], source_id=law["source_id"], confirmable=True)


def check_aggregate(p: Proposal, r: dict) -> list[Check]:
    out = []
    rt = r["rights"]
    if p.areas_scope != "total":
        return [Check("aggregate", "שטחים מול זכויות התכנית", "NOT_CHECKED",
                      "הבקשה מוסיפה או מסדירה בנייה בבניין קיים — השטחים שבמאגר עשויים להיות התוספת בלבד, ולכן אינם "
                      "מושווים לזכויות המגרש כולו.", source_id=r["source_id"], needs=["השטחים הקיימים בהיתר", "טבלת שטחים כוללת"])]
    if r.get("part_of_lot") and not rt.get("main_per_unit_m2"):
        return [Check("aggregate", "שטחים מול זכויות התכנית", "NOT_CHECKED",
                      f"הבקשה למגרש {r['part_of_lot']} — חלק של יחידה אחת במגרש דו־משפחתי, והזכויות בתכנית הן למגרש כולו; "
                      "נדרשת חלוקת הזכויות בין היחידות.", source_id=r["source_id"],
                      needs=["חלוקת הזכויות בין יחידות המגרש", "השטחים הבנויים ביחידה השנייה"])]
    svc = (None if rt.get("service_above_m2") is None or rt.get("service_below_m2") is None
           else rt["service_above_m2"] + rt["service_below_m2"])
    pairs = [("main", "שטח עיקרי כולל", p.total_main_m2, rt.get("main_m2")),
             ("service", "שטח שירות כולל (עילי ותת־קרקעי)", p.total_service_m2, svc)]
    if rt.get("main_m2") is None and rt.get("total_m2") is not None:      # a plan before the main/service split
        both = None if p.total_main_m2 is None or p.total_service_m2 is None else p.total_main_m2 + p.total_service_m2
        pairs = [("total", "שטח בנייה כולל", both, rt["total_m2"])]
    for key, he, val, lim in pairs:
        if lim is None:
            out.append(Check(f"aggregate_{key}", he, "NOT_CHECKED", "התכנית קובעת שטח זה לפי נתון שאינו בבקשה (שטח המגרש, "
                             "קומת הקרקע).", None, None, source_id=r["source_id"], needs=["שטח המגרש", "תכניות הקומות"]))
            continue
        if val is None:
            out.append(Check(f"aggregate_{key}", he, "NOT_CHECKED", "השטח המבוקש לא נמסר.", None, lim, source_id=r["source_id"],
                             needs=["שטחי הבקשה"]))
            continue
        if val <= lim + 0.005:
            out.append(Check(f"aggregate_{key}", he, "WITHIN", f"{val:.2f} מ\"ר ≤ {lim:.2f} מ\"ר בתכנית {r['plan']}.", val, lim,
                             source_id=r["source_id"], confirmable=True))
        else:
            out.append(Check(f"aggregate_{key}", he, "DEVIATION_UNCLASSIFIED",
                             f"{val:.2f} מ\"ר מעל {lim:.2f} מ\"ר בתכנית {r['plan']} — תוספת זכויות; האם ניתנת בהקלה אינו מוכרע "
                             "בתקנות המקודדות לתכנית שהופקדה אחרי 1.8.1989.", val, lim, source_id=r["source_id"], confirmable=True))
    return out


def check_floors(p: Proposal, r: dict, law: dict) -> list[Check]:
    """Floor-specific rights: floors above the entrance (with the regulation's basement definition), basement count,
    basement area against its own right plus the transfers the plan allows, service area used for main uses."""
    if p.floors is None:
        return [Check("floors", "זכויות לפי קומה ומרתף", "NOT_CHECKED",
                      "אין תכניות קומות או טבלת שטחים לפי קומה — לא ניתן לחשב את שטח המרתף ואת הזכויות לפי קומה. "
                      "עמידה בזכויות הכוללות אינה מוכיחה עמידה במגבלות המרתף.", source_id=r["source_id"],
                      needs=["תכנית קומת המרתף", "תכניות הקומות", "חתך עם מפלס הקרקע"])]
    out, rt, bs = [], r["rights"], r.get("basement") or {}
    conf = bool(p.floors_source)
    bdef = law["basement_definition"]["ceiling_above_ground_max_m"]
    below = [f for f in p.floors if f.below_entrance]
    counted, unknown = [f for f in p.floors if not f.below_entrance], []
    for f in below:                           # a "basement" whose ceiling rises above 1.20 m is a floor (reg. 2(8))
        if f.ceiling_above_ground_m is None:
            unknown.append(f.name)
        elif f.ceiling_above_ground_m > bdef:
            counted.append(f)
    n, lim = len(counted), rt["floors_above_entrance"]
    if n > lim:
        out.append(Check("floors_above", "מספר קומות מעל מפלס הכניסה", "PROHIBITED" if not law["substantial"]["added_floors"].get(
                             "relief_table_verified") else "RELIEF",
                         f"{n} קומות נספרות (כולל מרתף שתקרתו מעל {bdef} מ׳ מפני הקרקע) מול {lim} בתכנית — הוספת קומות היא סטייה ניכרת "
                         "אלא אם מתקיימים תנאי תקנה 2(8) וטבלתה.", n, lim, "קומות", reg="2(8)", source_id=r["source_id"],
                         confirmable=conf))
    else:
        out.append(Check("floors_above", "מספר קומות מעל מפלס הכניסה", "POSSIBLE_DEVIATION" if unknown else "WITHIN",
                         f"{n} קומות מעל הכניסה מול {lim} בתכנית" + (f"; גובה תקרת {', '.join(unknown)} מעל הקרקע לא ידוע — "
                         f"אם עולה על {bdef} מ׳ זו קומה נוספת." if unknown else "."), n, lim, "קומות", reg="2(8)",
                         source_id=r["source_id"], needs=["חתך עם גובה תקרת המרתף מעל פני הקרקע"] if unknown else [],
                         confirmable=conf and not unknown))
    if len(below) > bs.get("floors_max", 1):
        out.append(Check("basement_floors", "מספר קומות מרתף", "RELIEF",
                         f"{len(below)} קומות מתחת למפלס הכניסה מול {bs.get('floors_max', 1)} בתכנית.", len(below), bs.get("floors_max", 1),
                         "קומות", source_id=r["source_id"], confirmable=conf))
    above_main = sum(f.main_m2 for f in p.floors if not f.below_entrance)
    above_service = sum(f.service_m2 for f in p.floors if not f.below_entrance)
    base_area = round(sum(f.main_m2 + f.service_m2 for f in below), 2)
    own = rt["service_below_m2"]
    tr = r.get("transfers") or {}
    moved = 0.0
    if tr.get("to_basement"):
        moved = round(max(0.0, rt["main_m2"] - above_main) + max(0.0, rt["service_above_m2"] - above_service), 2)
    if below:
        mk = lambda st, text, lim, needs=(): Check("basement_area", "שטח המרתף", st, text, base_area, lim,
                                                   source_id=r["source_id"], needs=list(needs), confirmable=conf)
        if base_area <= own + 0.005:
            out.append(mk("WITHIN", f"שטח המרתף {base_area:.2f} מ\"ר ≤ {own:.2f} מ\"ר שירות תת־קרקעי בתכנית.", own))
        elif base_area <= own + moved + 0.005:
            mech = tr.get("mechanism", "unverified")
            text = (f"שטח המרתף {base_area:.2f} מ\"ר מעל {own:.2f} מ\"ר השירות התת־קרקעי בתכנית; הוא נשען על העברת "
                    f"{base_area - own:.2f} מ\"ר מהשטחים העיליים שלא נוצלו ({moved:.2f} מ\"ר) לפי הוראת ההעברה בתכנית")
            if mech == "by_right":
                out.append(mk("WITHIN", text + " — העברה מכוח התכנית.", own + moved))
            elif mech == "relief":
                out.append(mk("RELIEF", text + " — ההעברה טעונה הקלה.", own))
            else:
                out.append(mk("POSSIBLE_DEVIATION", text + " — התכנית אינה קובעת אם ההעברה מכוח זכות או טעונה פרסום/הקלה; "
                              "לא הוכרע.", own, ["אופן ההעברה לפי התכנית (מכוח זכות או בהקלה)"]))
        else:
            out.append(mk("RELIEF", f"שטח המרתף {base_area:.2f} מ\"ר מעל {own + moved:.2f} מ\"ר המותרים למרתף ({own:.2f} שירות "
                          f"תת־קרקעי" + (f" + {moved:.2f} שטחים עיליים שלא נוצלו" if moved else "") + f") — חריגה של "
                          f"{base_area - own - moved:.2f} מ\"ר מחלוקת השטחים שבתכנית; הגדלת המרתף טעונה הקלה (אינה מנויה "
                          "כסטייה ניכרת בתקנה 2, אלא אם התכנית קובעת זאת — תקנה 2(19)).", own + moved))
    misuse = sum(f.service_used_as_main_m2 for f in p.floors)
    if misuse > 0.005:
        out.append(Check("service_to_main", "שטח שירות בשימוש עיקרי", "PROHIBITED",
                         f"{misuse:.2f} מ\"ר שנספרו כשטח שירות מתוכננים לשימוש עיקרי — סטייה ניכרת (תקנה 2(16)).",
                         round(misuse, 2), 0.0, reg="2(16)", source_id=law["source_id"], confirmable=conf))
    return out


def check_declared(p: Proposal, r: dict) -> list[Check]:
    """Deviations the request itself declares (request text), e.g. a ±0.00 level other than the building plan's."""
    out = []
    if re.search(r"שינוי מפלס\s*0\.?00|שינוי\s+מפלס ה?-?0\.00|0\.00 לעומת", p.request_text):
        flex = (r.get("local_guidelines") or {}).get("zero_level_flex_m")
        if p.zero_level_change_m is None:
            out.append(Check("zero_level", "מפלס ±0.00 לעומת תכנית הבינוי", "POSSIBLE_DEVIATION",
                             "הבקשה מצהירה על שינוי מפלס 0.00 לעומת תכנית הבינוי, אך ערך השינוי אינו בנתונים"
                             + (f"; לפי הנחיות הבינוי מותרת גמישות של עד {flex['up']} מ׳ למעלה ו־{flex['down']} מ׳ למטה ({flex['condition']}), "
                                "ומעבר לה נדרשת הקלה." if flex else "."), needs=["מפלס 0.00 המוצע", "מפלס 0.00 בתכנית הבינוי"],
                             source_id=(r.get("local_guidelines") or {}).get("source_id")))
        else:
            ch = p.zero_level_change_m
            ok = flex and -flex["down"] <= ch <= flex["up"]
            out.append(Check("zero_level", "מפלס ±0.00 לעומת תכנית הבינוי", "WITHIN" if ok else "RELIEF",
                             f"שינוי של {ch:+.2f} מ׳ " + ("בתחום הגמישות שבהנחיות (באישור מהנדס הוועדה)." if ok
                                                      else "מעבר לגמישות שבהנחיות — נדרשת הקלה."),
                             ch, None, "מ׳", source_id=(r.get("local_guidelines") or {}).get("source_id"), confirmable=True))
    if re.search(r"(?<!ללא )(?<!בלי )(?<!ללא\s)הקל(?:ה|ות)\b", p.request_text) and p.selected_route == "REGULAR":
        out.append(Check("declared_relief", "הקלה המוזכרת בבקשה", "RELIEF",
                         "בתיאור הבקשה מוזכרת הקלה, אך הבקשה הוגשה במסלול ללא הקלות.", confirmable=True))
    return out


def check_short_track(p: Proposal) -> list[Check]:
    """Short-track eligibility on the gross new construction, not the net change.

    The form's addition field may hold a net figure (new construction minus approved area that is cancelled); the
    item's size limit applies to what is built. Cancelling approved-but-unbuilt area is a change of approved rights,
    not a physical demolition, so it does not offset the construction. A mismatch between the fields is a document
    discrepancy for clarification — never, by itself, a reason to call the route invalid."""
    if p.selected_route != "SHORT":
        return []
    out: list[Check] = []
    g, lim = p.gross_added_m2, p.short_item_limit_m2
    src = p.gross_added_source or "—"
    if g is None:
        out.append(Check("short_track_size", "היקף העבודה ברישוי מקוצר", "NOT_CHECKED",
                         "היקף הבנייה החדשה (ברוטו) לא נמדד: דרושות תכניות הבקשה.", limit=lim,
                         needs=["תכניות הבקשה (קומות) לחישוב הבנייה החדשה ברוטו"]))
    elif lim is None:
        out.append(Check("short_track_size", "היקף העבודה ברישוי מקוצר", "NOT_CHECKED",
                         f"בנייה חדשה {g:.2f} מ\"ר ({src}); מגבלת הפריט לא ידועה.", g,
                         needs=["נוסח פריט העבודה בתוספת לתקנות הרישוי"]))
    elif g <= lim:
        out.append(Check("short_track_size", "היקף העבודה ברישוי מקוצר", "WITHIN",
                         f"בנייה חדשה ברוטו {g:.2f} מ\"ר ≤ {lim:g} מ\"ר ({p.short_item_limit_source}); מקור הנתון: {src}.",
                         g, lim, reg=p.short_item_limit_source or None, confirmable=src == "drawings"))
    else:
        out.append(Check("short_track_size", "היקף העבודה ברישוי מקוצר", "DEVIATION_UNCLASSIFIED",
                         f"בנייה חדשה ברוטו {g:.2f} מ\"ר > {lim:g} מ\"ר — חורגת מפריט העבודה ברישוי מקוצר.",
                         g, lim, reg=p.short_item_limit_source or None, confirmable=src == "drawings",
                         needs=[] if src == "drawings" else ["מדידת הבנייה החדשה מתכניות הבקשה"]))
    d = p.declared_addition_m2
    if d is not None and g is not None and abs(d - g) > 0.5:
        net = g - (p.cancelled_unbuilt_m2 or 0)
        why = (f" ההפרש מתאים לשינוי נטו: {g:g} − {p.cancelled_unbuilt_m2:g} (שטח מאושר שלא נבנה) = {net:g} מ\"ר."
               if p.cancelled_unbuilt_m2 and abs(net - d) <= 0.5 else "")
        out.append(Check("short_track_fields", "שטח התוספת בטופס מול תיאור העבודה", "DOCUMENT_DISCREPANCY",
                         f"בטופס: שטח התוספת {d:g} מ\"ר; בתיאור הבקשה: בנייה חדשה {g:g} מ\"ר.{why} "
                         "יש להבהיר איזה נתון מוצהר; מגבלת הפריט נבדקת על הבנייה החדשה.", d, g))
    return out


def required_route(checks: list[Check]) -> str:
    st = {c.status for c in checks}
    if "PROHIBITED" in st:
        return "PROHIBITED"
    if st & {"RELIEF", "DEVIATION_UNCLASSIFIED"}:
        return "NOT_REGULAR"
    if st & {"POSSIBLE_DEVIATION", "NOT_CHECKED"}:
        return "UNKNOWN"
    return "REGULAR"


def validate(p: Proposal, rights_folder: Path | None = None, law_path: Path | None = None) -> RouteResult:
    rights, rnote = load_rights(p.plans, p.land_use, p.submission_date, rights_folder, lot=p.lot, use=p.main_use,
                                lot_area=p.lot_area_m2)
    law, law_ok, lnote = load_law(p.submission_date, law_path)
    short = check_short_track(p)
    if rights is None:
        # without the plan's rights only what the request itself declares can be judged (e.g. a relief it names
        # while filed without reliefs) — that needs no rights file
        declared = check_declared(p, {})
        decisive = [c for c in declared if c.status == "RELIEF"]
        prov, pnote = building_provisions(p, None, rights_folder.parent / "building_provisions" if rights_folder else None)
        notes = [rnote, lnote] + ([pnote] if prov else [])
        extra = [_provisions_check(prov)] if prov else []     # building provisions apply whatever the rights file
        if decisive and p.selected_route == "REGULAR":
            return RouteResult(p.application_id, p.selected_route, "NOT_REGULAR", "WRONG_ROUTE",
                               all(c.confirmable for c in decisive), short + declared + extra, notes)
        return RouteResult(p.application_id, p.selected_route, "UNKNOWN", "NO_RIGHTS", False, short + declared + extra, notes)
    checks = short + check_aggregate(p, rights) + check_floors(p, rights, law) + check_declared(p, rights)
    checks += [classify_setback(sb, law) for sb in p.setbacks]
    prov, pnote = building_provisions(p, rights.get("zone"), rights_folder.parent / "building_provisions" if rights_folder else None)
    if prov:
        checks.append(_provisions_check(prov))
        lnote = f"{lnote}; {pnote}" if lnote else pnote
    if p.lot_area_m2 is not None and rights.get("lot_min_m2"):
        lo = rights["lot_min_m2"] * (1 - rights.get("lot_min_tolerance_pct", 0) / 100)
        checks.append(Check("lot_area", "שטח מגרש מינימלי", "WITHIN" if p.lot_area_m2 >= lo else "DEVIATION_UNCLASSIFIED",
                            f"שטח המגרש {p.lot_area_m2:.1f} מ\"ר; מינימום {rights['lot_min_m2']} מ\"ר (סטייה מותרת "
                            f"{rights.get('lot_min_tolerance_pct', 0)}%).", round(p.lot_area_m2, 1), lo, source_id=rights["source_id"],
                            confirmable=True))
    need = required_route(checks)
    sel = p.selected_route
    decisive = [c for c in checks if c.status in ("RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED")]
    if need == "PROHIBITED":
        verdict = "PROHIBITED_DEVIATION"
        confirmed = law_ok and all(c.confirmable for c in decisive if c.status == "PROHIBITED")
    elif need == "NOT_REGULAR" and sel == "REGULAR":
        verdict, confirmed = "WRONG_ROUTE", all(c.confirmable for c in decisive) and bool(decisive)
    elif need == "UNKNOWN":
        verdict, confirmed = "INSUFFICIENT_EVIDENCE", False
    else:
        verdict, confirmed = "ROUTE_OK", True
    if verdict == "PROHIBITED_DEVIATION" and sel == "REGULAR" and not confirmed:
        # the route is wrong whatever the classification: any deviation excludes the regular route
        verdict, confirmed = "WRONG_ROUTE", all(c.confirmable for c in decisive)
    return RouteResult(p.application_id, sel, need, verdict, confirmed, checks, [rnote, lnote], rights["source_id"])


def summary_he(res: RouteResult) -> str:
    sel = ROUTES_HE.get(res.selected_route or "", "לא ידוע")
    if res.verdict == "NO_RIGHTS":
        return "אין קובץ זכויות לתכנית החלה — מסלול הרישוי לא נבדק."
    if res.verdict == "WRONG_ROUTE":
        dev = "; ".join(c.topic_he for c in res.checks if c.status in ("RELIEF", "DEVIATION_UNCLASSIFIED", "PROHIBITED"))
        return f"הבקשה הוגשה במסלול {sel}, אך כוללת חריגות מהתכנית ({dev}) — מסלול זה אינו מתאים."
    if res.verdict == "PROHIBITED_DEVIATION":
        return "הבקשה כוללת סטייה ניכרת מהתכנית, שאינה ניתנת לאישור בהקלה."
    if res.verdict == "INSUFFICIENT_EVIDENCE":
        need = sorted({n for c in res.checks for n in c.needs})
        return f"מסלול הרישוי ({sel}) לא הוכרע: חסרים {', '.join(need)}."
    return f"מסלול הרישוי ({sel}) תואם את הבקשה."
