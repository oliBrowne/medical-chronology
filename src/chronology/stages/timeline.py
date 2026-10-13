"""Step 4: findings -> ordered ``ChronologyEvent`` rows.

Dates come from ``tools.dates``. Sort by clinically relevant event date
(never file dates). Keep partial and unknown dates visible instead of
guessing, merge repeated statements of the same fact while keeping every
source, and flag contradictions instead of picking a winner.
"""

from __future__ import annotations

from chronology.schemas import ChronologyEvent, Finding


def build_timeline(findings: list[Finding]) -> list[ChronologyEvent]:
    raise NotImplementedError
