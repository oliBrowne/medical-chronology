"""Step 2: pages -> ``EvidenceSpan`` + ``Finding`` records.

The model may only *point at* text (character offsets on a page); the quote is
then copied from the page by code, so it is verbatim by construction. Each
finding carries its assertion state (present / absent / possible / historical)
and keeps the event date separate from the document date.
"""

from __future__ import annotations

from chronology.schemas import EvidenceSpan, Finding, Page


def extract_findings(page: Page) -> tuple[list[EvidenceSpan], list[Finding]]:
    raise NotImplementedError
