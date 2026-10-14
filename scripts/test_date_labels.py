"""Test Julia-1 (llama-server /v1/systemone) on labeling what kind of date a line holds.

Usage:
    python3 scripts/test_date_labels.py [--url http://127.0.0.1:8080] [--context]

Each test line is looked up in sample_data/case_1 (so the test stays tied to the real
text), sent as the `state`, and the model must choose one label. Standard library only.
"""
import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "sample_data" / "case_1"

# Keep descriptions short and distinct. Long descriptions that share wording
# ("The date the record was ...") made the model pick the wrong option with high confidence.
LABELS = {
    "visit": "visit",
    "signature": "signature",
    "print": "print",
    "certification": "certification",
    "dob": "dob",
    "mentioned_event": "mentioned_event",
}

# (substring that identifies one real line in the sample data, correct label)
CASES = [
    ("**Date of Service:** 03/14/2024", "visit"),
    ("Electronically signed: A. Kowalczyk, MD 03/15/2024 01:12", "signature"),
    ("Printed: 05/20/2024 09:14", "print"),
    ("**Visit Date:** 03/28/2024", "visit"),
    ("Signed: P. Nguyen, MD 03/28/2024", "signature"),
    ("**Patient:** Reyes, Dana **DOB:** 08/02/1990 **Date:** 04/03/2024", "visit"),
    ("L. Brandt, PT, DPT 04/03/2024", "signature"),
    ("**Exam Date:** 05/02/2024", "visit"),
    ("H. Osei, MD 05/02/2024 16:20", "signature"),
    ("Records certified: 08/30/2024", "certification"),
    ("| 06/09/2022 | CMT C/L, STM | Neck 3/10 |", "visit"),
    ("helped a friend move apartments on 3/20", "mentioned_event"),
    ("Printed: 04/02/2024 10:31 Page 1 of 2", "print"),
    ("Refusal signed: D. Reyes 18:15", "signature"),
    ("**Date:** 06/07/2022", "visit"),
]


def find_line(snippet):
    for f in sorted(DATA.glob("*.md")):
        for line in f.read_text().splitlines():
            if snippet in line:
                return f.name, line.strip()
    return None, None


def decide(url, state, question):
    body = {
        "state": state,
        "questions": {"q": {"type": "choice", "instructions": question, "criteria": LABELS}},
    }
    req = urllib.request.Request(
        f"{url}/v1/systemone",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["answers"]["q"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Server returned {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach {url}: {e.reason}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--context", action="store_true",
                    help="also send the previous line (some labels depend on the line before)")
    args = ap.parse_args()

    right = 0
    total = 0
    confusion = Counter()
    for snippet, gold in CASES:
        fname, line = find_line(snippet)
        if line is None:
            print(f"[SKIP] not found in sample data: {snippet!r}")
            continue
        state = line
        if args.context:
            lines = (DATA / fname).read_text().splitlines()
            i = next(k for k, l in enumerate(lines) if snippet in l)
            state = "\n".join(l for l in lines[max(0, i - 1): i + 1] if l.strip())
        ans = decide(args.url, state, "What kind of date or timestamp is in the last line of this text?")
        pred = ans["choice"]
        ok = pred == gold
        right += ok
        total += 1
        confusion[(gold, pred)] += 1
        top = ans["probabilities"][pred]
        print(f"[{'PASS' if ok else 'FAIL'}] gold={gold:<15} pred={pred:<15} p={top:.2f}  {line[:70]}")

    print(f"\nAccuracy: {right}/{total}")
    wrong = [(g, p, n) for (g, p), n in confusion.items() if g != p]
    if wrong:
        print("Mistakes (gold -> predicted):")
        for g, p, n in sorted(wrong, key=lambda x: -x[2]):
            print(f"  {g} -> {p}: {n}")
    sys.exit(0 if right == total else 1)


if __name__ == "__main__":
    main()
