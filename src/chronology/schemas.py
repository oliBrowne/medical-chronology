"""Data contract shared by every pipeline stage.

The rule the whole project hangs on: what the record *says* (an EvidenceSpan,
copied verbatim from a page) is stored separately from what the system
*thinks* it means (a Finding, a ConceptMapping, a ChronologyEvent). Every
interpretation points back to the spans that support it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceDocument(BaseModel):
    doc_id: str
    path: str  # relative to the case folder; never commit the file itself
    sha256: str
    page_count: int
    bates_prefix: str | None = None
    bates_start: int | None = None
    bates_end: int | None = None
    doc_type: str | None = None  # e.g. "medical records", "billing", "crash report"


class Page(BaseModel):
    doc_id: str
    page_index: int = Field(ge=0, description="0-based physical page in the PDF")
    bates_label: str | None = None  # e.g. "DOE 000018"; stays None if unstamped
    text: str
    text_source: Literal["native", "ocr"]
    ocr_confidence: float | None = None
    page_type: str | None = None  # set by triage, e.g. "consult note", "billing"
    # set by triage: "skip" | "reader" | "full" | "full_new" | "duplicate" | "billing"
    triage_route: str | None = None
    duplicate_of: str | None = None  # page id of the first copy
    segment: int = 0  # which document inside the PDF (merged productions hold many)


class EvidenceSpan(BaseModel):
    """An exact slice of a page's text. ``quote == page.text[char_start:char_end]``."""

    span_id: str
    doc_id: str
    page_index: int
    bates_label: str | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    quote: str


class Finding(BaseModel):
    finding_id: str
    span_ids: list[str] = Field(min_length=1)
    category: str  # e.g. "symptom", "diagnosis", "procedure", "medication", "imaging"
    original_phrase: str
    assertion: Literal["present", "absent", "possible", "historical"]
    subject: Literal["patient", "other"] = "patient"
    body_site: str | None = None
    event_date: str | None = None  # ISO 8601, may be partial: "2024-02", "2024"
    document_date: str | None = None  # when the note was written, kept separate


class ConceptMapping(BaseModel):
    finding_id: str
    status: Literal["mapped", "needs_review", "unmapped"]
    cui: str | None = None  # UMLS concept ID
    source_vocab: str | None = None  # e.g. "SNOMEDCT_US"
    source_code: str | None = None
    umls_release: str | None = None  # e.g. "2026AA"
    candidates: list[str] = Field(default_factory=list)
    iterations: int = 0
    rationale: str | None = None


class ChronologyEvent(BaseModel):
    event_id: str
    date: str | None = None  # ISO 8601, may be partial
    date_precision: Literal["day", "month", "year", "unknown"] = "unknown"
    finding_ids: list[str] = Field(min_length=1)
    conflicts: list[str] = Field(default_factory=list)  # finding_ids that disagree
    review_status: Literal["pending", "approved", "rejected"] = "pending"
