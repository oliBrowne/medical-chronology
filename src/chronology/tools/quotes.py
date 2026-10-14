"""Locate a quote on a page.

The model returns a quote; code finds where it sits. The slice taken from the
page, not the model's string, is what gets stored, so a stored quote is
verbatim by construction. Matching is exact except that runs of whitespace
(line breaks, double spaces) are treated as equal.
"""

from __future__ import annotations

import re


def find_quotes(text: str, quote: str) -> list[tuple[int, int]]:
    """Every ``(char_start, char_end)`` where ``quote`` appears in ``text``."""
    tokens = quote.split()
    if not tokens:
        return []
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    return [m.span() for m in re.finditer(pattern, text)]


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """The first match for ``quote`` in ``text``, or None."""
    matches = find_quotes(text, quote)
    return matches[0] if matches else None
