"""Deterministic date resolution for medical-legal records.

The model only copies a date string exactly as printed; code turns it into a
date. The model never computes or guesses one.

Conventions:
- US records, so ``03/04/2024`` is March 4 (month first).
- A date mentioned inside a note is almost always in the past, so a date with
  no year ("3/20", "5/13") is placed in the most recent such date on or
  before the ``anchor`` (the visit / document date), never in the future.
- Output is date-only. Partial dates keep their precision as partial ISO 8601
  ("2024-06", "2024"), matching ``schemas.Finding.event_date``.
- Anything that can't be resolved comes back as ``iso: None`` plus an
  ``error``, so a caller can send it to review instead of guessing.

Which date counts as a visit's *event* date (service date vs. signature,
print or certification date) is decided by rule in ``stages/timeline.py`` from
the labels the model attaches. It is not decided here.
"""

from __future__ import annotations

import datetime
import re

from dateparser.date import DateDataParser

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b|\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2}\b")
_TIME = re.compile(r"\b(\d{1,2}):([0-5]\d)(?:\s*([ap])\.?m\b\.?)?", re.IGNORECASE)

_ISO_FORMAT = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}


def resolve_date(phrase: str, anchor: str | None = None) -> dict:
    """Resolve a date string as printed in a record.

    Args:
        phrase: Only the date text, copied exactly ("03/14/2024", "5/13",
            "June 2024", "02/11/2023 08:05"), not the whole line it came from.
        anchor: ISO date (YYYY-MM-DD) of the visit or document the phrase
            appears in. Required when the phrase has no year, and for
            relative phrases like "5 days ago".

    Returns:
        ``{"iso", "precision", "time", "phrase"}`` on success, where ``iso``
        is "YYYY-MM-DD", "YYYY-MM" or "YYYY", ``precision`` is "day" /
        "month" / "year", and ``time`` is "HH:MM" or None. On failure
        ``iso`` and ``precision`` are None and ``error`` says why.

    A duration such as "x ~5 days" is not a date. Compute it from the visit
    date with ``add_days``.
    """
    text = (phrase or "").strip()
    if not text:
        return _unresolved(phrase, "empty phrase")

    anchor_date = None
    if anchor:
        try:
            anchor_date = datetime.date.fromisoformat(anchor)
        except ValueError:
            return _unresolved(phrase, f"anchor {anchor!r} is not an ISO date (YYYY-MM-DD)")

    if not re.search(r"[A-Za-z0-9]", _TIME.sub("", text)):
        return _unresolved(phrase, "no date in the phrase, only a time")

    if anchor_date is None and not _YEAR.search(text):
        return _unresolved(phrase, "no year in the phrase and no anchor date to take it from")

    settings = {
        "DATE_ORDER": "MDY",
        "PREFER_DATES_FROM": "past",
        "PREFER_DAY_OF_MONTH": "first",
        "TIMEZONE": "UTC",
        "RETURN_AS_TIMEZONE_AWARE": False,
    }
    if anchor_date is not None:
        settings["RELATIVE_BASE"] = datetime.datetime.combine(anchor_date, datetime.time())

    data = DateDataParser(languages=["en"], settings=settings).get_date_data(text)
    if data.date_obj is None:
        return _unresolved(phrase, "could not parse as a date")
    if data.period not in _ISO_FORMAT:  # "time": a clock time with no date
        return _unresolved(phrase, "no date in the phrase")

    return {
        "iso": data.date_obj.strftime(_ISO_FORMAT[data.period]),
        "precision": data.period,
        "time": _clock_time(text),
        "phrase": phrase,
    }


def _clock_time(text: str) -> str | None:
    """"HH:MM" (24-hour) from the first clock time in ``text``, or None."""
    found = _TIME.search(text)
    if not found:
        return None
    hour, minute, meridiem = int(found[1]), found[2], (found[3] or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "p" else 0)
    elif hour > 23:
        return None
    return f"{hour:02d}:{minute}"


def _unresolved(phrase: str, reason: str) -> dict:
    return {"iso": None, "precision": None, "time": None, "phrase": phrase, "error": reason}


def days_between(start: str, end: str) -> int:
    """Whole days from ``start`` to ``end`` (both ISO days). Negative if end is earlier."""
    return (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days


def add_days(date: str, days: int) -> str:
    """ISO day ``days`` after ``date`` (negative to go back, e.g. "x ~5 days" before a visit)."""
    return (datetime.date.fromisoformat(date) + datetime.timedelta(days=days)).isoformat()


def age_at(dob: str, on: str) -> int:
    """Age in whole years on a given ISO day, to check a note's "33 y/o" against the DOB."""
    born, day = datetime.date.fromisoformat(dob), datetime.date.fromisoformat(on)
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


RESOLVE_DATE_TOOL = {
    "type": "function",
    "function": {
        "name": "resolve_date",
        "description": (
            "Convert a date string copied from a record into an ISO date. ALWAYS call "
            "this for any date; never compute, convert or guess a date yourself. Pass "
            "only the date text exactly as printed, not the surrounding sentence. "
            "Dates are US month-first. Returns iso (YYYY-MM-DD, YYYY-MM or YYYY), "
            "precision, and time if one was printed, or an error if it can't be "
            "resolved; report an error as unresolved instead of guessing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phrase": {
                    "type": "string",
                    "description": "The date text exactly as printed, e.g. '03/14/2024' or '5/13'.",
                },
                "anchor": {
                    "type": "string",
                    "description": (
                        "ISO date (YYYY-MM-DD) of the visit or document the date appears "
                        "in. Required when the date has no year."
                    ),
                },
            },
            "required": ["phrase"],
        },
    },
}
