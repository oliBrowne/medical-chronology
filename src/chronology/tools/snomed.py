"""SNOMED CT search. The SNOMED CT concepts come from the local UMLS index
(``tools.snomed_index``), so this is ``umls_search`` under the name the term
resolver's tool list uses. Sends nothing off the machine."""

from __future__ import annotations

from chronology.tools.umls import umls_search


def snomed_search(phrase: str, max_results: int = 10, semantic_types: list[str] | None = None) -> list[dict]:
    return umls_search(phrase, max_results, semantic_types)
