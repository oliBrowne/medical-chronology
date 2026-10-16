"""Saved term resolutions (SQLite), keyed on the clinical phrase only.

The database holds phrases taken from records, so it lives under ``runs/``
(gitignored) and must never be committed. Never store page text, names,
dates of birth or record numbers here.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_DB = Path("runs/term_memory.sqlite")


def memory_get(phrase: str) -> dict | None:
    raise NotImplementedError


def memory_put(phrase: str, cui: str, source_vocab: str, source_code: str) -> None:
    raise NotImplementedError
