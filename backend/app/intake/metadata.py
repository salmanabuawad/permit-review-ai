"""Metadata index files (index.csv / index.json / index.html / request lists in Excel).

They describe documents — they never become applications themselves. Rows are used to match
documents to application numbers (by file name, folder or number), to fill gaps and to cross-check
extracted values, and to record the page range in the original protocol.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from openpyxl import load_workbook

COLS = {
    "application_number": [r"מס(?:פר|['׳])?\s*(?:ה)?בקשה", r"request.?(?:id|number)", r"case.?number"],
    "file": [r"(?<![֐-׿])קובץ", r"^file", r"filename"],
    "folder": [r"תיקי(?:י)?ה", r"folder"],
    "address": [r"כתובת", r"address"],
    "gush": [r"^גוש", r"gush", r"block"],
    "helka": [r"^חלקה", r"helka", r"parcel"],
    "building_file_number": [r"תיק\s*בניין", r"building.?file"],
    "item_number": [r"^סעיף", r"item"],
    "page_start": [r"עמוד\s*התחלה", r"page.?start"],
    "page_end": [r"עמוד\s*סיום", r"page.?end"],
    "title": [r"נושא", r"title"],
    "permit_type": [r"סוג\s*(?:ה)?בקשה", r"permit.?type"],
    "applicable_plans": [r"תכני(?:ת|ות)", r"plans?"],
    "decision_excerpt": [r"נוסח\s*ההחלטה|החלטה"],
}


@dataclass
class IndexRow:
    source: str
    row: int
    values: dict = field(default_factory=dict)

    def get(self, k, default=None):
        return self.values.get(k, default)


def _map_header(header: list) -> dict[str, int]:
    cols: dict[str, int] = {}
    for j, cell in enumerate(header):
        if cell is None:
            continue
        name = str(cell).strip().lstrip("﻿")
        for key, pats in COLS.items():
            if key not in cols and any(re.search(p, name, re.I) for p in pats):
                cols[key] = j
                break
    return cols


def _norm(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def _rows_from_table(source: str, rows: list[list]) -> tuple[list[str], list[IndexRow]]:
    for hi, header in enumerate(rows[:10]):
        cols = _map_header(header)
        if "application_number" in cols:
            out = []
            for ri, row in enumerate(rows[hi + 1:], start=hi + 2):
                vals = {k: _norm(row[j]) for k, j in cols.items() if j < len(row)}
                vals = {k: v for k, v in vals.items() if v is not None}
                if vals:
                    out.append(IndexRow(source, ri, vals))
            return [str(c) for c in header], out
    return [str(c) for c in (rows[0] if rows else [])], []


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._in = [], None, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in, self._cell = True, []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._in = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in:
            self._cell.append(data)


def read_table(name: str, data: bytes) -> list[list]:
    lower = name.lower()
    if lower.endswith(".csv"):
        return [r for r in csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace")))]
    if lower.endswith(".json"):
        obj = json.loads(data.decode("utf-8-sig", errors="replace"))
        items = obj if isinstance(obj, list) else next((v for v in obj.values() if isinstance(v, list)), [])
        items = [x for x in items if isinstance(x, dict)]
        if not items:
            return []
        keys = list(dict.fromkeys(k for x in items for k in x))
        return [keys] + [[x.get(k) for k in keys] for x in items]
    if lower.endswith((".html", ".htm")):
        p = _TableParser()
        p.feed(data.decode("utf-8", errors="replace"))
        return p.rows
    if lower.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()
    return []


def parse_index(name: str, data: bytes) -> tuple[list[str], list[IndexRow]]:
    try:
        return _rows_from_table(name, read_table(name, data))
    except Exception:  # noqa: BLE001 — malformed index: caller reports it, other files continue
        return [], []


TITLES = {"הרב", "השר", "רבי", "ר", "הגאון", "הרבי", "רחוב", "רח"}


def same_address(a: str | None, b: str | None) -> bool:
    """Order/format-insensitive address comparison: 'מימון, הרב 42' == 'הרב מימון 42',
    'לנד או חיים השר 5' == 'השר חיים לנדאו 5' (titles dropped, letters compared as a multiset)."""
    def norm(s):
        words = [w for w in re.split(r"[\s,]+", s or "") if w and w.strip("'\"") not in TITLES]
        return sorted("".join(words).replace("'", "").replace('"', ""))
    return bool(a and b) and norm(a) == norm(b)


def index_address(v: str | None) -> str | None:
    if not v:
        return None
    return re.sub(r",?\s*בני\s*ברק\s*$", "", v).strip() or None
