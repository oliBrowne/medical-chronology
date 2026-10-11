"""Phase 0 Jev test: page-type sorting on made-up pages.

Sends each page in synthetic_pages.json to Jev, compares Jev's choice with
the hand label, and prints a summary to paste back to the team. Full
results go to runs/ (gitignored).

    python scripts/jev/page_type_test.py            # all 20 pages
    python scripts/jev/page_type_test.py --limit 3  # quick check first

Needs TYPESAFE_API_KEY in the environment or in .env at the repo root.
Uses only made-up pages: do not point this at real records until zero data
retention is enabled on the TypeSafe org.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from chronology import jev  # noqa: E402


def summarize(rows: list[dict]) -> str:
    n = len(rows)
    correct = [r for r in rows if r["correct"]]
    wrong = [r for r in rows if not r["correct"]]
    tokens = sum(r["input_tokens"] for r in rows)
    lines = [
        f"Model: {rows[0]['model'] if rows else '?'}",
        f"Accuracy: {len(correct)}/{n} ({len(correct) / n:.0%})" if n else "No pages run",
    ]
    if correct:
        lines.append(f"Avg top probability when right: {sum(r['top_prob'] for r in correct) / len(correct):.2f}")
    if wrong:
        lines.append(f"Avg top probability when wrong: {sum(r['top_prob'] for r in wrong) / len(wrong):.2f}")
        lines.append("Mistakes:")
        for r in wrong:
            lines.append(f"  {r['id']}: expected {r['label']}, got {r['choice']} (p={r['top_prob']:.2f})")
    confusions = Counter((r["label"], r["choice"]) for r in wrong)
    if confusions:
        common = ", ".join(f"{a}->{b} x{c}" for (a, b), c in confusions.most_common(3))
        lines.append(f"Most common confusions: {common}")
    lines.append(f"Input tokens: {tokens}  (est. cost ${jev.estimated_cost(tokens):.4f})")
    lines.append(f"Avg seconds per page: {sum(r['seconds'] for r in rows) / n:.2f}" if n else "")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", type=Path, default=Path(__file__).with_name("synthetic_pages.json"))
    parser.add_argument("--model", default=jev.DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    api_key = jev.load_api_key(REPO / ".env")
    pages = json.loads(args.pages.read_text())[: args.limit]
    question = {"page_type": jev.page_type_question()}

    rows = []
    for page in pages:
        started = time.monotonic()
        response = jev.ask(page["text"], question, api_key, model=args.model)
        answer = response["answers"]["page_type"]
        rows.append({
            "id": page["id"],
            "label": page["label"],
            "choice": answer["choice"],
            "correct": answer["choice"] == page["label"],
            "top_prob": jev.top_probability(answer),
            "confidence": answer.get("confidence"),
            "input_tokens": response.get("usage", {}).get("input_tokens", 0),
            "seconds": round(time.monotonic() - started, 2),
            "model": response.get("model", args.model),
            "probabilities": json.dumps(answer.get("probabilities")),
        })
        print(f"{page['id']}: {answer['choice']:<18} (label {page['label']})", flush=True)

    out_dir = REPO / "runs"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"jev-page-type-{datetime.now():%Y%m%d-%H%M%S}.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print("\n--- Summary (paste this back) ---")
    print(summarize(rows))
    print(f"\nFull results: {out}")


if __name__ == "__main__":
    main()
