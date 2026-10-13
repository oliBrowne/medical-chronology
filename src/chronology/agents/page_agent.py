"""PageAgent: reads one assigned page and returns findings with span offsets.

It may only point at text; ``tools.quotes`` copies the quote from the page.
"""

from __future__ import annotations

from chronology.schemas import EvidenceSpan, Finding, Page

MAX_STEPS = 8
TOOLS = ["get_page_text", "find_quote", "parse_date", "lookup_abbreviation"]
SYSTEM_PROMPT = """TODO"""


def run(page: Page, client, registry) -> tuple[list[EvidenceSpan], list[Finding]]:
    raise NotImplementedError
