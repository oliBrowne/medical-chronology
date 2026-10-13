"""Cross-document problem flags, in plain code (no model).

E.g. date conflicts between documents, treatment gaps, duplicate pages.
"""

from __future__ import annotations

from chronology.schemas import ChronologyEvent


def run_checks(events: list[ChronologyEvent]) -> list[dict]:
    raise NotImplementedError
