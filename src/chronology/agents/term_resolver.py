"""TermResolver: maps one unclear clinical phrase to UMLS / SNOMED CT.

Checks saved resolutions first, then searches UMLS and SNOMED. Choosing among
candidates can go to Jev, with its probability as the stop rule. Only the
clinical phrase leaves the machine, never identifiers or page text.
"""

from __future__ import annotations

from chronology.schemas import ConceptMapping, Finding

MAX_STEPS = 3
TOOLS = ["memory_get", "lookup_abbreviation", "umls_search", "snomed_search"]
SYSTEM_PROMPT = """TODO"""


def run(finding: Finding, client, registry) -> ConceptMapping:
    raise NotImplementedError
