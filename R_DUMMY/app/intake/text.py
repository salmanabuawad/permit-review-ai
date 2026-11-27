"""Text helpers for Hebrew municipal PDFs.

Committee protocols exported from the licensing system (Complot) have mixed-direction lines:
words are in logical order but punctuation, numbers and even label fragments move
("תיק ןי בני" for "תיק בניין", ".ראה ..." for "ראה ... ."). These helpers clean page headers,
repair line-edge punctuation, flatten pages while remembering page boundaries, and build
"tolerant" label patterns that match on letters while ignoring spaces/punctuation between them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HEB = "֐-׿"
SEP = r"[\s:'\"׳״.\-–,]*"                 # allowed between letters of a tolerant label
HEADER_END = re.compile(r'קומפלוט\s*בע"מ')
NOISE_LINE = re.compile(r"^\s*(?:BAKPIRUT\d+|TBPIRUT\d+|IB5\.7x23E|גרסה|:?מס'\s*דף\s*:?)\s*$")


_SHIFTED_HEB = re.compile(r"[\u02a0-\u02ba]")


def repair_shifted_font(text: str) -> str:
    """Some government PDFs (Rishui Zamin "מידע להיתר") use a Hebrew font whose text layer is shifted: letters come
    out as U+02A0–U+02BA (א-ת minus 0x330), punctuation as control characters (space/.:"- minus 0x1D), and each line
    is in visual order. Map the characters back and turn visual lines into logical order. Other text is untouched."""
    if len(_SHIFTED_HEB.findall(text)) < 20:
        return text
    from bidi.algorithm import get_display
    fixed = "".join(chr(ord(c) + 0x330) if 0x2A0 <= ord(c) <= 0x2BA
                    else chr(ord(c) + 0x1D) if 0x01 <= ord(c) <= 0x1F and c not in "\n\r\t" else c for c in text)
    return "\n".join(get_display(line, base_dir="R") if re.search(f"[{HEB}]", line) else line
                     for line in fixed.split("\n"))


def tol(label: str) -> str:
    """Regex matching the letters of `label` in order, tolerating separators between letters."""
    letters = [c for c in label if c.isalnum()]
    return SEP.join(re.escape(c) for c in letters)


def fix_line_punct(line: str) -> str:
    """Move a leading '.'/',' (displaced by bidi) back to the end of the line."""
    s = line.strip()
    if len(s) > 1 and s[0] in ".," and s[-1] not in ".,:;":
        s = s[1:].strip() + s[0]
    return s


def clean_page(text: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines[:15]):          # drop the repeated page header block
        if HEADER_END.search(line):
            lines = lines[i + 1:]
            break
    out = []
    for line in lines:
        if NOISE_LINE.match(line):
            continue
        s = fix_line_punct(line)
        if re.fullmatch(r"\d{1,2}", s):        # list number alone on its line ("14" + ". text" below)
            s += "."
        if s:
            out.append(s)
    return "\n".join(out)


@dataclass
class Flat:
    text: str
    spans: list[tuple[int, int, int]]               # (start, end, page_no 1-based)

    def page_at(self, pos: int) -> int | None:
        for a, b, p in self.spans:
            if a <= pos < b:
                return p
        return self.spans[-1][2] if self.spans else None


def flatten(pages: list[tuple[int, str]]) -> Flat:
    """pages: [(page_no, cleaned_text)] -> single-spaced text with page spans."""
    parts, spans, pos = [], [], 0
    for page_no, txt in pages:
        t = re.sub(r"\s+", " ", txt).strip()
        if not t:
            continue
        if parts:
            parts.append(" ")
            pos += 1
        spans.append((pos, pos + len(t), page_no))
        parts.append(t)
        pos += len(t)
    return Flat("".join(parts), spans)


def compact(s: str) -> str:
    """Letters/digits only — for keyword matching robust to split words and moved punctuation."""
    return re.sub(r"[^\w]", "", s or "")


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip(" :;,-–")
    s = re.sub(r"\s+([.,])", r"\1", s)
    return s.strip()


def split_letters_digits(s: str) -> str:
    """'ביאליק25' -> 'ביאליק 25' (numbers glued to words by the PDF export)."""
    s = re.sub(rf"([{HEB}])(\d)", r"\1 \2", s)
    return re.sub(rf"(\d)([{HEB}])", r"\1 \2", s)


def quote(flat: Flat, a: int, b: int, limit: int = 160) -> str:
    q = flat.text[a:b].strip()
    return q if len(q) <= limit else q[:limit] + "…"
