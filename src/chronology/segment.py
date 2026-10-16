"""Find the documents inside one PDF.

Productions often merge many documents (an ED visit, a bill, a records
certification) into one PDF. Triage reuses answers within a document and
tells Jev "page 3 of 5"; the chronology groups facts by document. Both need
to know where each document starts.

Two sources, combined:

- Code, before any model call (``code_boundaries``): a page counter that
  restarts ("Page 1 of 3"), or a new title line that differs from the
  previous page's. A page whose counter says "Page 2 of 3", or whose first
  line reads like running text, continues the document before it.
- Jev's answer to the starts / continues question, asked during triage at no
  extra cost (``refine_with_jev``). It can only add a start where code found
  none (a title-less first page). It never removes one: on the synthetic case
  Jev answered a confident "continues" for new documents such as a phone note,
  a legal letter or discharge instructions (it sees only the glance, not the
  previous page), which cut recall from 0.94 to 0.86 when it could overrule
  code.

A page counter, when present, beats everything else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_COUNTER = re.compile(r"\bpage\s+(\d{1,4})\s*(?:of|/)\s*(\d{1,4})\b", re.IGNORECASE)
_BATES_OR_STAMP = re.compile(r"^\W*(?:[A-Z]{2,10}[-_ ]?\d{4,9}|page\s+\d+(?:\s*(?:of|/)\s*\d+)?|\d+)\W*$",
                             re.IGNORECASE)
_FAX_LINE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}.*\b(?:from|fax|p\.?\s?\d)", re.IGNORECASE)
_TITLE_WORDS = re.compile(
    r"\b(?:report|record|note|notes|summary|statement|invoice|claim|form|letter|certificat\w*|"
    r"authorization|request|subpoena|evaluation|consult\w*|instructions|history|list|results?|"
    r"flowsheet|ledger|explanation of benefits|cover|transmittal|index|affidavit|prescription|"
    r"emergency department|operative|procedure|radiology|laboratory|discharge)\b", re.IGNORECASE)
# Headings inside a document, not titles of a new one.
_SECTION = re.compile(r"^\W*(?:impression|findings|assessment|plan|hospital course|history|exam|"
                      r"subjective|objective|medications?|allergies|diagnos[ie]s|results?|addendum)\b\W*:?",
                      re.IGNORECASE)
_CONTINUED = re.compile(r"\(?\bcont(?:inued|'d|\.)\)?", re.IGNORECASE)
_LETTER = re.compile(r"^\s*(?:re|dear|to whom|subject)\b", re.IGNORECASE)
TITLE_LINES = 3   # a letterhead or clinic name can sit above the title
CONFIDENT = 0.90


@dataclass
class PageSignals:
    counter: tuple[int, int] | None   # (k, n) from "Page k of n"
    first_line: str                   # first line with words, stamps and fax lines skipped
    title: str | None                 # first title-like line among the first few
    continued: bool = False           # the title says "(continued)"
    letter: bool = False              # opens like a letter ("Re:", "Dear ...")

    @property
    def runs_on(self) -> bool:
        """The page opens mid-text: lower-case start, or a line that only
        continues a sentence."""
        s = self.first_line.lstrip()
        return bool(s) and (s[0].islower() or s[0] in ",;)")


def _norm(line: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", re.sub(r"\d+", " ", line.lower())).split())


def _looks_like_title(line: str) -> bool:
    if _SECTION.match(line):
        return False
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 3:
        return False
    upper = sum(c.isupper() for c in letters) / len(letters)
    return upper >= 0.6 or bool(_TITLE_WORDS.search(line) and len(line.split()) <= 10)


def signals(text: str) -> PageSignals:
    counter = None
    m = _COUNTER.search(text)
    if m:
        counter = (int(m.group(1)), int(m.group(2)))
    lines = [x.strip() for x in text.split("\n")
             if x.strip() and not _BATES_OR_STAMP.match(x) and not _FAX_LINE.match(x)]
    first = lines[0] if lines else ""
    head = lines[:TITLE_LINES]
    title = next((x for x in head if _looks_like_title(x)), None)
    continued = bool(title and _CONTINUED.search(title))
    letter = any(_LETTER.match(x) for x in lines[:TITLE_LINES + 1])
    return PageSignals(counter, first, title, continued, letter)


@dataclass
class Boundary:
    starts: bool
    source: str      # "first page" | "counter" | "title" | "runs on" | "no title" | "jev"
    sure: bool       # a page counter, or the first page: Jev cannot overrule it


def code_boundaries(texts: list[str]) -> list[Boundary]:
    """Does each page start a document? From code signals only."""
    out: list[Boundary] = []
    prev: PageSignals | None = None
    for i, text in enumerate(texts):
        sig = signals(text)
        if i == 0:
            out.append(Boundary(True, "first page", True))
        elif sig.counter:
            k, n = sig.counter
            prev_n = prev.counter[1] if prev and prev.counter else None
            if k == 1:
                out.append(Boundary(True, "counter", True))
            elif prev_n == n and prev.counter[0] == k - 1:
                out.append(Boundary(False, "counter", True))
            else:   # a counter that does not follow on: decide from the title
                new_title = bool(sig.title) and not sig.runs_on and not sig.continued and (
                    prev is None or _norm(sig.title) != _norm(prev.title or prev.first_line))
                out.append(Boundary(new_title, "title", False))
        elif sig.runs_on or sig.continued or _SECTION.match(sig.first_line):
            out.append(Boundary(False, "runs on", False))
        elif sig.title and (prev is None or _norm(sig.title) != _norm(prev.title or prev.first_line)):
            out.append(Boundary(True, "title", False))
        elif sig.letter:
            out.append(Boundary(True, "letter", False))
        else:
            out.append(Boundary(False, "no title", False))
        prev = sig
    return out


def refine_with_jev(bounds: list[Boundary], answers: list[tuple[str | None, float | None]]) -> list[Boundary]:
    """Add a document start where code found none and Jev confidently says
    the page starts one. ``answers`` is (position, probability) per page,
    None where Jev was not asked (reused or duplicate pages). Code's starts,
    and anything a page counter decided, are kept as they are."""
    out = []
    for b, (pos, p) in zip(bounds, answers):
        if not b.starts and not b.sure and pos == "starts" and p is not None and p >= CONFIDENT:
            out.append(Boundary(True, "jev", False))
        else:
            out.append(b)
    return out


def segment_ids(bounds: list[Boundary]) -> list[int]:
    """0, 0, 1, 1, 1, 2 ...: the document number of each page within the file."""
    ids, current = [], -1
    for b in bounds:
        current += 1 if b.starts or current < 0 else 0
        ids.append(current)
    return ids


def boundary_scores(predicted: list[bool], truth: list[bool]) -> dict:
    """Precision and recall of document starts, ignoring the first page."""
    pairs = list(zip(predicted[1:], truth[1:]))
    tp = sum(p and t for p, t in pairs)
    fp = sum(p and not t for p, t in pairs)
    fn = sum(t and not p for p, t in pairs)
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else 1.0,
            "recall": tp / (tp + fn) if tp + fn else 1.0}
