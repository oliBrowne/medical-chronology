"""SNOMED CT search via a Snowstorm server. Sends only the clinical phrase."""

from __future__ import annotations


def snomed_search(phrase: str, max_results: int = 10) -> list[dict]:
    raise NotImplementedError
