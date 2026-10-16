"""Lookups into the committed, PHI-free ``knowledge/`` folder."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"


@cache
def _load(name: str) -> dict:
    return json.loads((KNOWLEDGE_DIR / name).read_text())


def lookup_abbreviation(abbr: str) -> list[str]:
    """Possible expansions for an abbreviation; empty if unknown."""
    entry = _load("abbreviations.json").get("entries", {}).get(abbr)
    return list(entry["expansions"]) if entry else []


def injury_profile(region: str) -> dict:
    return json.loads((KNOWLEDGE_DIR / "injury_profiles" / f"{region}.json").read_text())
