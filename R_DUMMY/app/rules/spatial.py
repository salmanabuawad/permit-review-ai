"""Spatial screens against limits, with measurement uncertainty (V9 §Engines: GIS).

A geometric check compares a measured margin with a rule limit. The outcome is decided only when the margin is
larger than the combined uncertainty of the measurement AND the geometry is verified (native transform checked
against independent controls). Otherwise it is UNRESOLVED — candidate geometry is never certified.

    margin = allowed - measured  (positive = inside the limit, e.g. distance to the building line beyond the setback)

Rules encoded here (deterministic, no model):
  * independent measurements that disagree in sign (e.g. -0.240 m and +0.009 m to the local building line) → UNRESOLVED
  * |margin| ≤ uncertainty → UNRESOLVED
  * margin > uncertainty → PASS; margin < -uncertainty on verified geometry → CONFIRMED_DEFECT
  * an overlap with a well protection zone is not by itself a violation: the zone's restriction must name what is
    forbidden or conditioned there → UNRESOLVED (or FUTURE_STAGE when the restriction is a permit condition).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Measurement:
    value_m: float                   # signed margin to the limit (positive = complies)
    uncertainty_m: float             # 1-sigma-ish combined: drawing transform + source map + digitisation
    method: str                      # e.g. "native DWFX transform", "GIS overlay"
    verified: bool = False           # transform checked against independent controls (survey points, ITM coords)


@dataclass
class SpatialOutcome:
    status: str                      # PASS | CONFIRMED_DEFECT | UNRESOLVED | NOT_CHECKED
    explanation_he: str
    measurements: list = field(default_factory=list)


def classify_margin(topic_he: str, ms: list[Measurement]) -> SpatialOutcome:
    if not ms:
        return SpatialOutcome("NOT_CHECKED", f"{topic_he}: לא נמדד.")
    vals = "; ".join(f"{m.value_m:+.3f} מ׳ ±{m.uncertainty_m:.3f} ({m.method})" for m in ms)
    signs = {m.value_m > 0 for m in ms if abs(m.value_m) > 1e-9}
    if len(signs) > 1:
        return SpatialOutcome("UNRESOLVED", f"{topic_he}: מדידות בלתי תלויות אינן מסכימות בכיוון החריגה ({vals}).", ms)
    if any(abs(m.value_m) <= m.uncertainty_m for m in ms):
        return SpatialOutcome("UNRESOLVED", f"{topic_he}: המרווח קטן מאי-הוודאות של המדידה ({vals}).", ms)
    if all(m.value_m > 0 for m in ms):
        return SpatialOutcome("PASS", f"{topic_he}: בתחום המותר ({vals}).", ms)
    if any(m.verified for m in ms):
        return SpatialOutcome("CONFIRMED_DEFECT", f"{topic_he}: חריגה מעבר לאי-הוודאות בגאומטריה מאומתת ({vals}).", ms)
    return SpatialOutcome("UNRESOLVED", f"{topic_he}: חריגה לכאורה בגאומטריה שלא אומתה מול נקודות בקרה ({vals}).", ms)


# Plan 633-0723718 §6.4 ב(4) (Ministry of Health guidance for drinking-water wells), OCR of the approved scan,
# knowledge/source_texts/ha_633_0723718/ocr/approved_2021_p14.txt (also HA-35281D41D0 p.15):
#   א' — any building, except for operating the well;  ב' — building that may pollute the well, e.g. residential,
#   commercial or public buildings;  ג' — works that may cause severe pollution, e.g. a sewage facility, a main sewer
#   line or effluent irrigation;  ד) no fertilisation in the protection radius (an activity, not a building ban).
WELL_ZONES = {
    "A": {"forbids_residential": True, "quote_he": "באזור מגן א' אסורה כל בניה למעט למבנים המשמשים להפעלת הקידוח"},
    "B": {"forbids_residential": True, "quote_he": "באזור מגן ב' אסורים כל בניה ... כגון: מבני מגורים"},
    "C": {"forbids_residential": False, "quote_he": "באזור מגן ג' ... העלולים לגרום לזיהום חמור ... כגון: מתקן ביוב, קו ביוב ראשי"},
}
WELL_SOURCE = "HA-PLAN-633-0723718 §6.4 ב(4)"


def well_zone(zone: str | None, overlap_m2: float | None, residential: bool = True, geometry_verified: bool = False,
              permit_condition: bool = False) -> SpatialOutcome:
    """Overlap of the works with a well protection zone. Overlap alone is never a violation: what the zone forbids
    decides. Zone C does not forbid a residential building (only severe-pollution works such as sewage facilities)."""
    if overlap_m2 is None or zone is None:
        return SpatialOutcome("NOT_CHECKED", "רדיוס מגן קידוח: החפיפה או האזור לא נמדדו.")
    if overlap_m2 <= 0:
        return SpatialOutcome("PASS", f"רדיוס מגן קידוח: אין חפיפה עם אזור {zone}.")
    z = WELL_ZONES.get(zone.upper())
    if z is None:
        return SpatialOutcome("UNRESOLVED", f"רדיוס מגן קידוח: אזור {zone} אינו מוגדר בתכנית.")
    if residential and not z["forbids_residential"]:
        return SpatialOutcome("FUTURE_STAGE" if permit_condition else "PASS",
                              f"חפיפה {overlap_m2:.1f} מ\"ר עם אזור מגן ג': ההגבלה חלה על עבודות העלולות לגרום לזיהום "
                              f"חמור (מתקן ביוב, קו ביוב ראשי) ואינה איסור על מבנה מגורים ({WELL_SOURCE}). "
                              "צנרת הביוב בתחום — לפי דרישות התכנית.")
    if not geometry_verified:
        return SpatialOutcome("UNRESOLVED", f"חפיפה {overlap_m2:.1f} מ\"ר עם אזור מגן {zone} בגאומטריה שלא אומתה — "
                                            f"\"{z['quote_he']}\" ({WELL_SOURCE}).")
    return SpatialOutcome("CONFIRMED_DEFECT", f"מבנה מגורים בתחום אזור מגן {zone}: \"{z['quote_he']}\" ({WELL_SOURCE}).")
