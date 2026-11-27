"""Grounding check: an extracted value is kept only if it can be found in the source text.

Applied to every provider's output (rules pass trivially; an LLM that "fills in" a plausible
address or number that is not in the document is caught here). Comparison is on letters/digits
only, so bidi-damaged spacing and punctuation do not cause false rejections.
"""
from __future__ import annotations

from . import text as T
from .schemas import ApplicationExtraction

SCALAR_FIELDS = ["application_number", "building_file_number", "address", "gush", "helka", "zone", "plot_area_m2",
                 "application_type", "description", "applicable_plans", "deviations"]


def is_grounded(value, haystack_compact: str) -> bool:
    if value is None:
        return True
    needle = T.compact(str(value))
    if not needle:
        return True
    if needle in haystack_compact:
        return True
    # short values whose word order changed in the mixed-direction export ("1 כתובת: רחוב הבדיקה"):
    # accept when every word occurs, all within one 60-character window of the source
    words = [T.compact(w) for w in str(value).split() if T.compact(w)]
    if 1 < len(words) <= 6 and all(w in haystack_compact for w in words):
        anchor = max(words, key=len)
        start = 0
        while (i := haystack_compact.find(anchor, start)) != -1:
            window = haystack_compact[max(0, i - 60): i + len(anchor) + 60]
            if all(w in window for w in words):
                return True
            start = i + 1
    # long free text (descriptions/comments): accept when most 12-char windows are present
    if len(needle) > 40:
        windows = [needle[i:i + 12] for i in range(0, len(needle) - 12, 12)]
        found = sum(1 for w in windows if w in haystack_compact)
        return found / max(len(windows), 1) >= 0.8
    return False


def ground(ext: ApplicationExtraction, source_text: str) -> tuple[ApplicationExtraction, list[str]]:
    hay = T.compact(source_text)
    dropped = []
    for f in SCALAR_FIELDS:
        v = getattr(ext, f)
        if v is not None and not is_grounded(v.value, hay):
            dropped.append(f)
            setattr(ext, f, None)
    kept = []
    for c in ext.comments:
        if is_grounded(c.text, hay):
            kept.append(c)
        else:
            dropped.append(f"comment:{c.department}")
    ext.comments = kept
    ext.areas = [a for a in ext.areas if T.compact(str(a.value_m2).rstrip("0").rstrip(".")) in hay or (dropped.append("area") and False)]
    if ext.decision and not is_grounded(ext.decision.text, hay):
        dropped.append("decision")
        ext.decision = None
    if dropped:
        ext.warnings.append("ערכים שלא נמצאו בטקסט המסמך הושמטו (בדיקת עיגון): " + ", ".join(dropped))
    return ext, dropped
