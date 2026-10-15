"""Smoke test for a local embedding server (llama-server, OpenAI-compatible /v1/embeddings).

Usage:
    python3 scripts/test_embeddings.py [--url http://127.0.0.1:8080] [--model NAME]

Standard library only. Checks:
  1. server answers and returns vectors of a consistent size
  2. same text gives the same vector (determinism)
  3. related medical phrases score higher than unrelated ones
  4. batch input returns one vector per input
"""
import argparse
import json
import math
import sys
import urllib.request


def embed(url, texts, model):
    body = {"input": texts}
    if model:
        body["model"] = model
    req = urllib.request.Request(
        f"{url}/v1/embeddings",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)["data"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Server returned {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach {url}: {e.reason}")
    vecs = [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
    if vecs and isinstance(vecs[0][0], list):
        sys.exit("Got per-token vectors (pooling is 'none'). Start the server with a pooling mode, e.g. --pooling mean.")
    return vecs


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


# (anchor, related, unrelated): the related phrase should score higher than the unrelated one.
TRIPLES = [
    ("SLR neg bilat", "straight leg raise test negative on both sides", "corticosteroid injection"),
    ("cervical strain", "neck muscle strain", "wrist fracture"),
    ("low back pain", "lumbar pain", "right shoulder impingement"),
    ("rotator cuff tear", "supraspinatus tendon tear", "disc desiccation"),
    ("denies back pain", "no complaints of lumbar pain", "reports severe back pain"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    failures = 0

    def check(ok, label, detail=""):
        nonlocal failures
        print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}".rstrip())
        failures += 0 if ok else 1

    # 1. basic response and dimension
    v = embed(args.url, ["neck pain"], args.model)[0]
    check(len(v) > 0, "returns a vector", f"(dim={len(v)})")
    check(any(x != 0 for x in v), "vector is not all zeros")

    # 2. determinism
    v2 = embed(args.url, ["neck pain"], args.model)[0]
    sim = cosine(v, v2)
    check(sim > 0.999, "same text gives same vector", f"(cos={sim:.4f})")

    # 3. related vs unrelated
    flat = [t for triple in TRIPLES for t in triple]
    vecs = embed(args.url, flat, args.model)
    check(len(vecs) == len(flat), "batch returns one vector per input", f"({len(vecs)}/{len(flat)})")
    print("\nanchor | related score | unrelated score")
    wins = 0
    for i, (a, r, u) in enumerate(TRIPLES):
        va, vr, vu = vecs[3 * i : 3 * i + 3]
        sr, su = cosine(va, vr), cosine(va, vu)
        wins += sr > su
        print(f"  {a!r}: {sr:.3f} vs {su:.3f}  {'ok' if sr > su else 'WRONG ORDER'}")
    check(wins == len(TRIPLES), "related beats unrelated", f"({wins}/{len(TRIPLES)})")

    print(f"\n{'All checks passed' if not failures else str(failures) + ' check(s) failed'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
