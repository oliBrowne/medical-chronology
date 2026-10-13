"""Run the pipeline over one case folder and write the results.

    python -m chronology.pipeline sample_data/case_2
    python -m chronology.pipeline sample_data/case_2 --out data/output --workers 2

Every Markdown file in the folder (except README.md) is read and given a role
from its filename:

- ``record``: medical records. Run through the page agent.
- ``incident``: police, crash or store incident reports. Run through the page agent.
- ``claims``: the case summary. It is the attorney's account, not evidence. It
  goes through the page agent too, but its statements become claims (with the
  date they were claimed and the date they are about) and never enter the
  evidence chronology.

Wired so far: parse -> extract (page agent). Later stages (normalize, timeline,
checks, verify) plug in after ``extract``.

Writes under ``<out>/<case>/``: ``pages.json`` (per-page findings),
``chronology.json`` and ``chronology.md`` (merged, date-sorted evidence), and
``claims.json`` and ``claims.md`` (the case summary's claims, each with the
date it was claimed and the date it is about), and ``merged.json`` and
``merged.md`` (both in one date-ordered view, built from the other two, which
stay as they are). ``data/`` is gitignored.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from chronology.agents.page_agent import PageExtraction, extract_page
from chronology.llm import ollama
from chronology.llm.base import ChatClient
from chronology.llm.ollama import OllamaClient
from chronology.schemas import Page
from chronology.stages.claims import build_claims, render_claims_markdown
from chronology.stages.merge import merge_views, render_merged_markdown
from chronology.stages.parse import parse_markdown
from chronology.stages.timeline import build_chronology, render_markdown

ROLE_LABELS = {"record": "medical records", "incident": "incident report", "claims": "case summary"}
EXTRACTED_ROLES = ("record", "incident", "claims")


def file_role(path: Path) -> str:
    """The role of a case file, from its name."""
    name = path.stem.lower()
    if "summary" in name or "claim" in name:
        return "claims"
    if any(word in name for word in ("incident", "crash", "police", "accident")):
        return "incident"
    return "record"


def case_files(case_dir: Path) -> list[Path]:
    """Every Markdown file in the case folder, except READMEs."""
    return [p for p in sorted(case_dir.glob("*.md")) if p.name.lower() != "readme.md"]


def think_setting(model: str, level: str) -> str | bool | None:
    """The `think` value to send Ollama. gpt-oss takes a level (low, medium, high);
    other models take on or off; "default" leaves it to the model."""
    if level == "default":
        return None
    if model.startswith("gpt-oss"):
        return level if level in ("low", "medium", "high") else None
    return level != "off"


def run(case_dir: Path, out_dir: Path) -> None:
    """Process one case folder with the defaults. ``out_dir`` must be gitignored."""
    run_case(case_dir, out_dir)


def run_case(case_dir: Path, out_dir: Path, *, client: ChatClient | None = None,
             model: str = ollama.DEFAULT_MODEL, workers: int = 1,
             include_trace: bool = True, think: str | bool | None = "low") -> Path:
    """Read every file in the case folder, run the page agent on the evidence, save JSON.

    ``client`` is any ``ChatClient``; the default is a local Ollama model, built
    from ``model`` and ``think``.
    """
    client = client or OllamaClient(model, think=think)
    files = case_files(case_dir)
    if not files:
        raise FileNotFoundError(f"no .md files found in {case_dir}")

    sources: list[dict] = []
    jobs: list[tuple[Page, str, str]] = []  # page, file name, role
    for path in files:
        role = file_role(path)
        document, pages = parse_markdown(path)
        label = ROLE_LABELS[role]
        processed = role in EXTRACTED_ROLES
        sources.append({**document.model_copy(update={"doc_type": label}).model_dump(),
                        "role": role, "processed": processed,
                        **({} if processed else {"note": "claims step not built; file read but not extracted"})})
        print(f"  {path.name}: {role}, {document.page_count} pages"
              f"{'' if processed else ' (not extracted)'}", file=sys.stderr)
        if processed:
            jobs += [(page.model_copy(update={"page_type": label}), path.name, role) for page in pages]

    print(f"{case_dir.name}: {len(jobs)} pages to extract", file=sys.stderr)

    def run_page(job: tuple[Page, str, str]) -> PageExtraction:
        page = job[0]
        started = time.time()
        result = extract_page(page, client)
        result.seconds = time.time() - started
        print(f"  {job[1]} {page.bates_label or page.page_index}: {result.status}, "
              f"{len(result.findings)} findings, {result.steps} steps, "
              f"{result.seconds:.0f}s", file=sys.stderr)
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run_page, jobs))  # keeps job order

    output = {
        "case": case_dir.name,
        "model": getattr(client, "model", model),
        "think": getattr(client, "think", think),
        "sources": sources,
        "pages": [{"file": job[1], "role": job[2], **r.to_dict(include_trace=include_trace)}
                  for job, r in zip(jobs, results)],
    }
    path = out_dir / case_dir.name / "pages.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    # Evidence and claims are kept apart: claims never enter the chronology.
    rows = build_chronology([(job[1], job[2], r) for job, r in zip(jobs, results)
                             if job[2] != "claims"])
    (path.parent / "chronology.json").write_text(
        json.dumps({"case": case_dir.name, "events": rows}, indent=2, ensure_ascii=False))
    (path.parent / "chronology.md").write_text(render_markdown(case_dir.name, rows))

    claims = [c for job, r in zip(jobs, results) if job[2] == "claims"
              for c in build_claims(job[1], r)]
    (path.parent / "claims.json").write_text(
        json.dumps({"case": case_dir.name, "claims": claims}, indent=2, ensure_ascii=False))
    (path.parent / "claims.md").write_text(render_claims_markdown(case_dir.name, claims))

    # A third view built from the two above, which are left unchanged.
    merged = merge_views(rows, claims)
    (path.parent / "merged.json").write_text(
        json.dumps({"case": case_dir.name, "rows": merged}, indent=2, ensure_ascii=False))
    (path.parent / "merged.md").write_text(render_merged_markdown(case_dir.name, merged))
    print(f"  chronology: {len(rows)} events, claims: {len(claims)}, merged: {len(merged)}",
          file=sys.stderr)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/output"))
    parser.add_argument("--model", default=ollama.DEFAULT_MODEL)
    parser.add_argument("--think", default="low",
                        choices=["off", "low", "medium", "high", "default"],
                        help="reasoning effort: a level for gpt-oss, on/off for other models")
    parser.add_argument("--workers", type=int, default=1,
                        help="pages processed at once (Ollama also needs OLLAMA_NUM_PARALLEL)")
    parser.add_argument("--no-trace", action="store_true", help="leave tool-call traces out of the JSON")
    args = parser.parse_args()
    path = run_case(args.case_dir, args.out, model=args.model, workers=args.workers,
                    include_trace=not args.no_trace, think=think_setting(args.model, args.think))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
