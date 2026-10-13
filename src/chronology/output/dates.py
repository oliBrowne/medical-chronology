"""Display and ordering for ISO dates that may be partial ("2024-03", "2024").

A partial date stays partial: "2024-03" displays as "Mar 2024", never as
"Mar 1, 2024", and its distance from the incident is given only as precisely
as the date allows.
"""

from __future__ import annotations

import re
from datetime import date

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_ISO = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def precision(iso: str | None) -> str:
    """"day", "month", "year", or "unknown" (missing or unreadable)."""
    m = _ISO.match(iso or "")
    if not m:
        return "unknown"
    return "day" if m[3] else "month" if m[2] else "year"


def display(iso: str | None) -> str:
    p = precision(iso)
    if p == "day":
        return iso  # type: ignore[return-value]
    if p == "month":
        y, mo = iso.split("-")  # type: ignore[union-attr]
        return f"{_MONTHS[int(mo) - 1]} {y}"
    if p == "year":
        return iso  # type: ignore[return-value]
    return "Date unknown"


def _ym(iso: str) -> tuple[int, int]:
    y, _, rest = iso.partition("-")
    return int(y), int(rest[:2]) if rest else 1


def relative(iso: str | None, index_iso: str | None) -> str:
    """Distance from the incident, no more precise than the date itself."""
    p = precision(iso)
    if p == "unknown" or precision(index_iso) != "day":
        return ""
    idx = date.fromisoformat(index_iso)  # type: ignore[arg-type]
    if p == "day":
        days = (date.fromisoformat(iso) - idx).days  # type: ignore[arg-type]
        if days == 0:
            return "day of incident"
        if days < 0:
            return f"{-days} day{'s' if days != -1 else ''} before"
        return f"+{days} day{'s' if days != 1 else ''}"
    if p == "month":
        y, m = _ym(iso)  # type: ignore[arg-type]
        diff = (y * 12 + m) - (idx.year * 12 + idx.month)
        if diff == 0:
            return "month of incident"
        n = abs(diff)
        return f"~{n} month{'s' if n != 1 else ''} {'before' if diff < 0 else 'after'}"
    diff = int(iso) - idx.year  # type: ignore[arg-type]
    if diff == 0:
        return "year of incident"
    n = abs(diff)
    return f"~{n} year{'s' if n != 1 else ''} {'before' if diff < 0 else 'after'}"


def sort_key(iso: str) -> str:
    """Plain ISO string order: "2024-03" sorts before "2024-03-01", because
    a month-only date could be any day in that month, including the first."""
    return iso
