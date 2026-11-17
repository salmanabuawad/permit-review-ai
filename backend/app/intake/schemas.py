"""Pydantic schemas for structured extraction and validation.

Every extracted value carries a SourceRef: the file it came from, the page in that file, the
page in the original protocol when known (from the metadata index), a short exact quote, the
extraction method and a confidence. Values are never invented: a field that is not found is
simply absent (None), and AI-produced values must pass the grounding check (grounding.py).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DOC_CLASSES = {
    "permit_application": "טופס בקשה להיתר",
    "committee_protocol": "פרוטוקול ועדה",
    "planning_regulation": "מסמך תכנוני (תכנית/תקנון)",
    "architectural_drawing": "תכנית אדריכלית",
    "supporting_document": "מסמך נלווה",
    "metadata_index": "קובץ אינדקס (נתוני עזר)",
}
DocClass = Literal["permit_application", "committee_protocol", "planning_regulation", "architectural_drawing",
                   "supporting_document", "metadata_index"]

REVIEW_THRESHOLD = 0.8          # below this a value is flagged "נדרש אימות"


class SourceRef(BaseModel):
    file: str
    file_sha256: str | None = None
    page: int | None = None              # 1-based page within the file
    original_page: int | None = None     # page in the original protocol, when the index provides it
    quote: str | None = None             # exact text span (whitespace-normalised) the value was read from
    method: str
    confidence: float = Field(ge=0.0, le=1.0)
    provider: str = "local_rules"


class Extracted(BaseModel):
    value: Any
    source: SourceRef

    @property
    def needs_review(self) -> bool:
        return self.source.confidence < REVIEW_THRESHOLD


class AreaItem(BaseModel):
    floor: str | None = None
    status: Literal["existing", "proposed"] | None = None
    label: str
    value_m2: float = Field(gt=0, lt=1_000_000)
    source: SourceRef


class Comment(BaseModel):
    department: str                      # canonical key, e.g. "licensing_department"
    department_he: str
    item_no: str | None = None
    text: str
    source: SourceRef

    @field_validator("text")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("empty comment")
        return v.strip()


DecisionOutcome = Literal["approved", "approved_with_conditions", "renewed", "objection_partially_accepted",
                          "objection_rejected", "deferred", "rejected", "other"]
DECISION_OUTCOMES_HE = {
    "approved": "אושר", "approved_with_conditions": "אושר בתנאים/בהערות", "renewed": "חידוש אישור",
    "objection_partially_accepted": "התנגדות התקבלה בחלקה — אושר בתנאים", "objection_rejected": "התנגדות נדחתה — אושר",
    "deferred": "הדיון נדחה", "rejected": "נדחה", "other": "אחר — נדרש עיון",
}


class Decision(BaseModel):
    outcome: DecisionOutcome
    text: str
    conditions: list[str] = []
    meeting_number: str | None = None
    meeting_date: str | None = None      # ISO date
    item_number: str | None = None
    source: SourceRef


class ApplicationExtraction(BaseModel):
    """One permit application as found in one document (or one item of a multi-item protocol)."""
    application_number: Extracted | None = None
    building_file_number: Extracted | None = None
    address: Extracted | None = None
    gush: Extracted | None = None
    helka: Extracted | None = None
    zone: Extracted | None = None
    plot_area_m2: Extracted | None = None
    application_type: Extracted | None = None       # as written in the document, e.g. "בקשה להיתר"
    permit_type: Extracted | None = None            # system category, inferred from the description
    procedure: list[str] = []                       # renewal / re-discussion / appeal follow-up ...
    description: Extracted | None = None
    applicable_plans: Extracted | None = None
    deviations: Extracted | None = None             # הקלות שפורסמו
    areas: list[AreaItem] = []
    comments: list[Comment] = []
    decision: Decision | None = None
    item_number: str | None = None
    meeting_number: str | None = None
    meeting_date: str | None = None
    pages: list[int] = []                           # pages of the source file belonging to this item
    warnings: list[str] = []


class PlanningItem(BaseModel):
    """A plan discussion inside a committee protocol — never turned into a permit application."""
    item_number: str | None = None
    plan_number: str | None = None
    title: str | None = None
    decision_text: str | None = None
    pages: list[int] = []


class Classification(BaseModel):
    doc_class: DocClass
    confidence: float
    method: str
    signals: list[str] = []
    provider: str = "local_rules"
    model_version: str = "rules-1.0"
