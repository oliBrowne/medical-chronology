"""Tools bound to one page.

The page is fixed when the tools are built, so the model can read and quote
only the page it was given. It cannot cite a different one.
"""

from __future__ import annotations

from chronology.schemas import Page
from chronology.tools.quotes import find_quotes
from chronology.tools.registry import Tool, object_schema


def page_tools(page: Page) -> list[Tool]:
    def get_page_text() -> str:
        return page.text

    def verify_quote(quote: str) -> dict:
        matches = find_quotes(page.text, quote)
        if not matches:
            return {"found": False}
        start, end = matches[0]
        return {
            "found": True,
            "char_start": start,
            "char_end": end,
            "quote": page.text[start:end],  # the page's own text, not the model's
            "occurrences": len(matches),
        }

    return [
        Tool(
            name="get_page_text",
            description="Return the full text of the page you are working on.",
            parameters=object_schema(),
            fn=get_page_text,
        ),
        Tool(
            name="verify_quote",
            description=(
                "Check that a quote appears on the page. Returns where it is and the "
                "page's exact wording. Call this on every quote before submitting."
            ),
            parameters=object_schema(
                {"quote": {"type": "string", "description": "Text copied from the page."}},
                ["quote"],
            ),
            fn=verify_quote,
        ),
    ]
