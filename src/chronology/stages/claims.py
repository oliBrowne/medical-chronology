"""Claims: what the case summary says, kept separate from the evidence.

The case summary is the attorney's account, not a record. Its statements come
out of the page agent like any other page, then this module turns them into
claims:

- the type of a claim (incident fact, claimed injury, prior history, ...)
  comes from the section heading above it, chosen by code;
- rows of the treatment table and the specials table are made into claims
  directly, like vital-sign rows, so the model never has to copy table syntax;
- every claim carries two dates: ``claimed_on`` (when the summary was
  prepared) and ``about_date`` (the date the claim is about, if it has one).

Every claim starts as ``unchecked``. Comparing claims against the chronology
is a later step.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from chronology.stages.tables import find_tables
from chronology.tools.resolve_date import resolve_date

if TYPE_CHECKING:
    from chronology.agents.page_agent import PageExtraction

# (words in the section heading, claim type); the first match wins.
HEADING_TYPES = [
    ("question", "question"),
    ("outstanding", "outstanding_record"),
    ("special", "billed_amount"),
    ("billed", "billed_amount"),
    ("treatment", "claimed_treatment"),
    ("injur", "claimed_injury"),
    ("prior", "claimed_history"),
    ("history", "claimed_history"),
    ("incident", "incident_fact"),
    ("fact", "incident_fact"),
]
TYPE_ORDER = ["incident_fact", "claimed_injury", "claimed_history", "claimed_treatment",
              "billed_amount", "question", "outstanding_record", "other"]
_HEADING = re.compile(r"^#+\s*(.+?)\s*$", re.MULTILINE)
_DATE_IN_CELL = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


def heading_before(text: str, position: int) -> str | None:
    """The nearest heading above ``position``, or None."""
    found = [m.group(1) for m in _HEADING.finditer(text[:position])]
    return found[-1] if found else None


def claim_type(heading: str | None) -> str:
    lowered = (heading or "").lower()
    return next((kind for word, kind in HEADING_TYPES if word in lowered), "other")


def _table_claims(text: str) -> list[dict[str, Any]]:
    """Claims made directly from the treatment table and the specials table."""
    claims = []
    for table in find_tables(text):
        header = [h.lower() for h in table.header]
        for row in table.rows:
            if header and header[0] == "date":
                kind, dates = "claimed_treatment", _DATE_IN_CELL.findall(row.cells[0])
            elif any("billed" in h for h in header):
                kind, dates = "billed_amount", []
            else:
                continue
            first = resolve_date(dates[0]) if dates else None
            last = resolve_date(dates[1]) if len(dates) > 1 else None
            claims.append({"type": kind, "quote": row.text, "assertion": None, "body_site": None,
                           "about_date": first["iso"] if first else None,
                           "about_date_end": last["iso"] if last else None,
                           "char_start": row.start, "char_end": row.end, "flags": []})
    return claims


def build_claims(file: str, extraction: "PageExtraction") -> list[dict[str, Any]]:
    """The claims on one case-summary page, in a stable order."""
    page = extraction.page
    claimed_on = next((d["iso"] for d in extraction.dates
                       if d["role"] == "prepared_date" and d["iso"]), None)

    claims = _table_claims(page.text)
    taken = [(c["char_start"], c["char_end"]) for c in claims]

    spans = {s.span_id: s for s in extraction.spans}
    for f in extraction.findings:
        span = spans[f.span_ids[0]]
        if any(s < span.char_end and e > span.char_start for s, e in taken):
            continue  # a table row already made into a claim by code
        kind = claim_type(heading_before(page.text, span.char_start))
        claims.append({"type": kind, "quote": span.quote, "assertion": f.assertion,
                       "body_site": f.body_site,
                       "about_date": f.event_date if kind in ("incident_fact", "claimed_injury",
                                                              "claimed_treatment") else None,
                       "about_date_end": None, "char_start": span.char_start,
                       "char_end": span.char_end,
                       "flags": extraction.flags.get(f.finding_id, [])})

    claims.sort(key=lambda c: (TYPE_ORDER.index(c["type"]), c["about_date"] is None,
                               c["about_date"] or "", c["char_start"]))
    return [{"claim_id": f"c{n:04d}", **c, "claimed_on": claimed_on, "status": "unchecked",
             "source": {"file": file, "page_index": page.page_index,
                        "char_start": c["char_start"], "char_end": c["char_end"]}}
            for n, c in enumerate(claims, start=1)]


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def render_claims_markdown(case: str, claims: list[dict[str, Any]]) -> str:
    """A readable table of the claims, with both dates."""
    lines = [f"# Claims: {case}", "",
             f"{len(claims)} claims from the case summary. None has been checked against the "
             f"records yet.", "",
             "| Type | Claim | About date | Claimed on | Status | Flags |",
             "|---|---|---|---|---|---|"]
    for c in claims:
        about = c["about_date"] or ""
        if about and c["about_date_end"]:
            about += f" to {c['about_date_end']}"
        flags = ", ".join(sorted({f["rule"] for f in c["flags"]}))
        lines.append("| " + " | ".join(_cell(x) for x in (
            c["type"], c["quote"], about, c["claimed_on"] or "", c["status"], flags)) + " |")
    return "\n".join(lines) + "\n"
