"""UMLS / SNOMED CT search. Local index first; the UMLS web API only if asked.

The default is the local index (``tools.snomed_index``): no phrase leaves the
machine. The web API is a development fallback, used only when there is no
local index AND ``UMLS_WEB_FALLBACK=yes`` is set; it sends the phrase (never
page text or identifiers) with the key from ``UMLS_API_KEY``.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from functools import cache
from pathlib import Path

from chronology.tools.snomed_index import SAB, SnomedIndex, default_index_path

UTS_SEARCH = "https://uts-ws.nlm.nih.gov/rest/search/current"


@cache
def _index(path: str | None) -> SnomedIndex | None:
    found = Path(path) if path else default_index_path()
    return SnomedIndex(found) if found else None


def umls_search(phrase: str, max_results: int = 10, semantic_types: list[str] | None = None,
                index_path: str | None = None) -> list[dict]:
    """Candidate SNOMED CT concepts for one clinical phrase, best first.

    Each candidate has cui, code, name, preferred_name, tag, semantic_types,
    match, score and release. ``index_path`` (or ``SNOMED_INDEX``) picks an
    index file; otherwise the newest under ``data/umls/`` is used.
    """
    index = _index(index_path or os.environ.get("SNOMED_INDEX"))
    if index is not None:
        return [c.to_dict() for c in index.search(phrase, max_results, semantic_types)]
    if os.environ.get("UMLS_WEB_FALLBACK", "").lower() == "yes":
        return _web_search(phrase, max_results)
    raise FileNotFoundError(
        "no local SNOMED index: build one with scripts/umls/build_snomed_index.py "
        "(or set UMLS_WEB_FALLBACK=yes to use the UMLS web API during development)")


def _env_value(name: str, env_file: Path = Path(".env")) -> str:
    """A setting from the environment, falling back to a .env file."""
    if os.environ.get(name):
        return os.environ[name]
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip().strip('"').strip("'")
    raise SystemExit(f"{name} is not set. Add it to .env (see .env.example).")


def _web_search(phrase: str, max_results: int) -> list[dict]:
    """UMLS web API search limited to SNOMED CT. Development only."""
    key = _env_value("UMLS_API_KEY")
    query = urllib.parse.urlencode({"string": phrase, "sabs": SAB, "returnIdType": "code",
                                    "pageSize": max_results, "apiKey": key})
    with urllib.request.urlopen(f"{UTS_SEARCH}?{query}", timeout=30) as response:
        results = json.load(response)["result"]["results"]
    return [{"cui": None, "code": r["ui"], "name": r["name"], "preferred_name": r["name"],
             "tag": None, "semantic_types": [], "match": "web", "score": None,
             "release": "current (web API)"}
            for r in results if r.get("ui") not in (None, "NONE")][:max_results]
