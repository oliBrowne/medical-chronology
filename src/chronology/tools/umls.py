"""UMLS web API search: a development fallback for the local SNOMED index.

This sends the phrase to the National Library of Medicine, so it is off
unless a developer opts in with ``UMLS_WEB_FALLBACK=1``, and it needs the
developer's own ``UMLS_API_KEY`` (https://uts.nlm.nih.gov/; keys are per
person under the UMLS licence). Use it only with made-up phrases. Real record
phrases are looked up in the local index (``tools.snomed_index``), which
never leaves the machine.

Only the clinical phrase is sent: never page text, names, dates or record
numbers.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://uts-ws.nlm.nih.gov/rest"
SAB = "SNOMEDCT_US"


def web_allowed() -> bool:
    return os.environ.get("UMLS_WEB_FALLBACK", "").strip() in ("1", "true", "yes")


def _key() -> str:
    key = os.environ.get("UMLS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("UMLS_API_KEY is not set (each person uses their own key from uts.nlm.nih.gov)")
    return key


def _get(path: str, params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "apiKey": _key()})
    with urllib.request.urlopen(f"{API}{path}?{query}", timeout=30) as response:
        return json.load(response)


def umls_search(phrase: str, max_results: int = 10, version: str = "current") -> list[dict]:
    """SNOMED CT candidates for a phrase from the UMLS web API.

    Returns dicts shaped like the local index's results (``code``, ``cui``,
    ``name``, ``matched``, ``match``, ``release``), with ``tag`` and
    ``semantic_types`` left empty: the web search does not return them.
    """
    if not web_allowed():
        raise PermissionError("UMLS web search is off; set UMLS_WEB_FALLBACK=1 to allow it "
                              "(development only, made-up phrases only)")
    phrase = phrase.strip()
    if not phrase:
        return []
    try:
        data = _get(f"/search/{version}", {"string": phrase, "sabs": SAB, "returnIdType": "code",
                                           "searchType": "words", "pageSize": max_results})
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"UMLS API returned HTTP {err.code}") from err
    out = []
    for item in data.get("result", {}).get("results", [])[:max_results]:
        code = item.get("ui")
        if not code or code == "NONE":
            continue
        out.append({"code": code, "cui": None, "name": item.get("name", ""),
                    "matched": item.get("name", ""), "tag": None, "semantic_types": [],
                    "match": "web", "score": 0.0, "release": version})
    return out
