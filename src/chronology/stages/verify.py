"""Step 5: check every chronology row against its sources before output."""

from __future__ import annotations

from chronology.schemas import EvidenceSpan, Page


def quote_matches_page(span: EvidenceSpan, page: Page) -> bool:
    """True if the span's quote is exactly the cited slice of the cited page."""
    if (span.doc_id, span.page_index) != (page.doc_id, page.page_index):
        return False
    if not 0 <= span.char_start < span.char_end <= len(page.text):
        return False
    return page.text[span.char_start : span.char_end] == span.quote
