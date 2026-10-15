"""Exact-quote checks. Quotes are copied from the page, never typed by a model.

``find_quote`` and ``quote_matches_page`` are exact. ``find_quotes`` is the
lenient locator the page agent uses on a model's quote: runs of whitespace
(line breaks, double spaces) count as equal, and the slice taken from the page,
not the model's string, is what gets stored, so a stored quote is verbatim by
construction.
"""

from __future__ import annotations

import re

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


def find_quotes(text: str, quote: str) -> list[tuple[int, int]]:
    """Every ``(char_start, char_end)`` where ``quote`` appears in ``text``, treating
    runs of whitespace as equal."""
    tokens = quote.split()
    if not tokens:
        return []
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    return [m.span() for m in re.finditer(pattern, text)]
