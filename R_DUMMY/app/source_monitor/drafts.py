"""Candidate rule clauses in an official source document (deterministic, no AI).

A candidate is a sentence that states a measurable limit (number + unit + normative wording), a
document that must be attached to a request, or a prohibition. Each keeps the page and the exact page
text, so a rule author can verify it against the PDF. Section numbers in these PDFs are displaced by the
right-to-left layout, so the section shown is the nearest number and is marked as approximate.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..intake.text import fix_line_punct

HEB = "֐-׿"
UNITS = [
    ('מ"ר', re.compile(r'מ\s*["״]\s*ר(?![' + HEB + '])|מטר(?:ים)?\s+רבוע')),
    ('ס"מ', re.compile(r'ס\s*["״]\s*מ(?![' + HEB + '])|סנטימטר')),
    ("%", re.compile(r"%|אחוז")),
    ("קומות", re.compile(r"(?<![" + HEB + r"])קומות(?![" + HEB + "])")),
    ("מ'", re.compile(r"(?<![" + HEB + r"])מ['׳](?![" + HEB + r"])|(?<![" + HEB + r"])מטר(?:ים)?(?![" + HEB + "])")),
]
OPS = [
    (">=", re.compile(r"לא\s+[יית]?[יית]?פחת|לפחות|מינימ|לא\s+פחות")),
    ("<=", re.compile(r"לא\s+[יית]?[יית]?עלה|לא\s+יותר\s+מ[\s\-–]*\d|מקסימ|מירבי|מרבי|לכל\s+היותר|עד\s+\d|עד\s+ל")),
]
NORMATIVE = re.compile(r"יהי[הו]|תהי(?:ה|ינה)|יתוכננ?ו?|ייבנו|יבנו|תיבנה|ייבנה|לא\s+[יית]|לפחות|מינימ|מקסימ|מירבי|מרבי|"
                       r"בגובה|ברוחב|במרחק|בנסיגה|בעומק|עד\s")
DOCS = re.compile(r"יצורפ(?:ו)?|יצורף|תצורף|יש\s+לצרף|לצרף\s+לבקשה|תכלול|יכלול|יוגש(?:ו)?|תוגש|יש\s+להגיש|יסומנו|יסומן")
PROHIBIT = re.compile(r"לא\s+(?:יותר|תותר|יותרו|תותרנה)(?!\s+מ[\s\-–]*\d)|אסור|חל\s+איסור|לא\s+תהי(?:ה|ינה)|לא\s+יהי[הו]|אין\s+ל")
TOPICS = {
    "מרפסת": "מרפס", "סוכה": "סוכ", "חדר גג": "גג", "פרגולה": "פרגול", "מעקה": "מעקה", "חזית": "חזית",
    "קו בניין": "קו\\s*בנין|קו\\s*בניין|מרווח|נסיגה", "גובה": "גובה", "חניה": "חני", "מיגון": 'ממ"ד|מקלט|מרחב\\s*מוגן',
    "שטח": 'שטח|מ"ר', "גדר": "גדר", "מסמכים": "יצורפ|לצרף|תכלול|יוגש",
}
TOPICS_RE = {k: re.compile(v) for k, v in TOPICS.items()}

SECTION_LINE = re.compile(r"^\.?\s*(\d{1,2}(?:\.\d{1,2}){0,2})\s*\.?$")
TRAILING_SECTION = re.compile(r"(?<![\d.])(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)[\s.]*$")
NUMBER = re.compile(r"(?<![\d/.])\d+(?:[.,]\d+)?(?![\d/])")


@dataclass
class Draft:
    page: int
    section: str | None
    kind: str                       # numeric_limit | required_document | prohibition
    text_he: str
    values: list[dict] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        norm = re.sub(r"[\s\W_]+", "", self.text_he)
        return hashlib.sha1(f"{self.kind}|{norm}".encode()).hexdigest()[:20]


def _lines(text: str) -> list[str]:
    out = []
    for i, raw in enumerate(text.splitlines()):
        s = re.sub(r"\s+", " ", raw).strip()
        if not s or (i < 3 and re.fullmatch(r"\d{1,3}", s)):     # page number at the top
            continue
        out.append(fix_line_punct(s))
    return out


def _segments(text: str) -> list[tuple[str, str | None]]:
    """(sentence, approximate section) pairs for one page."""
    major: int | None = None
    pieces: list[tuple[str, str | None]] = []           # (text, marker-or-None)
    for ln in _lines(text):
        m = SECTION_LINE.match(ln)
        if m:
            num = m.group(1)
            if "." not in num:
                major = int(num)
            else:
                major = int(num.split(".")[0])
            pieces.append(("", num))
            continue
        t = TRAILING_SECTION.search(ln)
        # a number at the end of a line is a section only under a known heading (else it may be a measure: "1.05")
        if (t and major is not None and int(t.group(1).split(".")[0]) in (major, major + 1)
                and not re.search(r"\d\s*$", ln[: t.start()])):
            num = t.group(1)
            major = int(num.split(".")[0])
            pieces.append((ln[: t.start()].strip(), num))
            continue
        pieces.append((ln, None))
    # join into running text, remembering where markers sit
    text_parts, markers, pos = [], [], 0
    for chunk, marker in pieces:
        if marker:
            markers.append((pos, marker))
        if chunk:
            text_parts.append(chunk)
            pos += len(chunk) + 1
    joined = " ".join(text_parts)
    out = []
    start = 0
    for m in re.finditer(r"(?<!\d)[.!?](?!\d)|$", joined):
        end = m.end()
        sent = joined[start:end].strip(" .")
        if sent:
            near = [mk for p, mk in markers if start - 2 <= p <= end + 2]
            sec = next((mk for mk in near if "." in mk), near[0] if near else None)   # sub-section over heading
            if sec is None:
                prev = [mk for p, mk in markers if p < start]
                sec = prev[-1] if prev else None
            out.append((sent, sec))
        start = end
        if m.group(0) == "":
            break
    return out


def _values(sent: str) -> list[dict]:
    units = [(u, mm.start()) for u, rx in UNITS for mm in rx.finditer(sent)]
    if not units:
        return []
    ops = [(o, mm.start()) for o, rx in OPS for mm in rx.finditer(sent)]
    vals = []
    for mm in NUMBER.finditer(sent):
        before = sent[max(0, mm.start() - 8): mm.start()]
        if re.search(r"תיקון\s*$|תמ\"?א\s*$|סעיף\s*$|תקנה\s*$", before):
            continue
        n = float(mm.group(0).replace(",", "."))
        if 1900 <= n <= 2100 and "." not in mm.group(0):          # a year, not a measure
            continue
        unit = min(units, key=lambda u: abs(u[1] - mm.start()))[0]
        op = min(ops, key=lambda o: abs(o[1] - mm.start()))[0] if ops else None
        vals.append({"value": n, "unit": unit, "op": op})
        if len(vals) >= 4:
            break
    return vals


def find_drafts(pages: list[str], limit: int = 300) -> list[Draft]:
    out: list[Draft] = []
    seen: set[str] = set()
    for pno, text in enumerate(pages, start=1):
        for sent, sec in _segments(text):
            if len(sent) < 15:
                continue
            quote = sent if len(sent) <= 600 else sent[:600] + "…"
            vals = _values(sent)
            if vals and NORMATIVE.search(sent):
                kind = "numeric_limit"
            elif DOCS.search(sent):
                kind, vals = "required_document", []
            elif PROHIBIT.search(sent):
                kind, vals = "prohibition", []
            else:
                continue
            d = Draft(pno, sec, kind, quote, vals, [k for k, rx in TOPICS_RE.items() if rx.search(sent)])
            if d.key in seen:
                continue
            seen.add(d.key)
            out.append(d)
            if len(out) >= limit:
                return out
    return out
