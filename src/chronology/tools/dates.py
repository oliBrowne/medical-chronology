"""Date parsing tools. Partial dates stay partial; never fall back to file dates.

Date-role labels ("Date of Service", "Printed", ...) live in
``knowledge/date_roles.json``. The parsing itself is in ``resolve_date``;
this module is the stable entry point the rest of the code imports.
"""

from __future__ import annotations

from chronology.tools.resolve_date import add_days, age_at, days_between, resolve_date

__all__ = ["parse_date", "add_days", "age_at", "days_between"]


def parse_date(text: str, anchor: str | None = None) -> dict:
    """Return ``{"iso": "2024-02-11" | "2024-02" | None, "precision": ..., "time": ...}``.

    ``anchor`` is an ISO date (the visit or document date) that supplies a
    missing year. On failure ``iso`` is None and ``error`` says why.
    """
    return resolve_date(text, anchor)
