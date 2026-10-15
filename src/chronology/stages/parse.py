"""Step 1: PDFs -> one ``Page`` per physical page.

Plan:
- Use the native text layer when it's valid. Some productions print header
  text twice in layout mode, so prefer raw/reading-order extraction and spot
  check against the page image.
- OCR pages with no usable text (some files are image-only scans).
- Attach the Bates label from ``bates.parse_filename`` and cross-check it
  against ``bates.find_stamps`` on the page.
- Triage with Jev (``llm.jev``, once zero data retention is on): tag
  each page's type (billing, MAR, flowsheet, therapy note, consult,
  discharge summary, ...) from the filename and the first lines of text, and
  mark near-duplicate pages, so later stages can skip or deprioritize them.
  Rank pages rather than dropping them; every page stays searchable.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from chronology.schemas import Page, SourceDocument

_PAGE_BREAK = re.compile(r"\n\{\d+\}-+\n")  # marker-style break between pages
_STAMP = re.compile(r"([A-Za-z][A-Za-z.]*)\s(\d{4,})")  # e.g. "BELL 000101"


def parse_document(pdf_path: Path) -> tuple[SourceDocument, list[Page]]:
    raise NotImplementedError


def parse_markdown(path: Path) -> tuple[SourceDocument, list[Page]]:
    """Split a parsed-Markdown production (the sample cases) into pages.

    Pages are separated by ``{n}-----`` lines. A page's Bates label is the
    stamp on its last non-empty line, or None if it has none.
    """
    raw = path.read_bytes()
    pages: list[Page] = []
    for index, chunk in enumerate(_PAGE_BREAK.split(raw.decode())):
        text = chunk.strip()
        if not text:
            continue
        last_line = text.splitlines()[-1].strip()
        stamp = _STAMP.fullmatch(last_line)
        pages.append(Page(doc_id=path.stem, page_index=len(pages),
                          bates_label=last_line if stamp else None,
                          text=text, text_source="native"))

    numbers = [int(_STAMP.fullmatch(p.bates_label)[2]) for p in pages if p.bates_label]
    prefixes = {_STAMP.fullmatch(p.bates_label)[1] for p in pages if p.bates_label}
    document = SourceDocument(
        doc_id=path.stem, path=path.name, sha256=hashlib.sha256(raw).hexdigest(),
        page_count=len(pages),
        bates_prefix=prefixes.pop() if len(prefixes) == 1 else None,
        bates_start=min(numbers) if numbers else None,
        bates_end=max(numbers) if numbers else None,
        doc_type="medical records")
    return document, pages
