"""Step 4: findings -> an ordered chronology.

- Sort by the clinically relevant event date (never file dates). Undated
  findings stay in the list, last, instead of being guessed or dropped.
- Merge repeated statements of the same fact (same date, text, category and
  subject) into one event that keeps every source.
- Flag contradictions instead of picking a winner: merged findings that
  disagree on the assertion are listed in ``conflicts``.

``build_timeline`` works on findings alone. ``build_chronology`` joins its
events back to their quotes, locations, provider and flags for output.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, Any

from chronology.schemas import ChronologyEvent, Finding

if TYPE_CHECKING:
    from chronology.agents.page_agent import PageExtraction


def date_precision(date: str | None) -> str:
    """"day", "month", "year" or "unknown" for an ISO date, partial or not."""
    return {10: "day", 7: "month", 4: "year"}.get(len(date), "unknown") if date else "unknown"


def _normalize(text: str) -> str:
    """Compare quotes ignoring case, Markdown markers, list numbers and trailing punctuation."""
    text = re.sub(r"[*|]", " ", text)
    text = re.sub(r"^\s*(?:[-•]|\d+\.)\s+", "", text)
    return re.sub(r"\s+", " ", text).strip().strip(".;,").lower()


def build_timeline(findings: list[Finding]) -> list[ChronologyEvent]:
    """One event per distinct fact per date, sorted by date (undated last)."""
    groups: dict[tuple, list[Finding]] = {}
    for f in findings:  # first-seen order, so ties keep page order
        key = (f.event_date, _normalize(f.original_phrase), f.category, f.subject)
        groups.setdefault(key, []).append(f)

    events: list[tuple[str | None, list[Finding], list[str]]] = []
    for (date, *_), group in groups.items():
        common = Counter(f.assertion for f in group).most_common(1)[0][0]
        conflicts = [f.finding_id for f in group if f.assertion != common] \
            if len({f.assertion for f in group}) > 1 else []
        events.append((date, group, conflicts))

    events.sort(key=lambda e: (e[0] is None, e[0] or ""))  # stable
    return [ChronologyEvent(event_id=f"ev{n:04d}", date=date, date_precision=date_precision(date),
                            finding_ids=[f.finding_id for f in group], conflicts=conflicts)
            for n, (date, group, conflicts) in enumerate(events, start=1)]


def build_chronology(pages: list[tuple[str, str, "PageExtraction"]]) -> list[dict[str, Any]]:
    """Output rows for the chronology. ``pages`` is ``(file name, role, extraction)`` in order."""
    findings: list[Finding] = []
    where: dict[str, tuple] = {}
    for file, role, extraction in pages:
        spans = {s.span_id: s for s in extraction.spans}
        for f in extraction.findings:
            findings.append(f)
            where[f.finding_id] = (file, role, extraction, spans[f.span_ids[0]])
    by_id = {f.finding_id: f for f in findings}

    rows: list[dict[str, Any]] = []
    for event in build_timeline(findings):
        group = [by_id[i] for i in event.finding_ids]
        first = group[0]
        sources, flags = [], []
        for f in group:
            file, role, extraction, span = where[f.finding_id]
            sources.append({"file": file, "role": role, "bates_label": span.bates_label,
                            "page_index": span.page_index, "char_start": span.char_start,
                            "char_end": span.char_end, "finding_id": f.finding_id,
                            "facility": extraction.facility, "provider": extraction.provider})
            flags += extraction.flags.get(f.finding_id, [])
        rows.append({"event_id": event.event_id, "date": event.date,
                     "date_precision": event.date_precision, "category": first.category,
                     "assertion": first.assertion, "subject": first.subject,
                     "body_site": first.body_site, "quote": where[first.finding_id][3].quote,
                     "flags": flags, "conflicts": event.conflicts, "sources": sources,
                     "review_status": event.review_status})
    return rows


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(case: str, rows: list[dict[str, Any]]) -> str:
    """A readable table of the chronology."""
    undated = sum(1 for r in rows if r["date"] is None)
    flagged = sum(1 for r in rows if r["flags"] or r["conflicts"])
    lines = [f"# Chronology: {case}", "",
             f"{len(rows)} events, {undated} undated, {flagged} with flags or conflicts.", "",
             "| Date | Source | Provider | Category | Finding | Assertion | Site | Flags |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        src = r["sources"][0]
        source = f"{src['file']} {src['bates_label'] or 'p' + str(src['page_index'] + 1)}"
        if len(r["sources"]) > 1:
            source += f" (+{len(r['sources']) - 1})"
        provider = " / ".join(x for x in (src["facility"], src["provider"]) if x)
        flags = sorted({f["rule"] for f in r["flags"]} | ({"conflict"} if r["conflicts"] else set()))
        date = r["date"] or "undated"
        if r["date"] and r["date_precision"] != "day":
            date += f" ({r['date_precision']})"
        lines.append("| " + " | ".join(_cell(x) for x in (
            date, source, provider, r["category"], r["quote"], r["assertion"],
            r["body_site"], ", ".join(flags))) + " |")
    return "\n".join(lines) + "\n"
