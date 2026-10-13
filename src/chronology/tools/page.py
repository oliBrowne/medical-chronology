"""``get_page_text`` bound to one assigned page, so an agent can't read others."""

from __future__ import annotations

from typing import Callable

from chronology.schemas import Page


def bind_page_text(page: Page) -> Callable[..., dict]:
    def get_page_text(start: int = 0, end: int | None = None) -> dict:
        end = len(page.text) if end is None else end
        return {"bates_label": page.bates_label, "start": start, "end": end,
                "text": page.text[start:end]}
    return get_page_text
