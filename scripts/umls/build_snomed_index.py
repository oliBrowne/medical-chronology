"""Build the local SNOMED CT search index from a UMLS release.

    python scripts/umls/build_snomed_index.py ~/Downloads/umls-2025AB-metathesaurus-full.zip
    python scripts/umls/build_snomed_index.py ~/umls/2025AB/META --release 2025AB

Download the "UMLS Metathesaurus Full Subset" zip (umls-<release>-metathesaurus-full.zip)
from https://www.nlm.nih.gov/research/umls/licensedcontent/umlsknowledgesources.html
with your own UMLS account. The zip is read directly; no need to unpack it.
(The "UMLS Full Release" zip holds .nlm files that need MetamorphoSys; skip it.)

Writes data/umls/snomed_<release>.sqlite (gitignored). It is licensed UMLS
content: don't commit it or send it to anyone; each person builds their own.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from chronology.tools.snomed_index import (
    DEFAULT_DIR,
    SnomedIndex,
    build_index,
    guess_release,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the release zip, or a folder holding MRCONSO.RRF and MRSTY.RRF")
    parser.add_argument("--release", help="e.g. 2025AB; read from the path when left out")
    parser.add_argument("--out", type=Path, help=f"default: {DEFAULT_DIR.relative_to(REPO)}/snomed_<release>.sqlite")
    parser.add_argument("--try", dest="try_phrase", default="neck pain", help="phrase to search once it is built")
    args = parser.parse_args()

    release = args.release or guess_release(args.source)
    if not release:
        raise SystemExit("can't tell the UMLS release from the path; pass --release 2025AB")
    out = args.out or DEFAULT_DIR / f"snomed_{release}.sqlite"
    started = time.time()
    print(f"reading {args.source} (UMLS {release}); this takes a few minutes for a full release")
    counts = build_index(args.source, out, release)
    print(f"wrote {out}: {counts['concepts']:,} SNOMED CT concepts, {counts['names']:,} names "
          f"in {time.time() - started:.0f}s")
    index = SnomedIndex(out)
    for c in index.search(args.try_phrase, 5):
        print(f"  {c.score:.2f} {c.match:5} {c.code:>12} {c.cui} {c.preferred_name} ({c.tag}) {list(c.semantic_types)}")


if __name__ == "__main__":
    main()
