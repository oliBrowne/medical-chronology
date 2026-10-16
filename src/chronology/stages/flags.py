"""Flags: rule-based second opinions on the model's labels.

A flag never changes a finding. It marks the finding for review and says why.
The rules are crude on purpose: the model and a simple rule rarely make the
same mistake, so a disagreement points a reviewer at the findings most likely
to be wrong. Each flag is ``{"rule": ..., "detail": ...}``.

Rules:
- negation_vs_assertion: a negation word in a "present" finding, or "absent"
  with no negation word.
- laterality: the quote and the body site name different sides.
- weak_quote: a one-word quote, or a quote that occurs more than once on the
  page (so its location may be wrong).
- multi_fact: the quote may hold more than one fact.
"""

from __future__ import annotations

import re

from chronology.schemas import EvidenceSpan, Finding, Page
from chronology.tools.quotes import find_quotes

NEGATION = re.compile(r"\b(no|denies|denied|neg|negative|without|not|none|nil|absent|nkda)\b", re.IGNORECASE)
# "left"/"right" in any case; a bare L or R only in capitals and not part of "L-spine", "L4", "RTC".
_SIDE_WORD = re.compile(r"\b(left|right)\b", re.IGNORECASE)
_SIDE_LETTER = re.compile(r"(?<![\w-])([LR])(?![\w-])")


def _sides(text: str) -> set[str]:
    found = {m.group(1).lower() for m in _SIDE_WORD.finditer(text)}
    found |= {"left" if m.group(1) == "L" else "right" for m in _SIDE_LETTER.finditer(text)}
    return found


def _flag(rule: str, detail: str) -> dict[str, str]:
    return {"rule": rule, "detail": detail}


def check_finding(finding: Finding, quote: str, page_text: str) -> list[dict[str, str]]:
    """All flags for one finding. ``quote`` is the page's own text for it."""
    flags: list[dict[str, str]] = []

    cue = NEGATION.search(quote)
    if finding.assertion == "present" and cue:
        flags.append(_flag("negation_vs_assertion",
                           f"quote has '{cue.group(0)}' but the assertion is 'present'"))
    elif finding.assertion == "absent" and not cue:
        flags.append(_flag("negation_vs_assertion",
                           "assertion is 'absent' but the quote has no negation word"))

    quote_sides, site_sides = _sides(quote), _sides(finding.body_site or "")
    if quote_sides and site_sides and quote_sides.isdisjoint(site_sides):
        flags.append(_flag("laterality",
                           f"quote says {sorted(quote_sides)} but body site says {sorted(site_sides)}"))

    if len(quote.split()) < 2:
        flags.append(_flag("weak_quote", "the quote is a single word and may not stand alone"))
    occurrences = len(find_quotes(page_text, quote))
    if occurrences > 1:
        flags.append(_flag("weak_quote",
                           f"the quote appears {occurrences} times on the page; its location may be wrong"))

    if ";" in quote or re.search(r"\.\s+[A-Z]", quote) or quote.count(",") >= 2:
        flags.append(_flag("multi_fact", "the quote may hold more than one fact"))

    return flags


_BATES_LINE = re.compile(r"[A-Za-z][A-Za-z.]*\s\d{4,}")
_TABLE_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")
_BOLD_LABEL_ONLY = re.compile(r"^\*\*[^*]+\*\*$")
_SIGNATURE_LINE = re.compile(r"^(printed|electronically signed|signed|records certified)\b", re.IGNORECASE)
_HEADER_FIELD = re.compile(
    r"\*\*(Patient|Provider|MRN|DOB|Date|Visit Date|Date of Service|Exam Date|Arrival|"
    r"Referred by|Ordering|Radiologist):\*\*")


def uncovered_lines(page: Page, spans: list[EvidenceSpan], dates: list[dict] | tuple = (),
                    facility: str | None = None) -> list[dict]:
    """Lines of the page that no finding overlaps: a visible measure of what was dropped.

    Skipped as not worth reporting: blank lines, headings, table separators and
    header rows, the Bates stamp, signature/print lines, patient/provider header
    fields, the facility name, and lines that hold a date the model listed. A
    line counts as covered if any finding overlaps any part of it, so a line
    with several facts and one finding looks covered.
    """
    lines: list[tuple[str, int, int]] = []
    position = 0
    for raw in page.text.split("\n"):
        start = position + (len(raw) - len(raw.lstrip()))
        text = raw.strip()
        lines.append((text, start, start + len(text)))
        position += len(raw) + 1

    date_texts = [d["text"] for d in dates if d.get("text")]
    out: list[dict] = []
    for i, (text, start, end) in enumerate(lines):
        if (not text or text.startswith("#") or _TABLE_SEPARATOR.match(text)
                or _BATES_LINE.fullmatch(text) or _BOLD_LABEL_ONLY.match(text)
                or _SIGNATURE_LINE.match(text) or _HEADER_FIELD.search(text)
                or (facility and text == facility)):
            continue
        following = lines[i + 1][0] if i + 1 < len(lines) else ""
        if text.startswith("|") and _TABLE_SEPARATOR.match(following):
            continue  # table header row
        if any(d in text for d in date_texts):
            continue
        if any(s.char_start < end and s.char_end > start for s in spans):
            continue
        out.append({"text": text, "char_start": start, "char_end": end})
    return out


def flag_findings(findings: list[Finding], spans: list[EvidenceSpan],
                  page: Page) -> dict[str, list[dict[str, str]]]:
    """Flags for every flagged finding on a page, keyed by finding_id."""
    by_span = {s.span_id: s for s in spans}
    out: dict[str, list[dict[str, str]]] = {}
    for finding in findings:
        found = check_finding(finding, by_span[finding.span_ids[0]].quote, page.text)
        if found:
            out[finding.finding_id] = found
    return out
