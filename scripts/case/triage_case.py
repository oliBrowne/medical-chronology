"""Triage a case folder of PDFs and write what a reviewer needs to check it.

    python scripts/case/triage_case.py runs/synthetic-case          # made-up case: Jev allowed
    python scripts/case/triage_case.py data/<case> --code-only      # real case, no model calls
    python scripts/case/triage_case.py data/<case> --zdr-confirmed  # real case, only once ZDR is on

Sends page text to Jev only when it is safe to:
  - the folder holds a SYNTHETIC marker (written by make_synthetic_case.py), or
  - zero data retention is confirmed for the TypeSafe org: pass --zdr-confirmed
    AND set TYPESAFE_ZDR_CONFIRMED=yes in the environment. Both, on purpose.
Otherwise use --code-only: parsing, document detection, duplicates and code
rules run; every page that would need Jev is routed to a full read.

Writes to runs/case-<folder>-<timestamp>/ (gitignored):
  audit.jsonl   one row per page: route, reason, answers, text hash; no text
  review.csv    every page that the page agent will NOT read in full (index
                only, table reader, duplicate), with its file and Bates label,
                and empty columns for the reviewer: compare each with the PDF
                and mark ok / missed, plus notes
  summary.txt   routes, documents found, Jev calls and cost; with a truth.json
                (synthetic cases) also the clinical pages held back and
                document-start precision and recall
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "jev"))

from chronology import segment# noqa: E402
from chronology.llm import jev# noqa: E402
from chronology.stages import parse  # noqa: E402

HELD_BACK = ("skip", "reader", "duplicate", "billing")


jev_allowed = jev.real_text_allowed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("case", type=Path)
    parser.add_argument("--code-only", action="store_true", help="no Jev calls: pages needing Jev get a full read")
    parser.add_argument("--fake", action="store_true", help="offline keyword stand-in for Jev (testing only)")
    parser.add_argument("--zdr-confirmed", action="store_true")
    parser.add_argument("--model", default=jev.DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    case = args.case.resolve()
    pdfs = sorted(p for p in case.rglob("*") if p.suffix.lower() == ".pdf")
    if not pdfs:
        raise SystemExit(f"no PDFs under {case}")

    if args.code_only:
        def ask(state, qs):
            raise RuntimeError("code-only run: no Jev call")
        mode = "code only (no Jev calls)"
    elif args.fake:
        from triage_v2_test import fake_ask_v5
        ask, mode = fake_ask_v5, "fake Jev (keyword stand-in): numbers mean nothing"
    else:
        ok, why = jev_allowed(case, args.zdr_confirmed)
        if not ok:
            raise SystemExit(why)
        key = jev.load_api_key(REPO / ".env")

        def ask(state, qs):
            return jev.ask(state, qs, key, model=args.model)
        mode = f"Jev {args.model}: {why}"

    docs, pages = [], []
    for pdf in pdfs:
        d, ps = parse.parse_document(pdf, case)
        docs.append(d)
        pages += ps
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = parse.triage_case(pages, ask, pool_map=pool.map)
    rows = parse.audit_rows(pages, results)

    out = REPO / "runs" / f"case-{case.name}-{datetime.now():%Y%m%d-%H%M%S}"
    parse.write_audit(out / "audit.jsonl", rows)
    path_of = {d.doc_id: d.path for d in docs}
    with (out / "review.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "page", "bates", "route", "page_type", "reason", "duplicate_of",
                    "reviewer_ok (ok/missed)", "reviewer_notes"])
        for r in rows:
            if r["route"] in HELD_BACK:
                w.writerow([path_of[r["doc_id"]], r["page_index"] + 1, r["bates_label"], r["route"],
                            r["page_type"], r["reason"], r["duplicate_of"] or "", "", ""])

    routes = Counter(r["route"] for r in rows)
    calls = 0 if args.code_only else sum(r["jev_calls"] for r in rows)
    tokens = sum(res.tokens for res in results)
    agent = sum(r["chars_to_agent"] or 0 for r in rows)
    total = sum(r["chars"] for r in rows)
    lines = [f"Case: {case.name}   mode: {mode}",
             f"{len(docs)} files, {len(pages)} pages, {sum(1 for r in rows if r['chars'] == 0)} with no text layer",
             f"documents found inside files: {len({(p.doc_id, p.segment) for p in pages})}",
             "routes: " + "  ".join(f"{k} {routes.get(k, 0)}" for k in ("skip", "reader", "duplicate", "full_new", "full", "billing")),
             f"page agent reads {agent:,} of {total:,} characters ({agent / max(1, total):.0%})",
             f"Jev calls {calls} ({calls / max(1, len(pages)):.2f} per page), input tokens {tokens} "
             f"(est. ${jev.estimated_cost(tokens):.4f})",
             f"pages for the reviewer (not read in full): {sum(routes.get(k, 0) for k in HELD_BACK)} -> review.csv"]
    truth_path = case / "truth.json"
    if truth_path.exists():
        truth = json.loads(truth_path.read_text())
        held = [r for r in rows if r["route"] in ("skip", "duplicate", "billing")]
        critical = [r["bates_label"] for r in held if truth[r["bates_label"]]["clinical"] == "yes"
                    and r["route"] != "duplicate"]
        reader_clinical = [r["bates_label"] for r in rows if r["route"] == "reader"
                           and truth[r["bates_label"]]["clinical"] == "yes"]
        files: dict[str, list] = {}
        for p in pages:
            files.setdefault(p.doc_id, []).append(p)
        pred, true = [], []
        for fp in files.values():
            fp.sort(key=lambda p: p.page_index)
            for prev, p in zip(fp, fp[1:]):
                pred.append(p.segment != prev.segment)
                true.append(bool(truth[p.bates_label]["starts"]))
        sc = segment.boundary_scores([True] + pred, [True] + true)
        type_right = sum(r["page_type"] in (truth[r["bates_label"]]["label"], None) or
                         (r["page_type"] in jev.EXTRA_PAGE_TYPES and truth[r["bates_label"]]["label"] == "other")
                         for r in rows if r["route"] != "duplicate")
        lines += [f"TRUTH: clinical pages held back (index only): {len(critical)} {' '.join(critical)}",
                  f"TRUTH: clinical pages sent to a table reader (rows kept verbatim): {len(reader_clinical)}",
                  f"TRUTH: page type right (or unsure) on {type_right}/{sum(r['route'] != 'duplicate' for r in rows)}",
                  f"TRUTH: document starts precision {sc['precision']:.2f} recall {sc['recall']:.2f} "
                  f"(missed {sc['fn']}, false {sc['fp']})"]
    text = "\n".join(lines)
    (out / "summary.txt").write_text(text + "\n")
    print(text)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
