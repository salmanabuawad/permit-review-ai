"""Area table (טבלת שטחים / "רובוט שטחים") extraction from Excel.

The exact official template of the area table has not been verified, so header matching
is synonym-based and configurable. Rows that cannot be classified are reported, not guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

HEADER_SYNONYMS = {
    "item":     [r"תיאור", r"שימוש", r"מפלס|קומה", r"item"],
    "status":   [r"קיים.?/.?מוצע", r"מצב", r"status"],
    "main_m2":  [r"עיקרי", r"main"],
    "service_m2": [r"שירות", r"service"],
    "total_m2": [r"סה.?כ", r"total"],
}
STATUS_MAP = {"קיים": "existing", "מוצע": "proposed", "existing": "existing", "proposed": "proposed"}


@dataclass
class AreaRow:
    sheet: str
    row: int
    item: str
    status: str | None
    main_m2: float | None
    service_m2: float | None
    total_m2: float | None


@dataclass
class ExcelResult:
    status: str
    rows: list[AreaRow] = field(default_factory=list)
    totals: dict[str, float] = field(default_factory=dict)
    header_map: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> dict:
        return {"status": self.status, "row_count": len(self.rows), "totals_m2": self.totals,
                "header_map": self.header_map, "warnings": self.warnings,
                "rows": [r.__dict__ for r in self.rows]}


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_area_table(path: Path) -> ExcelResult:
    try:
        wb = load_workbook(str(path), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        return ExcelResult(status="ERROR", warnings=[f"Excel open error: {exc}"])
    res = ExcelResult(status="OK")
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        header_idx, cols = None, {}
        for i, row in enumerate(rows[:15]):
            found = {}
            for j, cell in enumerate(row):
                if cell is None:
                    continue
                for key, pats in HEADER_SYNONYMS.items():
                    if key not in found and any(re.search(p, str(cell), re.IGNORECASE) for p in pats):
                        found[key] = j
                        break
            if "main_m2" in found or "total_m2" in found:
                header_idx, cols = i, found
                res.header_map = {k: str(row[v]) for k, v in found.items()}
                break
        if header_idx is None:
            continue
        for k, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
            get = lambda key: row[cols[key]] if key in cols and cols[key] < len(row) else None  # noqa: E731
            item = get("item")
            if item is None and all(get(c) is None for c in ("main_m2", "service_m2", "total_m2")):
                continue
            raw_status = str(get("status") or "").strip()
            status = STATUS_MAP.get(raw_status)
            ar = AreaRow(ws.title, k, str(item or ""), status, _num(get("main_m2")),
                         _num(get("service_m2")), _num(get("total_m2")))
            if re.search(r"סה.?כ|total", ar.item, re.IGNORECASE):
                continue   # skip subtotal rows; totals recomputed below
            if status is None:
                res.warnings.append(f"{ws.title}!{k}: status (existing/proposed) not recognised: '{raw_status}'")
            res.rows.append(ar)
    if not res.rows:
        res.status = "NO_AREA_TABLE"
        res.warnings.append("No area table header recognised.")
    for st in ("existing", "proposed"):
        main = sum(r.main_m2 or 0 for r in res.rows if r.status == st)
        serv = sum(r.service_m2 or 0 for r in res.rows if r.status == st)
        res.totals[f"{st}_main_m2"] = round(main, 3)
        res.totals[f"{st}_service_m2"] = round(serv, 3)
    return res
