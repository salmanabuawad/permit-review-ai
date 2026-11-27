"""ReliefValidationEngine — one assessment per requested relief.

For each relief: the binding regulation, the permitted and requested values, the absolute and percentage deviation,
whether a relief is legally available under the framework in force on the submission date, whether the deviation is
substantial, whether a planning justification and supporting evidence were provided, whether the decision is the
committee's discretion, and which procedures apply (publication under s.149).

The outcome keeps deterministic findings apart from discretionary ones:
  CONFIRMED_VIOLATION            the value exceeds the limit and no relief was requested (needs measured/declared value)
  LEGALLY_UNAVAILABLE_RELIEF     the regulations make this deviation substantial — a relief cannot approve it
  UNRESOLVED_APPLICABILITY       the binding limit itself is not established
  INSUFFICIENT_EVIDENCE          the requested value is not evidenced
  MISSING_PLANNING_JUSTIFICATION a relief that may be legal, filed without a planning justification
  DISCRETIONARY_DECISION_REQUIRED a relief that may be legal, with a justification: for the committee to weigh
  PERMISSIBLE_RELIEF_REQUESTED   (alias kept for reports) — legal possibility only, never "justified"
  WITHIN_LIMIT                   the requested value does not exceed the limit (no relief needed)
A relief is never treated as justified because it is legally possible, and never rejected only because the value
exceeds the original limit. Only CONFIRMED_VIOLATION and LEGALLY_UNAVAILABLE_RELIEF may reach an external report, and an
unapproved requested relief is never reported as existing illegal construction.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .components import Component, validate_component

JUSTIFICATION = re.compile(r"נימוק|הצדקה|בשל |עקב |מאחר|לאור |בגלל|לצורך |הואיל|justif", re.I)
DESIGN_COMPONENTS = {"covered_parking", "storage", "pergola", "fence", "roof", "auxiliary_building", "basement",
                     "external_stairs", "garage", "retaining_wall"}


@dataclass
class ReliefRequest:
    component: str
    attribute: str
    requested_value: float | None
    value_source: str = "declared"                # declared | committee_reported | measured | drawing_read
    text: str = ""                                # the request's own wording of the relief
    justification: str | None = None              # the applicant's planning justification, if any
    evidence: list = field(default_factory=list)  # documents supporting the requested value
    published: bool | None = None                 # s.149 publication done


@dataclass
class ReliefAssessment:
    component: str
    attribute: str
    binding_regulation: dict
    permitted: float | None
    requested: float | None
    deviation_abs: float | None
    deviation_pct: float | None
    legally_available: str                        # YES | NO | CONDITIONAL | UNKNOWN
    substantial: str                              # NO | YES | POSSIBLE | UNKNOWN
    justification: str                            # PROVIDED | NOT_PROVIDED
    evidence: str                                 # PROVIDED | NOT_PROVIDED
    discretionary: bool
    procedural: list
    outcome: str
    external: bool                                # may appear in the external defects report
    explanation_he: str

    def as_dict(self) -> dict:
        return asdict(self)


class ReliefValidationEngine:
    def __init__(self, law: dict):
        self.law = law

    def assess(self, req: ReliefRequest, limits: dict) -> ReliefAssessment:
        comp = Component(req.component, reliefs=[req.attribute])
        if req.requested_value is not None:
            from .components import Measure
            comp.measures[req.attribute] = Measure(req.requested_value, req.value_source)
        f = next(x for x in validate_component(comp, limits) if x.attribute == req.attribute)
        just = "PROVIDED" if (req.justification or JUSTIFICATION.search(req.text or "")) else "NOT_PROVIDED"
        evid = "PROVIDED" if req.evidence else "NOT_PROVIDED"
        proc = ["פרסום לפי סעיף 149 לחוק (הקלה)"] + ([] if req.published is None else
                                                    [f"פרסום בוצע: {'כן' if req.published else 'לא'}"])
        base = dict(component=req.component, attribute=req.attribute, binding_regulation=f.regulation,
                    permitted=f.permitted, requested=f.value, deviation_abs=f.deviation_abs, deviation_pct=f.deviation_pct,
                    justification=just, evidence=evid, procedural=proc)
        if f.status in ("NO_APPLICABLE_LIMIT", "UNRESOLVED_LIMIT"):
            return ReliefAssessment(**base, legally_available="UNKNOWN", substantial="UNKNOWN", discretionary=False,
                                    outcome="UNRESOLVED_APPLICABILITY", external=False,
                                    explanation_he="המגבלה החלה על הרכיב לא הוכרעה — "
                                                   + (f.regulation.get("note") or "אין מקור במאגר הידע"))
        if f.status == "NO_MEASUREMENT":
            return ReliefAssessment(**base, legally_available="UNKNOWN", substantial="UNKNOWN", discretionary=False,
                                    outcome="INSUFFICIENT_EVIDENCE", external=False,
                                    explanation_he="הערך המבוקש אינו נתון בבקשה או במסמכיה.")
        if f.status == "WITHIN":
            return ReliefAssessment(**base, legally_available="YES", substantial="NO", discretionary=False,
                                    outcome="WITHIN_LIMIT", external=False,
                                    explanation_he=f"הערך המבוקש {f.value} אינו עולה על המותר {f.permitted} — אין צורך בהקלה.")
        avail, subst, why = self._availability(req, f)
        if avail == "NO":
            return ReliefAssessment(**base, legally_available="NO", substantial="YES", discretionary=False,
                                    outcome="LEGALLY_UNAVAILABLE_RELIEF", external=True, explanation_he=why)
        reg = f.regulation
        head = (f"{_he(req)}: מבוקש {f.value} במקום {f.permitted} המותרים (חריגה {f.deviation_abs} — {f.deviation_pct}%) "
                f"לפי תכנית {reg.get('plan')}" + (f" סעיף {reg['clause']}" if reg.get("clause") else "") + ". " + why)
        if just == "NOT_PROVIDED":
            return ReliefAssessment(**base, legally_available=avail, substantial=subst, discretionary=True,
                                    outcome="MISSING_PLANNING_JUSTIFICATION", external=False,
                                    explanation_he=head + " לא צורף נימוק תכנוני להקלה; ההכרעה בשיקול דעת הוועדה.")
        return ReliefAssessment(**base, legally_available=avail, substantial=subst, discretionary=True,
                                outcome="DISCRETIONARY_DECISION_REQUIRED", external=False,
                                explanation_he=head + " צורף נימוק; ההכרעה בשיקול דעת הוועדה ואינה נקבעת מכנית.")

    def _availability(self, req: ReliefRequest, f) -> tuple[str, str, str]:
        sub = self.law.get("substantial", {})
        if req.component in DESIGN_COMPONENTS and "design_requirements" in sub:
            d = sub["design_requirements"]
            return ("CONDITIONAL", "POSSIBLE",
                    f"הקלה מהוראות בינוי אפשרית, אלא אם ההוראה נועדה לקבוע את אופי הבנייה או לשמור על חזות הסביבה "
                    f"(תקנה {d['reg']} לתקנות הסטייה הניכרת) — הכרעה משפטית, לא חישובית.")
        return "UNKNOWN", "UNKNOWN", "סיווג החריגה לפי תקנות הסטייה הניכרת אינו מקודד לרכיב זה."

    def assess_violation(self, comp: Component, limits: dict) -> list[ReliefAssessment]:
        """Components measured above their limit with no relief requested: confirmed violations only when the value
        is measured or declared by the applicant; a committee-reported value stays internal."""
        out = []
        for f in validate_component(comp, limits):
            if f.status != "EXCEEDS":
                continue
            ext = f.evidence_source in ("measured", "declared")
            out.append(ReliefAssessment(comp.kind, f.attribute, f.regulation, f.permitted, f.value, f.deviation_abs,
                                        f.deviation_pct, "N/A", "UNKNOWN", "N/A", "PROVIDED" if ext else "NOT_PROVIDED",
                                        False, [], "CONFIRMED_VIOLATION" if ext else "INSUFFICIENT_EVIDENCE", ext,
                                        f"{comp.kind}.{f.attribute}: {f.value} מעל המותר {f.permitted} ללא בקשת הקלה."))
        return out


HE = {"covered_parking": "חניה מקורה", "storage": "מחסן", "basement": "מרתף", "fence": "גדר", "roof": "גג",
      "inner_height_m": "גובה פנימי", "outer_height_m": "גובה חיצוני", "area_m2": "שטח"}


def _he(req: ReliefRequest) -> str:
    return f"{HE.get(req.attribute, req.attribute)} {HE.get(req.component, req.component)}"
