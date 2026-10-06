# medical-chronology

**Agentic Chronology Construction from Unstructured Medical-Legal Records**
CSCI 7000 AI Agents, CU Boulder

Physician expert witnesses get thousands of pages of medical records in no
particular order and have to build a chronology of the facts that matter. This
project builds a pipeline that does the first pass: it turns the records into a
timeline where **every entry is a verbatim quote tied to a Bates number**, so a
physician can check each line against the source.

## Research questions

- Can a system turn a disordered medical-legal record set into a chronology
  where every entry is a quote at a Bates number?
- Is recall high enough, with enough traceability, that a physician can rely on it?
- Where in this process does an agentic system add value?

## Pipeline

The five steps from the Milestone 1 deck, one module each in
`src/chronology/stages/`:

| # | Stage | Module | What it does |
|---|-------|--------|--------------|
| 1 | Parse PDFs | `parse.py` | Per-page text (native text layer, OCR for scans), Bates label per page, page-type triage |
| 2 | Extract terms | `extract.py` | Findings with exact source spans, negation/uncertainty, event vs document date |
| 3 | ReAct loop | `normalize.py` | Bounded loop that maps each finding to UMLS / SNOMED CT |
| 4 | Generate timeline | `timeline.py` | Orders events, keeps partial dates and contradictions visible |
| 5 | Verify | `verify.py` | Checks every quote is exactly on the cited page before output |

The shared data contract is in `src/chronology/schemas.py`. The key rule is
that what the record *says* (an `EvidenceSpan`) is stored separately from what
the system *thinks* it means (`Finding`, `ConceptMapping`, `ChronologyEvent`),
and every interpretation points back to its spans.

## Patient data: read this first

The case records contain real PHI. **They never go in this repo**, private or not.

- Keep records in `data/` on your own machine. Git ignores everything there
  except `data/README.md`.
- `.gitignore` also blocks PDFs, ZIPs, DOCX, DICOM, emails and `.env` anywhere
  in the repo, and CI fails if one gets committed anyway.
- Don't paste record text into issues, PRs, commit messages or committed
  notebooks. Tests use made-up names and text.
- Don't send record text to hosted model APIs until the team has confirmed
  that's allowed for this data.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

For the UMLS stage, copy `.env.example` to `.env` and add your own UMLS API
key from https://uts.nlm.nih.gov/ (keys are per person under the UMLS license).

## Status

Scaffold only. Done so far: the data schemas, Bates filename parsing and stamp
detection, and the exact-quote check. Stages 1 to 4 are stubs. A good first
target is the smallest case (about 60 pages), scored against the physician's
existing chronology for that case.

## Team

Rosby Robinson, Sushmey Nirmal, Ted Mburu, Jack McKinstry, Oliver Browne.
Physician advisor: Dr. Jan Bear.
