"""Cheap readers: ways to read a page without the (expensive) page agent.

Everything here is plain code, and every value it returns carries the
character offsets of the line it came from, so the quote is a verbatim slice
of the page, exactly as for the page agent.

- ``read_table``: billing lines, medication rows and lab rows. A page goes
  to a table reader only if every line with clinical-looking words is a row
  the reader understood; anything else on the page sends it to a full read.
- ``new_line_spans``: for copied-forward notes, the lines that did not
  appear on an earlier page, so the page agent reads only those.
- ``reader_model``: which size of model the page agent should use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from chronology.triage import clinical_keyword, norm_line

_DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b")
_ICD = re.compile(r"\b[A-TV-Z]\d{2}\.[0-9A-Z]{1,4}\b")
_CPT = re.compile(r"\b(\d{5}(?:-\d{2})?|[A-Z]\d{4})\b")
_MONEY = re.compile(r"-?\$\s?[\d,]+\.\d{2}")
_DOSE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(mg|mcg|g|ml|mL|units?|tab|caps?)\b", re.I)
_ALLERGY = re.compile(r"\ballerg\w*|\bNKDA\b|\bNKA\b", re.I)
_LAB_HINT = re.compile(r"\((?:H|L|HH|LL)\)|\bref\b|within normal limits|\bnegative\b|\bpositive\b|U/L|mg/dL|mmol/L|g/dL|K/uL", re.I)

TABLE_KINDS = {"billing": "billing", "medication_record": "medication", "lab_result": "lab"}
MIN_ROW_SHARE = 0.4   # at least this share of non-empty lines must be rows


@dataclass
class Row:
    kind: str
    char_start: int
    char_end: int
    quote: str
    date: str | None = None
    codes: list[str] = field(default_factory=list)      # CPT / HCPCS
    diagnoses: list[str] = field(default_factory=list)  # ICD-10-CM
    amount: str | None = None
    dose: str | None = None
    value: str | None = None
    flag: str | None = None


@dataclass
class TableRead:
    accepted: bool
    rows: list[Row]
    reason: str


def _lines(text: str):
    start = 0
    for line in text.split("\n"):
        yield start, start + len(line), line
        start += len(line) + 1


def _row(kind: str, s: int, e: int, line: str) -> Row | None:
    date = _DATE.search(line)
    if kind == "billing":
        icd = _ICD.findall(line)
        money = _MONEY.search(line)
        cpt = [c for c in _CPT.findall(line) if not _DATE.search(c)]
        if not (icd or money or cpt):
            return None
        return Row(kind, s, e, line, date.group(0) if date else None, cpt, icd,
                   money.group(0) if money else None)
    if kind == "medication":
        dose = _DOSE.search(line)
        if not dose:
            return None
        return Row(kind, s, e, line, date.group(0) if date else None, dose=dose.group(0))
    if kind == "lab":
        if not _LAB_HINT.search(line):
            return None
        flag = re.search(r"\((H|L|HH|LL)\)", line)
        num = re.search(r"\b\d+(?:\.\d+)?\b", line)
        return Row(kind, s, e, line, date.group(0) if date else None,
                   value=num.group(0) if num else None, flag=flag.group(1) if flag else None)
    raise ValueError(kind)


def read_table(text: str, page_type: str, ignore: set[str] | frozenset = frozenset()) -> TableRead:
    """Read a billing, medication or lab page as rows, or refuse.

    Refuses (so the page gets a full read) when the page type has no table
    reader, when too few lines are rows, or when a line that is not a row
    contains clinical-looking text the reader would otherwise drop.
    """
    kind = TABLE_KINDS.get(page_type)
    if kind is None:
        return TableRead(False, [], f"no table reader for {page_type}")
    rows, kept, leftovers, nonempty = [], [], [], 0
    for s, e, line in _lines(text):
        if not line.strip():
            continue
        if ignore and norm_line(line) in ignore and not (clinical_keyword(line) or _ALLERGY.search(line)):
            continue  # production boilerplate printed on many pages, with nothing clinical in it
        nonempty += 1
        row = _row(kind, s, e, line)
        if row:
            rows.append(row)
        elif _ALLERGY.search(line):
            kept.append(Row("allergy", s, e, line))
        elif _DATE.search(line):
            # a header or footer date ("Collected 03/14/2024", "Dates of service
            # 04/02/24 - 04/30/24"): kept, and rows without a date inherit it
            kept.append(Row("context", s, e, line, _DATE.search(line).group(0)))
        else:
            leftovers.append(line)
    if not rows or len(rows) / max(1, nonempty) < MIN_ROW_SHARE:
        return TableRead(False, rows, "too few table rows: full read")
    page_date = next((k.date for k in kept if k.kind == "context"), None)
    for row in rows:
        if row.date is None and page_date:
            row.date = page_date
    rows = sorted(rows + kept, key=lambda r: r.char_start)
    for line in leftovers:
        hit = clinical_keyword(line)
        if hit:
            return TableRead(False, rows, f"clinical text outside the table ({hit!r}): full read")
    return TableRead(True, rows, f"{len(rows)} {kind} rows")


# --- copied-forward notes --------------------------------------------------

_norm = norm_line


MIN_LINE_WORDS = 4      # shorter lines (headers, "Plan:") are always treated as new
MAX_NEW_SHARE = 0.85    # if more than this is new, read the whole page


@dataclass
class CopyForward:
    new_spans: list[tuple[int, int]]
    new_share: float
    carried_share: float

    @property
    def worth_it(self) -> bool:
        return self.new_share <= MAX_NEW_SHARE


class LineMemory:
    """Lines already read on earlier pages, for spotting copied-forward text."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def diff(self, text: str) -> CopyForward:
        spans, new_chars, total = [], 0, 0
        for s, e, line in _lines(text):
            n = _norm(line)
            if not n:
                continue
            total += e - s
            if len(n.split()) < MIN_LINE_WORDS or n not in self._seen:
                spans.append((s, e))
                new_chars += e - s
        share = new_chars / total if total else 1.0
        return CopyForward(spans, share, 1 - share)

    def add(self, text: str) -> None:
        for _, _, line in _lines(text):
            n = _norm(line)
            if len(n.split()) >= MIN_LINE_WORDS:
                self._seen.add(n)


# --- model size for the page agent -----------------------------------------

SMALL_MODEL_TYPES = frozenset({"therapy_note", "medication_record", "lab_result", "billing",
                               "patient_form", "ems_report", "imaging_report"})
SMALL_MODEL_MAX_CHARS = 1500


def reader_model(page_type: str | None, chars_to_read: int) -> str:
    """"small" for short pages of structured, formulaic types; "large" for
    narrative notes, long pages, and any page without a confident type."""
    if page_type in SMALL_MODEL_TYPES and chars_to_read <= SMALL_MODEL_MAX_CHARS:
        return "small"
    return "large"
