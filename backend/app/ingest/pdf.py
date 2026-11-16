"""PDF text + layout extraction with word bounding boxes (for citations / overlays).

Pages without a text layer are flagged NEEDS_OCR and routed to the AI gateway's OCR
task (local by default). Nothing measured from a raster page is treated as binding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf


@dataclass
class PdfPage:
    number: int                     # 1-based
    width_pt: float
    height_pt: float
    text: str
    words: list[tuple[float, float, float, float, str]]
    has_text_layer: bool
    tables: list[list[list[str | None]]] = field(default_factory=list)


@dataclass
class PdfResult:
    status: str
    page_count: int = 0
    pages: list[PdfPage] = field(default_factory=list)
    is_signed: bool = False
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> dict:
        return {
            "status": self.status, "page_count": self.page_count, "is_signed_field_present": self.is_signed,
            "pages_without_text": [p.number for p in self.pages if not p.has_text_layer],
            "tables_found": sum(len(p.tables) for p in self.pages),
            "metadata": {k: v for k, v in self.metadata.items() if v}, "warnings": self.warnings,
        }

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)


def parse_pdf(path: Path, extract_tables: bool = True) -> PdfResult:
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001
        return PdfResult(status="ERROR", warnings=[f"PDF open error: {exc}"])
    res = PdfResult(status="OK", page_count=doc.page_count, metadata=dict(doc.metadata or {}))
    try:
        res.is_signed = any(w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE
                            for page in doc for w in (page.widgets() or []))
    except Exception:  # noqa: BLE001
        res.is_signed = False
    for page in doc:
        words = [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]
        text = page.get_text("text")
        tables: list = []
        if extract_tables and words:
            try:
                tables = [t.extract() for t in page.find_tables().tables]
            except Exception:  # noqa: BLE001
                tables = []
        res.pages.append(PdfPage(page.number + 1, page.rect.width, page.rect.height, text, words,
                                 has_text_layer=bool(text.strip()), tables=tables))
    if any(not p.has_text_layer for p in res.pages):
        res.status = "NEEDS_OCR"
        res.warnings.append("Some pages have no text layer (scanned). OCR required before text checks.")
    # Signature *presence* only. Cryptographic validation needs the issuer CA chain — TODO, see backlog.
    return res


def render_page_png(path: Path, page_number: int, zoom: float = 1.5) -> bytes:
    doc = pymupdf.open(str(path))
    page = doc[page_number - 1]
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
