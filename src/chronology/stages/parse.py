"""Step 1: PDFs -> one ``Page`` per physical page.

Plan:
- Use the native text layer when it's valid. Some productions print header
  text twice in layout mode, so prefer raw/reading-order extraction and spot
  check against the page image.
- OCR pages with no usable text (some files are image-only scans).
- Attach the Bates label from ``bates.parse_filename`` and cross-check it
  against ``bates.find_stamps`` on the page.
- Triage: tag each page's type (billing, MAR, flowsheet, therapy note, consult,
  discharge summary, ...) from the filename and the first lines of text, and
  mark near-duplicate pages, so later stages can skip or deprioritize them.
  Rank pages rather than dropping them; every page stays searchable.
"""

from __future__ import annotations

from pathlib import Path

from chronology.schemas import Page, SourceDocument


def parse_document(pdf_path: Path) -> tuple[SourceDocument, list[Page]]:
    raise NotImplementedError
