"""Merge: the evidence chronology and the claims, in one date-ordered view.

This is a third view built from the other two. The evidence-only chronology
and the claims file are written first and left unchanged, so anyone can read
just the evidence. Here the claims are placed in the timeline by the date they
are about, tagged ``claim`` next to the ``evidence`` rows, so the attorney's
account can be read against the records in date order.

The merge only combines and sorts. It does not compare a claim with the
evidence; every claim keeps its ``unchecked`` status.
"""

from __future__ import annotations

from typing import Any

from chronology.stages.timeline import date_precision


def merge_views(chronology: list[dict[str, Any]], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evidence rows and claim rows in one list, sorted by date.

    Undated rows go last. On the same date, evidence comes before claims, and
    each keeps its original order.
    """
    items: list[tuple[str | None, int, int, dict[str, Any]]] = []
    for n, row in enumerate(chronology):
        items.append((row["date"], 0, n, {**row, "kind": "evidence"}))
    for n, claim in enumerate(claims):
        source = {"file": claim["source"]["file"], "role": "claims", "bates_label": None,
                  "page_index": claim["source"]["page_index"],
                  "char_start": claim["source"]["char_start"], "char_end": claim["source"]["char_end"],
                  "facility": None, "provider": None}
        items.append((claim["about_date"], 1, n, {
            "kind": "claim", "event_id": claim["claim_id"], "date": claim["about_date"],
            "date_precision": date_precision(claim["about_date"]),
            "about_date_end": claim["about_date_end"], "claimed_on": claim["claimed_on"],
            "category": claim["type"], "assertion": claim["assertion"], "subject": "client",
            "body_site": claim["body_site"], "quote": claim["quote"], "flags": claim["flags"],
            "conflicts": [], "sources": [source], "status": claim["status"]}))
    items.sort(key=lambda item: (item[0] is None, item[0] or "", item[1], item[2]))
    return [row for *_, row in items]


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def render_merged_markdown(case: str, rows: list[dict[str, Any]]) -> str:
    """A readable table of the merged view."""
    evidence = sum(1 for r in rows if r["kind"] == "evidence")
    claims = len(rows) - evidence
    lines = [f"# Chronology with claims: {case}", "",
             f"{evidence} evidence events and {claims} claims, in date order. Claims are the "
             f"attorney's account, not evidence, and have not been checked against the records.", "",
             "| Date | Kind | Source | Provider | Type | Statement | Assertion | Site | Claimed on | Flags |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        src = r["sources"][0]
        source = f"{src['file']} {src['bates_label'] or 'p' + str(src['page_index'] + 1)}"
        if len(r["sources"]) > 1:
            source += f" (+{len(r['sources']) - 1})"
        provider = " / ".join(x for x in (src["facility"], src["provider"]) if x)
        date = r["date"] or "undated"
        if r["date"] and r.get("about_date_end"):
            date += f" to {r['about_date_end']}"
        elif r["date"] and r["date_precision"] != "day":
            date += f" ({r['date_precision']})"
        flags = sorted({f["rule"] for f in r["flags"]} | ({"conflict"} if r["conflicts"] else set()))
        lines.append("| " + " | ".join(_cell(x) for x in (
            date, r["kind"], source, provider, r["category"], r["quote"], r["assertion"],
            r["body_site"], r.get("claimed_on"), ", ".join(flags))) + " |")
    return "\n".join(lines) + "\n"
