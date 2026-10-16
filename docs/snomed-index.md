# Local SNOMED CT index

Normalization (step 3) maps each finding's phrase to a SNOMED CT concept. It
looks phrases up in a SQLite index built once from a UMLS release, not in the
UMLS web API:

- **No phrase leaves your machine.** Real record phrases are only ever
  searched locally.
- **No rate limits**, and a search takes milliseconds.
- **Reproducible.** Every result names the UMLS release it came from, so a
  run can be repeated against the same terminology.

The UMLS web API stays as an opt-in fallback for development on made-up
phrases.

## Build it (once per person)

The UMLS licence is per person, so each team member downloads the release
and builds their own index. The index is licensed content: it lives under
`data/` (gitignored) and must never be committed.

1. Get a UMLS licence and sign in at https://uts.nlm.nih.gov/ (approval can
   take a few days).
2. Download the **UMLS Metathesaurus Full Subset** for the current release
   (for example 2026AA) and unzip it. You need its `META` folder with
   `MRCONSO.RRF`, `MRSTY.RRF` and `MRSAB.RRF`.
3. Build:

```bash
python -m chronology.tools.snomed_index build path/to/2026AA/META
```

This keeps the English, non-suppressed `SNOMEDCT_US` names (preferred terms,
fully specified names, synonyms) and their UMLS semantic types, and writes
`data/umls/snomed.sqlite`. On a large synthetic file of 1.2 million SNOMED
terms the build took 21 seconds; the real release is a few times larger.

4. Check it:

```bash
python -m chronology.tools.snomed_index info
```

```bash
python -m chronology.tools.snomed_index search "neck pain"
```

Set `SNOMED_INDEX` to use an index somewhere else.

## Use it

```python
from chronology.tools.snomed import snomed_search

snomed_search("neck pain", max_results=5, category="symptom")
```

Each result has `code` (SNOMED CT id), `cui` (UMLS concept), `name` (SNOMED
preferred term), `matched` (the term that matched), `tag` (SNOMED semantic
tag such as `finding` or `disorder`), `semantic_types` (UMLS), `match`
(`exact`, `all_words` or `any_word`), `score`, `release` and `source`
(`local` or `web`).

`category` is a page-agent finding category. It drops candidates of the
wrong kind, for example a disorder for a symptom
(`SEMANTIC_TYPES_BY_CATEGORY` in `tools/snomed.py`).

Search is lexical and deterministic: an exact match on the normalized term
first, then all words matching (SQLite full-text search with stemming,
ranked by BM25), then any word. Choosing among the candidates, checking the
quote supports the choice, and rephrasing are later steps (Jev and the
TermResolver loop).

## Web fallback (development only)

If no index exists, `snomed_search` can use the UMLS web API instead, but only
with an explicit opt-in, because it sends the phrase to NLM:

```
UMLS_WEB_FALLBACK=1
UMLS_API_KEY=<your own key>
```

Use it with made-up phrases only. Web results have no semantic types or tags,
so `category` filtering does not apply.

## Tests

`tests/tools/test_snomed_index.py` builds an index from
`tests/fixtures/umls_mini/`, a tiny UMLS release in the real file format with
made-up identifiers (no licensed content).
