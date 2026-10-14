"""Write made-up pages as a synthetic case folder of PDFs, for end-to-end tests.

Each file from scripts/jev/generated_test.json (or --pages) becomes one PDF
named like a production ("TEST 000001-000004 - synthetic.pdf") with a matching
Bates stamp printed on every page. The folder gets a SYNTHETIC marker, which
is what lets scripts/case/triage_case.py send its pages to Jev, and a
truth.json with the hand labels so the run can be scored.

    python scripts/case/make_synthetic_case.py                     # -> runs/synthetic-case/
    python scripts/case/make_synthetic_case.py --pages scripts/jev/heldout2_pages.json --out runs/heldout2-case

The output goes under runs/ (gitignored); PDFs are never committed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STAMP = re.compile(r"^\s*TEST \d{6}\s*$")
MARKER = "SYNTHETIC"


def main() -> None:
    import pymupdf as fitz

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", type=Path, default=REPO / "scripts/jev/generated_test.json")
    parser.add_argument("--out", type=Path, default=REPO / "runs/synthetic-case")
    args = parser.parse_args()

    pages = json.loads(args.pages.read_text())
    files: dict[str, list[dict]] = {}
    for p in pages:
        files.setdefault(p.get("doc", p["id"]), []).append(p)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / MARKER).write_text("Made-up pages written by scripts/case/make_synthetic_case.py. No record text.\n")
    truth, bates = {}, 1
    for fid, fp in files.items():
        fp.sort(key=lambda p: p.get("seq", 1))
        start, end = bates, bates + len(fp) - 1
        name = f"TEST {start:06d}-{end} - synthetic.pdf"
        pdf = fitz.open()
        for i, p in enumerate(fp):
            label = f"TEST {start + i:06d}"
            body = "\n".join(x for x in p["text"].split("\n") if not STAMP.match(x))
            page = pdf.new_page()
            page.insert_textbox(fitz.Rect(54, 54, 558, 740), body, fontsize=10, fontname="helv")
            page.insert_text((470, 770), label, fontsize=9, fontname="helv")
            truth[label] = {"label": p["label"], "clinical": p["clinical"], "category": p.get("category", ""),
                            "starts": p.get("starts", p.get("seq", 1) == 1), "source_id": p["id"]}
        pdf.save(args.out / name)
        pdf.close()
        bates = end + 1
    (args.out / "truth.json").write_text(json.dumps(truth, indent=1))
    print(f"wrote {len(files)} PDFs, {len(truth)} pages to {args.out}")


if __name__ == "__main__":
    main()
