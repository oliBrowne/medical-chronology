"""Step 3: map each unclear phrase to UMLS / SNOMED CT via ``agents.term_resolver``.

Bounded ReAct loop per finding: propose a candidate, look it up in UMLS,
judge whether the evidence is sufficient, and if not pull more surrounding
context and try again. Stops as mapped, needs_review or unmapped, with a hard
iteration cap. Never sends patient identifiers or record narrative to the UMLS
API, only the clinical phrase. Reads the key from ``UMLS_API_KEY``.
"""

from __future__ import annotations

from chronology.schemas import ConceptMapping, Finding

MAX_ITERATIONS = 3


def map_finding(finding: Finding) -> ConceptMapping:
    raise NotImplementedError
