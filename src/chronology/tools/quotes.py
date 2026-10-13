"""Exact-quote checks. Quotes are copied from the page, never typed by a model."""

from __future__ import annotations

from chronology.schemas import EvidenceSpan, Page


def quote_matches_page(span: EvidenceSpan, page: Page) -> bool:
    """True if the span's quote is exactly the cited slice of the cited page."""
    if (span.doc_id, span.page_index) != (page.doc_id, page.page_index):
        return False
    if not 0 <= span.char_start < span.char_end <= len(page.text):
        return False
    return page.text[span.char_start : span.char_end] == span.quote


def find_quote(page: Page, quote: str) -> list[tuple[int, int]]:
    """All (char_start, char_end) offsets where ``quote`` occurs exactly on the page."""
    if not quote:
        return []
    hits, start = [], page.text.find(quote)
    while start != -1:
        hits.append((start, start + len(quote)))
        start = page.text.find(quote, start + 1)
    return hits
