"""SNOMED CT search for normalization, from the local index.

``snomed_search`` is the tool the TermResolver calls. It reads the local
SQLite index (``tools.snomed_index``), so nothing leaves the machine. When no
index has been built yet it falls back to the UMLS web API, but only if the
developer has opted in (see ``tools.umls``); otherwise it raises with the
command that builds the index.

The index path comes from ``SNOMED_INDEX`` and defaults to
``data/umls/snomed.sqlite``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from chronology.tools import umls
from chronology.tools.snomed_index import DEFAULT_DB, SnomedIndex

# Finding category (from the page agent) -> UMLS semantic types that fit it.
# Used to drop candidates of the wrong kind, e.g. a disorder for a symptom.
SEMANTIC_TYPES_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "symptom": ("Sign or Symptom", "Finding"),
    "exam_finding": ("Finding", "Sign or Symptom", "Pathologic Function", "Injury or Poisoning"),
    "imaging": ("Finding", "Pathologic Function", "Anatomical Abnormality", "Injury or Poisoning",
                "Disease or Syndrome", "Diagnostic Procedure"),
    "diagnosis": ("Disease or Syndrome", "Injury or Poisoning", "Pathologic Function",
                  "Anatomical Abnormality", "Mental or Behavioral Dysfunction", "Finding"),
    "procedure": ("Therapeutic or Preventive Procedure", "Diagnostic Procedure",
                  "Health Care Activity"),
    "medication": ("Pharmacologic Substance", "Clinical Drug", "Organic Chemical"),
    "history": (),   # history can be anything; no filter
}


def index_path() -> Path:
    return Path(os.environ.get("SNOMED_INDEX") or DEFAULT_DB)


@lru_cache(maxsize=4)
def _index(path: str) -> SnomedIndex:
    return SnomedIndex(Path(path))


def snomed_search(phrase: str, max_results: int = 10, category: str | None = None) -> list[dict]:
    """Candidate SNOMED CT concepts for a clinical phrase, best first.

    Each result has ``code`` (SNOMED id), ``cui``, ``name``, ``matched``,
    ``tag``, ``semantic_types``, ``match`` ("exact" / "all_words" /
    ``any_word``), ``score``, ``release`` and ``source`` ("local" or "web").
    With ``category`` (a finding category), candidates of an unfitting
    semantic type are dropped.
    """
    types = SEMANTIC_TYPES_BY_CATEGORY.get(category or "", ()) or None
    path = index_path()
    if path.exists():
        hits = _index(str(path)).search(phrase, max_results, semantic_types=types)
        return [{**h.to_dict(), "source": "local"} for h in hits]
    if umls.web_allowed():
        return [{**h, "source": "web"} for h in umls.umls_search(phrase, max_results)]
    raise FileNotFoundError(
        f"no SNOMED index at {path}. Build it once from your UMLS download "
        f"(python -m chronology.tools.snomed_index build <META folder>), or, for development "
        f"only, set UMLS_WEB_FALLBACK=1 with UMLS_API_KEY to use the UMLS web API.")
