"""Regulatory hierarchy, Hebrew terminology and clause extraction (Permit360 1.4).

* Hierarchy: IL (national) → district → planning committee → local authority (a tenant of the system). Built from the
  national committee register; idempotent. Retrieval for an authority covers its own chain only — local knowledge of
  one committee never answers for another. Scopes are retrieval boundaries, not legal precedence.
* Terminology: surface forms per concept (synonyms, spellings, abbreviations). Used to expand queries and to tag
  clause topics. Different concepts stay different (internal vs external height, main vs service area).
* Clauses: a source page is cut along its legal numbering (1. / 1.1 / א. / (א) / סעיף 12); each clause keeps the
  original wording, its offsets in the page, its parent and depth. A page without numbering is one clause.
  Everything stays UNVERIFIED until a professional confirms it.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (CommitteeDocument, CommitteePassage, CommitteeSnapshot, Jurisdiction, Municipality,
                     PlanningCommittee, RegulatoryClause, Term)

NATIONAL = "IL"

# concept → (display label, forms). Forms are matched on whole words after normalisation.
TERMS: dict[str, tuple[str, list[str]]] = {
    "parking": ("חניה", ["חניה", "חנייה", "חניות", "חניית", "מקום חניה", "מקומות חניה", "חניון"]),
    "covered_parking": ("חניה מקורה", ["חניה מקורה", "חנייה מקורה", "סככת חניה"]),
    "building_line": ("קו בניין", ["קו בניין", "קו בנין", "קווי בניין", "קווי בנין", "נסיגה", "מרווח", "מרווחים"]),
    "main_area": ("שטח עיקרי", ["שטח עיקרי", "שטחים עיקריים", "שטחי עיקרי"]),
    "service_area": ("שטח שירות", ["שטח שירות", "שטחי שירות"]),
    "coverage": ("תכסית", ["תכסית", "תכסית קרקע", "כיסוי קרקע"]),
    "permeable_area": ("שטח חלחול", ["שטח חלחול", "שטחי חלחול", "שטח מחלחל", "חלחול"]),
    "pergola": ("פרגולה", ["פרגולה", "פרגולות", "מצללה", "מצללות"]),
    "storage": ("מחסן", ["מחסן", "מחסנים", "מחסן ביתי"]),
    "basement": ("מרתף", ["מרתף", "מרתפים", "קומת מרתף", "קומות מרתף"]),
    "internal_height": ("גובה פנימי", ["גובה פנימי", "גובה נטו", "גובה הקומה הפנימי"]),
    "external_height": ("גובה הבניין", ["גובה הבניין", "גובה בניין", "גובה המבנה", "גובה מבנה", "גובה חיצוני", "גובה מרבי"]),
    "determining_entrance": ("כניסה קובעת", ["כניסה קובעת", "מפלס הכניסה הקובעת", "מפלס כניסה קובעת"]),
    "occupied_floor": ("קומה מאוכלסת", ["קומה מאוכלסת", "קומות מאוכלסות"]),
    "relief": ("הקלה", ["הקלה", "הקלות", "בקשה להקלה"]),
    "nonconforming_use": ("שימוש חורג", ["שימוש חורג", "שימושים חורגים"]),
    "building_rights": ("זכויות בנייה", ["זכויות בנייה", "זכויות בניה", "זכויות הבנייה", "זכויות הבניה"]),
    "roof_room": ("חדר על הגג", ["חדר על הגג", "חדרי גג", "חדר יציאה לגג", "בנייה על הגג", "בניה על הגג"]),
    "balcony": ("מרפסת", ["מרפסת", "מרפסות", "מרפסת זיזית", "מרפסות זיזיות"]),
    "fence": ("גדר", ["גדר", "גדרות", "גדר בנויה"]),
    "tree": ("עצים", ["עץ בוגר", "עצים בוגרים", "כריתת עצים", "פקיד היערות"]),
    "shelter": ("מרחב מוגן", ["ממ\"ד", "ממד", "מרחב מוגן", "מקלט"]),
    "pool": ("בריכת שחייה", ["בריכה", "בריכת שחייה", "בריכות שחייה"]),
    "unit_split": ("פיצול יחידות", ["פיצול יחידות", "פיצול יחידת דיור", "פיצול דירה"]),
    "permit_info": ("תיק מידע", ["תיק מידע", "מידע להיתר", "מידע תכנוני"]),
}
DISTINCT = [("internal_height", "external_height"), ("main_area", "service_area"), ("parking", "covered_parking")]

CLAUSE_HEAD = re.compile(
    r"(?m)^[ \t]*(?:(?:סעיף|ס['׳]?)\s*)?"
    r"(?P<num>\d{1,3}(?:\.\d{1,3}){0,4}|[א-ת](?=[.)])|\((?:[א-ת]|\d{1,2})\))"
    r"[.)]?[ \t]+(?=\S)")


def norm(text: str) -> str:
    t = re.sub(r"[\"״׳'`]", "", text or "")
    t = re.sub(r"[^\w\s.]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_FORM_RX: dict[str, re.Pattern] = {}


def _form_rx(form: str) -> re.Pattern:
    """A term form as a pattern: whole words, each allowing up to two Hebrew prefix letters (ו ה ב ל מ ש כ)."""
    rx = _FORM_RX.get(form)
    if rx is None:
        words = norm(form).split()
        rx = re.compile(r"(?<![\w])" + r"\s+".join(r"[והבלמשכ]{0,2}" + re.escape(w) for w in words) + r"(?![\w])")
        _FORM_RX[form] = rx
    return rx


# ------------------------------------------------------------------ terminology

def seed_terms(s: Session) -> int:
    have = {(t.concept, t.term) for t in s.scalars(select(Term))}
    n = 0
    for concept, (label, forms) in TERMS.items():
        for i, f in enumerate(forms):
            if (concept, f) not in have:
                s.add(Term(concept=concept, term=f, label_he=label if i == 0 else None, created_by="system"))
                n += 1
    s.flush()
    return n


def term_index(s: Session) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for t in s.scalars(select(Term)):
        out.setdefault(t.concept, []).append(t.term)
    return out


def topics_of(text: str, index: dict[str, list[str]]) -> list[str]:
    t = norm(text)
    return sorted(c for c, forms in index.items() if any(_form_rx(f).search(t) for f in forms))


def expand(query: str, index: dict[str, list[str]]) -> list[str]:
    """The query plus every form of each concept it names (distinct concepts are not merged)."""
    forms = [query]
    for c in topics_of(query, index):
        forms += [f for f in index[c] if f not in forms]
    return forms


# ------------------------------------------------------------------ hierarchy

def build(s: Session) -> dict:
    """Create / refresh the hierarchy from the committee register and the authorities of the system."""
    have = {j.id: j for j in s.scalars(select(Jurisdiction))}

    def put(jid, kind, name, parent, **kw):
        j = have.get(jid)
        if j is None:
            j = Jurisdiction(id=jid, kind=kind, name_he=name, parent_id=parent, **kw)
            s.add(j)
            have[jid] = j
        else:
            j.kind, j.name_he, j.parent_id = kind, name, parent
            for k, v in kw.items():
                setattr(j, k, v)
        return j

    put(NATIONAL, "NATIONAL", "ישראל — דין ארצי", None)
    s.flush()
    for c in s.scalars(select(PlanningCommittee)):
        put(f"district:{c.district}", "DISTRICT", f"מחוז {c.district}", NATIONAL)
    s.flush()
    for c in s.scalars(select(PlanningCommittee)):
        put(f"committee:{c.id}", "PLANNING_COMMITTEE", c.name_he, f"district:{c.district}", committee_id=c.id)
    s.flush()
    for m in s.scalars(select(Municipality).where(Municipality.is_demo.is_(False))):
        parent = f"committee:{m.committee_id}" if m.committee_id else NATIONAL
        put(f"authority:{m.id}", "LOCAL_AUTHORITY", m.name_he, parent, municipality_id=m.id)
    seed_terms(s)
    s.flush()
    return {k: v for k, v in s.execute(select(Jurisdiction.kind, func.count()).group_by(Jurisdiction.kind)).all()}


def chain(s: Session, tenant: str) -> list[str]:
    """The authority's jurisdictions from itself up to national (what its retrieval may see)."""
    out, jid = [], f"authority:{tenant}"
    j = s.get(Jurisdiction, jid)
    if j is None:
        return [NATIONAL]
    while j is not None:
        out.append(j.id)
        j = s.get(Jurisdiction, j.parent_id) if j.parent_id else None
    return out


# ------------------------------------------------------------------ clauses

def split_clauses(text: str) -> list[dict]:
    """[{number, depth, start, end, parent}] along the legal numbering of a page (parent = index in the list)."""
    heads = [(m.start(), m.group("num")) for m in CLAUSE_HEAD.finditer(text or "")]
    if not heads:
        return [{"number": None, "depth": 0, "start": 0, "end": len(text or ""), "parent": None}] if (text or "").strip() else []
    out: list[dict] = []
    if heads[0][0] > 0 and text[:heads[0][0]].strip():
        out.append({"number": None, "depth": 0, "start": 0, "end": heads[0][0], "parent": None})
    stack: list[tuple[int, int]] = []            # (depth, index in out)
    for k, (pos, num) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(text)
        if num[0].isdigit():
            depth = num.count(".") + 1
        elif num.startswith("("):
            depth = (stack[-1][0] + 1) if stack else 2
        else:                                    # Hebrew letter: under the last numeric clause
            numeric = [d for d, _ in stack if d <= 5]
            depth = (max(numeric) + 1) if numeric else 1
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1] if stack else None
        out.append({"number": num.strip("()"), "depth": depth, "start": pos, "end": end, "parent": parent})
        stack.append((depth, len(out) - 1))
    return out


def _served():
    from .models import Municipality
    return select(Municipality.committee_id).where(Municipality.committee_id.is_not(None))


def extract_clauses(s: Session, limit: int = 300) -> int:
    """Cut clauses for current committee passages that have none yet. Returns clauses added."""
    index = term_index(s)
    done = select(RegulatoryClause.passage_id)
    q = (select(CommitteePassage, CommitteeDocument.committee_id)
         .join(CommitteeSnapshot, CommitteePassage.snapshot_id == CommitteeSnapshot.id)
         .join(CommitteeDocument, CommitteeSnapshot.document_id == CommitteeDocument.id)
         .where(CommitteeDocument.sha256 == CommitteeSnapshot.sha256, CommitteePassage.id.not_in(done))
         .order_by(CommitteeDocument.committee_id.not_in(_served()), CommitteePassage.id).limit(limit))
    n = 0
    for p, committee_id in s.execute(q).all():
        jid = f"committee:{committee_id}" if committee_id else NATIONAL          # uploaded national knowledge
        if s.get(Jurisdiction, jid) is None:
            continue
        rows: list[RegulatoryClause] = []
        for c in split_clauses(p.text_he):
            body = p.text_he[c["start"]:c["end"]].strip()
            if not body:
                rows.append(None)
                continue
            parent = rows[c["parent"]] if c["parent"] is not None and c["parent"] < len(rows) else None
            r = RegulatoryClause(jurisdiction_id=jid, passage_id=p.id, number=c["number"], depth=c["depth"],
                                 start=c["start"], end=c["end"], text_he=body[:20000], topics=topics_of(body, index),
                                 parent_id=None, verification="UNVERIFIED")
            s.add(r)
            s.flush()
            if parent is not None:
                r.parent_id = parent.id
            rows.append(r)
            n += 1
        if not rows:                              # mark the passage as processed (an empty page)
            s.add(RegulatoryClause(jurisdiction_id=jid, passage_id=p.id, number=None, depth=0, start=0, end=0,
                                   text_he="", topics=[], verification="EMPTY"))
    s.commit()
    return n


def search(s: Session, tenant: str, query: str, limit: int = 30) -> dict:
    """Clauses in the authority's own chain whose text has the query or a synonym of a concept it names."""
    index = term_index(s)
    forms = expand(query.strip(), index)
    scope = chain(s, tenant)
    from sqlalchemy import or_
    q = (select(RegulatoryClause, Jurisdiction.name_he, Jurisdiction.kind)
         .join(Jurisdiction, RegulatoryClause.jurisdiction_id == Jurisdiction.id)
         .where(RegulatoryClause.jurisdiction_id.in_(scope), RegulatoryClause.verification != "EMPTY",
                or_(*[RegulatoryClause.text_he.contains(f, autoescape=True) for f in forms])).limit(limit))
    out = []
    for c, jname, kind in s.execute(q):
        out.append({"id": c.id, "jurisdiction": jname, "level": kind, "number": c.number, "depth": c.depth,
                    "text_he": c.text_he[:1200], "topics": c.topics, "passage_id": c.passage_id,
                    "verification": c.verification})
    return {"scope": scope, "expanded": forms, "concepts": topics_of(query, index), "clauses": out}
