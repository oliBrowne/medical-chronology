"""Step 1: PDFs -> one ``Page`` per physical page, then page triage.

- ``parse_document``: text of each page from the PDF's native text layer
  (PyMuPDF, reading order), the Bates label from the filename cross-checked
  against the stamp printed on the page, and the document segments inside the
  file (``chronology.segment``). Pages with no usable text are kept, with
  empty text: triage reads them in full and flags them for OCR, which is not
  built yet.
- ``parse_markdown``: the sample cases, which are parsed-Markdown productions
  with ``{n}-----`` page breaks (used by ``chronology.pipeline``).
- ``triage_case``: runs ``chronology.triage.triage_pages`` over every page of
  every file and writes each page's type and route back onto the ``Page``.
  Jev's starts / continues answers then refine the segments.
- ``audit_rows`` / ``write_audit``: one row per page explaining what triage
  did and why. Rows never contain page text, only a hash of it, so the log can
  be shared for review without sharing the record.

Every page stays searchable whatever its route; triage only decides how much
reading it gets.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Iterable

from chronology import bates, segment, triage
from chronology.schemas import Page, SourceDocument

_PAGE_BREAK = re.compile(r"\n\{\d+\}-+\n")  # marker-style break between pages
_STAMP = re.compile(r"([A-Za-z][A-Za-z.]*)\s(\d{4,})")  # e.g. "BELL 000101"
MIN_TEXT_CHARS = 20   # below this a page has no usable text layer (image-only scan)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_document(pdf_path: Path, case_root: Path | None = None) -> tuple[SourceDocument, list[Page]]:
    """Read one PDF into a ``SourceDocument`` and its ``Page`` list."""
    import pymupdf as fitz  # pip install -e ".[pdf]"

    pdf_path = Path(pdf_path)
    sha = _sha256_file(pdf_path)
    rng = bates.parse_filename(pdf_path.name)
    # an id without the file name, which can carry the patient's name
    doc_id = f"{rng.prefix}{rng.start:0{rng.width}d}" if rng else f"doc-{sha[:12]}"
    pages: list[Page] = []
    with fitz.open(pdf_path) as pdf:
        for i, pg in enumerate(pdf):
            text = pg.get_text("text")
            if len(text.strip()) < MIN_TEXT_CHARS:
                text = ""
            label = None
            if rng:
                expected = rng.start + i
                stamped = bates.find_stamps(text, rng.prefix)
                # the printed stamp wins when it is the only one and disagrees
                number = stamped[0] if len(stamped) == 1 and stamped[0] != expected else expected
                label = f"{rng.prefix} {number:0{rng.width}d}"
            pages.append(Page(doc_id=doc_id, page_index=i, bates_label=label, text=text,
                              text_source="native"))
        page_count = len(pdf)
    rel = str(pdf_path.relative_to(case_root)) if case_root else pdf_path.name
    doc = SourceDocument(doc_id=doc_id, path=rel, sha256=sha, page_count=page_count,
                         bates_prefix=rng.prefix if rng else None,
                         bates_start=rng.start if rng else None, bates_end=rng.end if rng else None)
    for p, seg in zip(pages, segment.segment_ids(segment.code_boundaries([p.text for p in pages]))):
        p.segment = seg
    return doc, pages


def page_id(page: Page) -> str:
    return page.bates_label or f"{page.doc_id}#p{page.page_index + 1}"


def triage_case(pages: list[Page], ask: Callable[[str, dict], dict], pool_map=map,
                **settings) -> list[triage.PageResult]:
    """Triage every page (all files of a case) and write the result onto each
    ``Page``. Files are triage's documents; code segments inside a file are
    refined with Jev's starts / continues answers afterwards."""
    by_id = {page_id(p): p for p in pages}
    if len(by_id) != len(pages):
        raise ValueError("two pages share a Bates label; fix the production before triage")
    rows = [{"id": pid, "doc": p.doc_id, "seq": p.page_index + 1, "text": p.text} for pid, p in by_id.items()]
    results = triage.triage_pages(rows, ask, pool_map=pool_map, **settings)
    res_by_id = {r.id: r for r in results}
    for pid, p in by_id.items():
        r = res_by_id[pid]
        p.page_type = r.decision.page_type
        p.triage_route = r.decision.route
        p.duplicate_of = r.decision.duplicate_of
    # refine segments per file with Jev's position answers
    files: dict[str, list[Page]] = {}
    for p in pages:
        files.setdefault(p.doc_id, []).append(p)
    for file_pages in files.values():
        file_pages.sort(key=lambda p: p.page_index)
        bounds = segment.code_boundaries([p.text for p in file_pages])
        answers = [(res_by_id[page_id(p)].position, res_by_id[page_id(p)].position_prob) for p in file_pages]
        for p, seg in zip(file_pages, segment.segment_ids(segment.refine_with_jev(bounds, answers))):
            p.segment = seg
    return results


def audit_rows(pages: Iterable[Page], results: Iterable[triage.PageResult]) -> list[dict]:
    """One row per page: what triage did and why. Never the page text."""
    res = {r.id: r for r in results}
    out = []
    for p in pages:
        r = res[page_id(p)]
        d = r.decision
        out.append({
            "page_id": page_id(p), "doc_id": p.doc_id, "page_index": p.page_index,
            "bates_label": p.bates_label, "segment": p.segment, "text_sha256": text_sha256(p.text),
            "chars": len(p.text), "route": d.route, "reason": d.reason, "page_type": d.page_type,
            "type_prob": d.type_prob, "type_source": d.type_source, "clinical": d.clinical,
            "clinical_prob": d.clinical_prob, "clinical_kind": r.clinical_kind, "position": r.position,
            "position_prob": r.position_prob, "duplicate_of": d.duplicate_of, "confirmed": r.confirmed,
            "chars_to_agent": r.chars_to_agent, "model": r.model, "jev_calls": r.calls, "error": r.error,
        })
    return out


def write_audit(path: Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


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
