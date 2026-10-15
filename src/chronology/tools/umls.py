"""UMLS API search. Sends only the clinical phrase; key from ``UMLS_API_KEY``."""

from __future__ import annotations


def umls_search(phrase: str, max_results: int = 10) -> list[dict]:
    raise NotImplementedError
