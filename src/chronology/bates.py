"""Bates numbering helpers.

Each PDF in a production is named for its Bates range, e.g.
``DOE 000018-1021 - Hospital recs.pdf``: prefix ``DOE``, first page 18, last
page 1021. The end number usually drops its leading zeros (``000001-55``), so
it is parsed as a plain integer. Most pages also carry the stamp itself
(``DOE 000018``) in their text layer; ``find_stamps`` picks those up so the
number derived from the filename can be cross-checked against the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

_FILENAME = re.compile(
    r"^(?P<prefix>[A-Za-z][A-Za-z.]*)\s+(?P<start>\d{4,})(?:-(?P<end>\d+))?(?=\s|$)"
)


@dataclass(frozen=True)
class BatesRange:
    prefix: str
    start: int
    end: int
    width: int  # zero-padded digit count used in the stamp, e.g. 6 for 000018

    @property
    def page_count(self) -> int:
        return self.end - self.start + 1

    def label(self, page_index: int) -> str:
        """Bates label for a 0-based physical page index within this file."""
        if not 0 <= page_index < self.page_count:
            raise IndexError(f"page {page_index} outside {self.prefix} {self.start}-{self.end}")
        return f"{self.prefix} {self.start + page_index:0{self.width}d}"


def parse_filename(name: str | PurePath) -> BatesRange | None:
    """Read the Bates range from a production filename, or None if it has none.

    A single-page file (``DOE 006966 - EMS form.pdf``) gets start == end.
    """
    stem = PurePath(name).stem
    m = _FILENAME.match(stem)
    if not m:
        return None
    start = int(m["start"])
    end = int(m["end"]) if m["end"] else start
    if end < start:
        raise ValueError(f"Bates range ends before it starts: {stem!r}")
    return BatesRange(prefix=m["prefix"], start=start, end=end, width=len(m["start"]))


def find_stamps(text: str, prefix: str) -> list[int]:
    """Bates numbers stamped in a page's text for the given prefix, in order."""
    pattern = re.compile(rf"\b{re.escape(prefix)}\s?(\d{{4,}})\b", re.IGNORECASE)
    return [int(n) for n in pattern.findall(text)]
