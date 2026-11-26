"""ApplicableRegulationResolver — which regulatory sources govern one application, and the component limits they set.

Resolution uses the submission date, the plans' effective dates, the block / parcel / lot, the lot's zone (rights file
or GIS land use), the main use, and the relations between plans recorded in the knowledge base ("changes", "subordinate
to", "rights from"). It never picks the strictest or newest rule by default: where two sources set the same limit, the
source that legally changes the other (and was in force on the submission date) governs; with no recorded relation the
limit is UNRESOLVED and both values are kept as evidence. A plan the application names but the knowledge base does not
hold is UNRESOLVED, never silently ignored.

Sources considered (each only if the knowledge base holds it): national regulations (deviation regulations 2002),
national / district / local outline plans, detailed plans, regulatory ("תקנונית") plans, amendments, local building
guidelines, the lot's permit history (historical reliefs), licensing information. Transitional provisions: a source
applies to requests submitted on or after its effective date unless its file says otherwise.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from ..config import settings
from . import route as R

KINDS = ("national_regulation", "national_plan", "district_plan", "outline_plan", "detailed_plan", "regulatory_plan",
         "amendment", "local_guideline", "building_regulation", "transitional_provision", "historical_relief",
         "licensing_information")


@dataclass
class AppContext:
    application_id: str
    submission_date: dt.date
    plans: list[str]                              # lot-defining plan first, then other plans named or found in the GIS
    block: str | None = None
    parcel: str | None = None
    lot: str | None = None
    main_use: str | None = None
    building_type: str | None = None              # e.g. "single-family", "farm holding"
    activity: str = ""                            # the request text
    land_use: str | None = None                   # the zone, from the GIS when known
    lot_area_m2: float | None = None


@dataclass
class RegSource:
    plan: str
    kind: str
    status: str                                   # APPLIES | NOT_APPLICABLE | UNRESOLVED
    reason: str
    source_id: str | None = None
    effective_from: str | None = None
    relation: str | None = None                   # e.g. "changes 6/123/03/6", "subordinate to תמא 39"
    evidence: list = field(default_factory=list)


@dataclass
class Limit:
    component: str
    attribute: str                                # area_m2 | inner_height_m | outer_height_m | ...
    value: float | None
    plan: str
    source_id: str
    clause: str | None = None
    page: object = None
    status: str = "GOVERNS"                       # GOVERNS | SUPERSEDED | UNRESOLVED_CONFLICT
    note: str = ""


@dataclass
class Resolution:
    sources: list[RegSource]
    limits: dict                                  # (component, attribute) -> Limit that governs (or UNRESOLVED_CONFLICT)
    superseded: list[Limit]
    rights: dict | None
    unresolved: list[str]

    def as_dict(self) -> dict:
        return {"sources": [asdict(s) for s in self.sources],
                "limits": {f"{c}.{a}": asdict(v) for (c, a), v in self.limits.items()},
                "superseded": [asdict(x) for x in self.superseded], "unresolved": self.unresolved,
                "rights_zone": (self.rights or {}).get("zone")}


# attribute names of the building-provisions file → (component, attribute)
PROVISION_ATTRS = {
    ("storage", "area_max_m2"): ("storage", "area_m2"),
    ("storage", "inner_height_max_m"): ("storage", "inner_height_m"),
    ("storage", "outer_height_max_m"): ("storage", "outer_height_m"),
    ("covered_parking", "area_max_m2"): ("covered_parking", "area_m2"),
    ("covered_parking", "inner_max_m"): ("covered_parking", "inner_height_m"),
    ("covered_parking", "top_max_m"): ("covered_parking", "outer_height_m"),
    ("basement", "height_max_m"): ("basement", "inner_height_m"),
    ("basement", "main_to_basement_max_m2"): ("basement", "main_area_m2"),
    ("fences", "between_lots_max_m"): ("fence", "outer_height_m"),
    ("height", "sloped_ridge_max_m"): ("roof", "ridge_height_m"),
    ("height", "flat_with_railing_max_m"): ("roof", "flat_height_m"),
    ("service_yard", "wall_height_max_m"): ("auxiliary_building", "outer_height_m"),
}
RIGHTS_ATTRS = {"area_max_m2": "area_m2", "height_sloped_max_m": "ridge_height_m", "height_flat_max_m": "flat_height_m"}
RIGHTS_COMPONENT = {"building": "roof"}


def _norm(s: str | None) -> str:
    return R.re.sub(r"[\s\"״׳']", "", s or "")


class ApplicableRegulationResolver:
    def __init__(self, knowledge_dir: Path | None = None):
        self.k = Path(knowledge_dir or settings.knowledge_dir)

    def kb_version(self) -> str:
        """Hash of every knowledge file the resolver reads — the cache key's plan-version part."""
        h = hashlib.sha256()
        for d in ("rights", "building_provisions", "law", "rules"):
            for f in sorted((self.k / d).glob("*.yaml")):
                h.update(f.name.encode() + f.read_bytes())
        return h.hexdigest()[:16]

    def cache_key(self, app: AppContext) -> str:
        return f"applicability/2|{app.block}|{app.parcel}|{app.lot}|{app.submission_date}|{app.main_use}|" \
               f"{app.land_use}|{app.lot_area_m2}|{'+'.join(app.plans)}|{self.kb_version()}"

    def resolve(self, app: AppContext, cache=None) -> Resolution:
        if cache is not None:                     # cache(key, compute) -> dict, e.g. backed by derivation_cache
            return _from_dict(cache(self.cache_key(app), lambda: _to_dict(self._resolve(app))))
        return self._resolve(app)

    # ------------------------------------------------------------------ resolution
    def _resolve(self, app: AppContext) -> Resolution:
        src: list[RegSource] = []
        unresolved: list[str] = []
        law = yaml.safe_load((self.k / "law" / "deviation_regulations_2002.yaml").read_text(encoding="utf-8"))
        frm = R._date(law.get("in_force_from"))
        src.append(RegSource("תקנות התכנון והבניה (סטיה ניכרת מתכנית), תשס\"ב-2002", "national_regulation",
                             "APPLIES" if frm and app.submission_date >= frm else "NOT_APPLICABLE",
                             f"in force from {frm}; consolidated as of {law.get('consolidated_as_of')} — later amendments "
                             "not verified", law.get("source_id"), str(frm)))
        p = R.Proposal(application_id=app.application_id, submission_date=app.submission_date, plans=app.plans,
                       land_use=app.land_use, lot_area_m2=app.lot_area_m2, lot=app.lot, main_use=app.main_use)
        rights, rnote = R.load_rights(app.plans[:1], app.land_use, app.submission_date, self.k / "rights",
                                      lot=app.lot, use=app.main_use, lot_area=app.lot_area_m2)
        known = set()
        for f in (self.k / "rights").glob("*.yaml"):
            y = yaml.safe_load(f.read_text(encoding="utf-8"))
            known |= {_norm(a) for a in [y["plan"], *y.get("aliases", [])]}
        rules_files = {}                          # plans encoded as executable rules (knowledge/rules), not as rights
        for f in sorted((self.k / "rules").glob("*.yaml")):
            txt = f.read_text(encoding="utf-8")
            for q in app.plans:
                if q and q in txt:
                    rules_files.setdefault(_norm(q), f.name)
        lot_plan = app.plans[0] if app.plans else None
        if lot_plan:
            if rights:
                src.append(RegSource(lot_plan, "detailed_plan", "APPLIES", rnote, rights.get("source_id"),
                                     rights.get("effective_from"), evidence=[{"zone": rights.get("zone")}]))
                if rights.get("via_plan") or "→" in str(rights.get("zone", "")):
                    src.append(RegSource(rights["plan"], "outline_plan", "APPLIES",
                                         f"rights of {lot_plan} are set by {rights['plan']} ({rights.get('zone')})",
                                         rights.get("source_id"), rights.get("effective_from"),
                                         relation=f"rights for {lot_plan}"))
                if rights.get("local_guidelines"):
                    g = rights["local_guidelines"]
                    src.append(RegSource(g.get("source_id", "local guidelines"), "local_guideline", "APPLIES",
                                         "building guidelines attached to the plan's rights (guidelines, not plan provisions)",
                                         g.get("source_id")))
            else:
                st = "NOT_APPLICABLE" if ("לא הייתה בתוקף" in rnote or "אחרי מועד" in rnote or "אין זכויות לשימוש" in rnote) \
                    else "UNRESOLVED"
                if _norm(lot_plan) in rules_files:
                    st, rnote = "APPLIES", (f"plan {lot_plan} is encoded as executable rules in knowledge/rules/"
                                            f"{rules_files[_norm(lot_plan)]} (no rights file)")
                elif _norm(lot_plan) not in known:
                    st, rnote = "UNRESOLVED", f"plan {lot_plan} is not in the knowledge base"
                src.append(RegSource(lot_plan, "detailed_plan", st, rnote))
                if st == "UNRESOLVED":
                    unresolved.append(f"{lot_plan}: {rnote}")
        for other in app.plans[1:]:
            if _norm(other) in rules_files:
                src.append(RegSource(other, "detailed_plan", "APPLIES", f"encoded as rules in knowledge/rules/{rules_files[_norm(other)]}"))
            elif _norm(other) not in known:
                src.append(RegSource(other, "detailed_plan", "UNRESOLVED", "named for the land but not in the knowledge base"))
                unresolved.append(f"{other}: not in the knowledge base")
        # regulatory / building-provisions plans that change listed plans
        for f in sorted((self.k / "building_provisions").glob("*.yaml")):
            b = yaml.safe_load(f.read_text(encoding="utf-8"))
            prov, pnote = R.building_provisions(p, (rights or {}).get("zone"), self.k / "building_provisions", only=f)
            listed = [e if isinstance(e, str) else e["plan"] for e in b.get("changes_plans", [])]
            hit = next((q for q in app.plans if any(_norm(q) == _norm(x) for x in listed)), None)
            eff = R._date(b.get("effective_from"))
            if prov and prov["plan"] == b["plan"]:
                src.append(RegSource(b["plan"], "regulatory_plan", "APPLIES", pnote, b["source_id"], str(eff),
                                     relation=f"changes {hit}; subordinate to {', '.join(b.get('subordinate_to', []))}",
                                     evidence=[{"verified_applicability": b.get("verified_applicability")}]))
            elif hit is None:
                src.append(RegSource(b["plan"], "regulatory_plan", "NOT_APPLICABLE",
                                     "none of the application's plans is among the plans it changes", b["source_id"], str(eff)))
            elif eff and app.submission_date < eff:
                src.append(RegSource(b["plan"], "regulatory_plan", "NOT_APPLICABLE",
                                     f"submitted {app.submission_date} — before it came into force ({eff})", b["source_id"], str(eff)))
            elif not app.main_use or "מגורים" not in app.main_use:
                src.append(RegSource(b["plan"], "regulatory_plan", "NOT_APPLICABLE", "not a residential use", b["source_id"], str(eff)))
            elif rights is None and not app.lot:
                src.append(RegSource(b["plan"], "regulatory_plan", "UNRESOLVED",
                                     f"changes {hit}, but the lot's zone is unknown", b["source_id"], str(eff)))
                unresolved.append(f"{b['plan']}: zone of the lot unknown")
            else:
                src.append(RegSource(b["plan"], "regulatory_plan", "NOT_APPLICABLE",
                                     f"changes {hit} only for listed lots / residential zones; this lot or zone is outside it",
                                     b["source_id"], str(eff)))
        limits, superseded = self._limits(app, rights, src)
        for (c, a), lim in limits.items():
            if lim.status == "UNRESOLVED_CONFLICT":
                unresolved.append(f"{c}.{a}: {lim.note}")
        return Resolution(src, limits, superseded, rights, unresolved)

    # ------------------------------------------------------------------ limits and conflicts
    def _limits(self, app: AppContext, rights: dict | None, src: list[RegSource]):
        cands: dict[tuple, list[Limit]] = {}
        if rights:
            for comp, attrs in (rights.get("components") or {}).items():
                for k, v in attrs.items():
                    if k in RIGHTS_ATTRS and isinstance(v, (int, float)):
                        key = (RIGHTS_COMPONENT.get(comp, comp), RIGHTS_ATTRS[k])
                        cands.setdefault(key, []).append(Limit(*key, float(v), rights["plan"], rights["source_id"],
                                                               attrs.get("clause"), attrs.get("page")))
        applies = {s.plan for s in src if s.status == "APPLIES" and s.kind == "regulatory_plan"}
        for f in sorted((self.k / "building_provisions").glob("*.yaml")):
            b = yaml.safe_load(f.read_text(encoding="utf-8"))
            if b["plan"] not in applies:
                continue
            for comp, attrs in b["provisions"].items():
                for k, v in attrs.items():
                    key = PROVISION_ATTRS.get((comp, k))
                    if key and isinstance(v, (int, float)):
                        cl = (b.get("clauses") or {}).get(comp, {})
                        cands.setdefault(key, []).append(Limit(*key, float(v), b["plan"], b["source_id"],
                                                               cl.get("clause"), cl.get("page")))
        changes = {}
        for f in sorted((self.k / "building_provisions").glob("*.yaml")):
            b = yaml.safe_load(f.read_text(encoding="utf-8"))
            changes[b["plan"]] = {_norm(e if isinstance(e, str) else e["plan"]) for e in b.get("changes_plans", [])}
        limits, superseded = {}, []
        for key, ls in cands.items():
            vals = {x.value for x in ls}
            if len(ls) == 1 or len(vals) == 1:
                limits[key] = ls[0]
                continue
            # the source that legally changes the other governs; otherwise the conflict stays open
            gov = [x for x in ls if any(_norm(y.plan) in changes.get(x.plan, set()) for y in ls if y is not x)]
            if len(gov) == 1:
                g = gov[0]
                for y in ls:
                    if y is not g:
                        y.status, y.note = "SUPERSEDED", f"changed by {g.plan} (in force on the submission date)"
                        superseded.append(y)
                g.note = f"governs over {', '.join(y.plan for y in ls if y is not g)} (relation: changes)"
                limits[key] = g
            else:
                limits[key] = Limit(*key, None, " / ".join(x.plan for x in ls), "", status="UNRESOLVED_CONFLICT",
                                    note="; ".join(f"{x.plan}: {x.value}" for x in ls) + " — no recorded relation decides")
        return limits, superseded


def _to_dict(r: Resolution) -> dict:
    return {"sources": [asdict(s) for s in r.sources],
            "limits": [asdict(v) for v in r.limits.values()], "superseded": [asdict(x) for x in r.superseded],
            "rights": json.loads(json.dumps(r.rights, default=str)) if r.rights else None, "unresolved": r.unresolved}


def _from_dict(d: dict) -> Resolution:
    lim = [Limit(**x) for x in d["limits"]]
    return Resolution([RegSource(**s) for s in d["sources"]], {(x.component, x.attribute): x for x in lim},
                      [Limit(**x) for x in d["superseded"]], d.get("rights"), d["unresolved"])
