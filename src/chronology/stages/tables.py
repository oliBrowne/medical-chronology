"""Markdown tables, handled in code.

Rows of a vital-signs table become findings directly. The quote is the row
exactly as printed (``| BP | 136/84 |``), so the model never has to copy table
syntax; when it did, it kept rewriting the row as ``BP 136/84``, which is not
on the page, and the page was rejected. Other tables are left to the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from chronology.schemas import EvidenceSpan, Finding, Page

_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")


@dataclass(frozen=True)
class TableRow:
    cells: tuple[str, ...]
    text: str  # the row exactly as printed, without surrounding whitespace
    start: int  # character offsets of ``text`` in the page
    end: int


@dataclass(frozen=True)
class Table:
    header: tuple[str, ...]  # empty if the table has no header row
    rows: tuple[TableRow, ...]  # data rows only


def _cells(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def find_tables(text: str) -> list[Table]:
    """Every run of consecutive ``|...|`` lines, split into header and data rows."""
    lines: list[tuple[str, int, int]] = []
    position = 0
    for raw in text.split("\n"):
        start = position + (len(raw) - len(raw.lstrip()))
        stripped = raw.strip()
        lines.append((stripped, start, start + len(stripped)))
        position += len(raw) + 1

    tables: list[Table] = []
    group: list[tuple[str, int, int]] = []
    for line in lines + [("", 0, 0)]:  # the sentinel closes a table at the end of the text
        if line[0].startswith("|") and line[0].endswith("|"):
            group.append(line)
            continue
        if group:
            has_header = len(group) >= 2 and _SEPARATOR.match(group[1][0]) is not None
            body = group[2:] if has_header else group
            rows = tuple(TableRow(_cells(t), t, s, e) for t, s, e in body if not _SEPARATOR.match(t))
            tables.append(Table(_cells(group[0][0]) if has_header else (), rows))
            group = []
    return tables


def vital_table_rows(text: str) -> list[TableRow]:
    """Data rows of every table whose first header cell starts with "Vital"."""
    return [row for table in find_tables(text)
            if table.header and table.header[0].lower().startswith("vital")
            for row in table.rows]


def vital_findings(page: Page, event_date: str | None,
                   document_date: str | None) -> tuple[list[EvidenceSpan], list[Finding]]:
    """One ``vital`` finding per vital-signs row, with the row as its quote."""
    prefix = f"{page.doc_id}:p{page.page_index}"
    spans: list[EvidenceSpan] = []
    findings: list[Finding] = []
    for n, row in enumerate(vital_table_rows(page.text)):
        span = EvidenceSpan(span_id=f"{prefix}:ts{n}", doc_id=page.doc_id,
                            page_index=page.page_index, bates_label=page.bates_label,
                            char_start=row.start, char_end=row.end, quote=page.text[row.start:row.end])
        spans.append(span)
        findings.append(Finding(finding_id=f"{prefix}:tf{n}", span_ids=[span.span_id],
                                category="vital", original_phrase=span.quote,
                                assertion="present", subject="patient", body_site=None,
                                event_date=event_date, document_date=document_date))
    return spans, findings
