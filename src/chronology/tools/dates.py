"""Date parsing tools. Partial dates stay partial; never fall back to file dates.

Date-role labels ("Date of Service", "Printed", ...) live in
``knowledge/date_roles.json``.
"""

from __future__ import annotations


def parse_date(text: str) -> dict:
    """Return ``{"iso": "2024-02-11" | "2024-02" | None, "precision": ...}``."""
    raise NotImplementedError
