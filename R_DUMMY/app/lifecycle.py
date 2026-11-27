"""Application lifecycle: structured committee decisions and version comparison.

Decision taxonomy — an application may carry several decisions over its lifecycle; a refused relief is a decision on
one component, never a rejection of the whole application. `final_status` comes from the last decisive event (permit
issued, completion certificate, cancellation), not from the first refusal.

ApplicationVersionComparator compares an original, corrected and approved version on the attributes each version
actually evidences. A geometric change is only stated when both versions carry geometry; otherwise the change is
NOT_VERIFIED. The approved version is validation evidence and never replaces the original submission.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

DECISION_TYPES = ("APPLICATION_APPROVED", "APPLICATION_APPROVED_WITH_CONDITIONS", "APPLICATION_REJECTED",
                  "RELIEF_REJECTED", "RETURNED_FOR_CORRECTIONS", "APPLICATION_WITHDRAWN", "APPLICATION_CANCELLED",
                  "APPLICATION_PENDING")

RELIEF_REFUSAL = re.compile(r"(?:לסרב|לדחות|דחיית|לא לאשר)\s+(?:את\s+)?(?:ה?בקשה\s+)?(?:ל)?ה?הקל[הות]")
APP_REFUSAL = re.compile(r"החלטה לסרב|החלטה לדחות(?! את הדיון)|לסרב לבקשה|דחיית בקשה")
CONDITIONS = re.compile(r"בתנאים|בכפוף ל|מסמיכה את הדרג המקצועי.*תנאים")
COMPONENT_WORDS = {"covered_parking": r"חני", "storage": r"מחסן", "fence": r"גדר|חומ", "basement": r"מרתף",
                   "pergola": r"פרגול|מצלל", "building_lines": r"קו(?:וי)? בנ", "height": r"גוב|הגבה", "use": r"שימוש חורג"}


@dataclass
class Decision:
    type: str
    date: str | None
    meeting: str | None = None
    application_version: str | None = None
    rejected_component: str | None = None
    regulatory_reference: str | None = None
    reason: str | None = None
    required_correction: str | None = None
    subsequent_decision: str | None = None

    def __post_init__(self):
        if self.type not in DECISION_TYPES:
            raise ValueError(self.type)


@dataclass
class Lifecycle:
    application_id: str
    decisions: list[Decision]
    final_status: str                             # PERMIT_ISSUED | COMPLETION_CERTIFICATE | REJECTED | CANCELLED | PENDING

    def as_dict(self) -> dict:
        return {"application_id": self.application_id, "final_status": self.final_status,
                "decisions": [asdict(d) for d in self.decisions]}


def _component(text: str) -> str | None:
    hits = [k for k, rx in COMPONENT_WORDS.items() if re.search(rx, text)]
    if "covered_parking" in hits and "height" in hits:
        return "covered_parking.height"
    return hits[0] if hits else None


def classify_decision_text(text: str) -> str:
    t = re.sub(r"\s+", " ", text)
    if RELIEF_REFUSAL.search(t):
        return "RELIEF_REJECTED"
    if APP_REFUSAL.search(t):
        return "APPLICATION_REJECTED"
    if re.search(r"החלטה לאשר|לאשר את הבקשה|אושרה", t):
        return "APPLICATION_APPROVED_WITH_CONDITIONS" if CONDITIONS.search(t) else "APPLICATION_APPROVED"
    return "APPLICATION_PENDING"


def build_lifecycle(application_id: str, process_history: list[dict], decision_texts: list[dict]) -> Lifecycle:
    """process_history: [{description, date}] (register process steps, newest first or any order);
    decision_texts: [{date, meeting, text, reference?}] (committee decisions)."""
    ev = []
    for d in decision_texts:
        typ = classify_decision_text(d["text"])
        ref = re.search(r"\b\d{3}-\d{7}\b|\b\d+/\d+/\d+/\d+\b", d["text"])
        ev.append(Decision(typ, d.get("date"), d.get("meeting"), d.get("version"),
                           _component(d["text"]) if typ == "RELIEF_REJECTED" else None,
                           d.get("reference") or (ref.group(0) if ref else None), d["text"][:300]))
    steps = sorted(process_history, key=lambda s: _key(s.get("date")))
    for s in steps:
        desc = s.get("description", "")
        if re.search(r"הוחזר לעורך|אי עמידה בתנאים", desc):
            ev.append(Decision("RETURNED_FOR_CORRECTIONS", s.get("date"), reason=desc))
        elif re.search(r"הפקת היתר", desc):
            ev.append(Decision("APPLICATION_APPROVED", s.get("date"), reason=desc))
        elif re.search(r"בוטל|ביטול הבקשה|סגירת תיק", desc):
            ev.append(Decision("APPLICATION_CANCELLED", s.get("date"), reason=desc))
        elif re.search(r"משיכת|נמשכה", desc):
            ev.append(Decision("APPLICATION_WITHDRAWN", s.get("date"), reason=desc))
        elif re.search(r"^החלטה לסרב", desc) and not any(e.type in ("RELIEF_REJECTED", "APPLICATION_REJECTED")
                                                          and e.date == s.get("date") for e in ev):
            ev.append(Decision("APPLICATION_REJECTED", s.get("date"), reason=desc))
    ev.sort(key=lambda e: _key(e.date))
    for a, b in zip(ev, ev[1:]):
        a.subsequent_decision = b.type
    descs = " ".join(s.get("description", "") for s in process_history)
    final = ("COMPLETION_CERTIFICATE" if "תעודת גמר" in descs
             else "PERMIT_ISSUED" if "הפקת היתר" in descs
             else "CANCELLED" if any(e.type == "APPLICATION_CANCELLED" for e in ev)
             else "REJECTED" if ev and ev[-1].type == "APPLICATION_REJECTED" else "PENDING")
    return Lifecycle(application_id, ev, final)


def _key(d: str | None) -> tuple:
    try:
        dd, mm, yy = (d or "").split("/")
        return int(yy), int(mm), int(dd)
    except ValueError:
        return (0, 0, 0)


# ------------------------------------------------------------------ versions

@dataclass
class ApplicationVersion:
    label: str                                    # original | corrected | approved
    source: str                                   # where the facts come from
    areas: dict = field(default_factory=dict)     # category -> m²
    components: dict = field(default_factory=dict)  # "covered_parking.inner_height_m" -> value
    reliefs: list | None = None                   # None: this version's reliefs are not evidenced
    building_lines: dict = field(default_factory=dict)
    parking: dict = field(default_factory=dict)
    documents: list = field(default_factory=list)
    declarations: dict = field(default_factory=dict)
    geometry_available: bool = False              # drawings with readable geometry for this version
    evidence: dict = field(default_factory=dict)  # attribute -> evidence source


@dataclass
class VersionChange:
    attribute: str
    before: object
    after: object
    status: str                                   # CHANGED | UNCHANGED | NOT_VERIFIED
    evidence: str
    related_to_decision: bool


class ApplicationVersionComparator:
    def compare(self, a: ApplicationVersion, b: ApplicationVersion, decisions: list[Decision] = ()) -> list[VersionChange]:
        out = []
        rejected = {d.rejected_component for d in decisions if d.rejected_component}
        for group in ("areas", "components", "building_lines", "parking", "declarations"):
            da, db = getattr(a, group), getattr(b, group)
            for k in sorted(set(da) | set(db)):
                attr = f"{group}.{k}"
                rel = any(r and (r.split(".")[0] in k or k.split(".")[0] in r) for r in rejected)
                geom = group in ("components", "building_lines")
                if k not in db or k not in da:
                    why = (f"{b.label}: not evidenced" if k not in db else f"{a.label}: not evidenced")
                    if geom and not (a.geometry_available and b.geometry_available):
                        why += " — no geometry for both versions; the change is not inferred"
                    out.append(VersionChange(attr, da.get(k), db.get(k), "NOT_VERIFIED", why, rel))
                    continue
                same = da[k] == db[k] if not isinstance(da[k], (int, float)) else abs(da[k] - db[k]) < 0.005
                ev = f"{a.evidence.get(k, a.source)} → {b.evidence.get(k, b.source)}"
                out.append(VersionChange(attr, da[k], db[k], "UNCHANGED" if same else "CHANGED", ev, rel and not same))
        if a.reliefs is None or b.reliefs is None:
            for x in sorted(set(a.reliefs or []) | set(b.reliefs or [])):
                out.append(VersionChange(f"reliefs.{x}", None if a.reliefs is None else x in a.reliefs,
                                         None if b.reliefs is None else x in b.reliefs, "NOT_VERIFIED",
                                         "the relief list of one version is not evidenced", True))
            return out
        ra, rb = set(a.reliefs), set(b.reliefs)
        for x in sorted(ra | rb):
            out.append(VersionChange(f"reliefs.{x}", x in ra, x in rb,
                                     "CHANGED" if (x in ra) != (x in rb) else "UNCHANGED", f"{a.source} → {b.source}",
                                     any(r and r.split(".")[0] in x for r in rejected)))
        return out
