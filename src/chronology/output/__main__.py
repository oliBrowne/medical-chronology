"""Render a chronology bundle.

    python -m chronology.output --bundle examples/syn-001.bundle.json \\
        --case-dir data/synthetic/SYN-001 --out outputs/SYN-001

``--case-dir`` is the folder the PDFs were read from; document paths in the
bundle are relative to it. Without it, Bates labels render unlinked.
``--out`` must be gitignored for real cases (``outputs/`` is).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from chronology.output.bundle import index_bundle, load_bundle
from chronology.output.timeline_html import write_outputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m chronology.output", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--case-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    bundle = load_bundle(args.bundle)
    paths = write_outputs(bundle, case_dir=args.case_dir, out_dir=args.out)
    problems = index_bundle(bundle).problems
    for name, path in paths.items():
        print(f"{name}: {path}")
    if problems:
        print(f"{len(problems)} problem(s) flagged in the output:")
        for p in problems:
            print(f"  [{p.kind}] {p.ref}: {p.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
