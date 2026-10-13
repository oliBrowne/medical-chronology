"""The chronology bundle: everything the output step needs, in one JSON file.

It is the shared schemas from ``chronology.schemas`` grouped together, plus
the case information the timeline is drawn around (the index event and the
claimed injuries). ``schemas.py`` is not changed; this module only wraps it.

``index_bundle`` resolves every reference (event -> finding -> span -> page ->
document) and re-runs the exact-quote check on every span. Anything broken is
collected as a ``Problem`` and shown in the output, never dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from chronology.schemas import (
    ChronologyEvent,
    ConceptMapping,
    EvidenceSpan,
    Finding,
    Page,
    SourceDocument,
)
from chronology.stages.verify import quote_matches_page

BUNDLE_VERSION = "0.1"


class IndexEvent(BaseModel):
    """The incident the chronology is measured from (the highlighted bar)."""

    date: str  # ISO day, e.g. "2024-03-14"
    time: str | None = None  # "17:40" if the record gives one
    description: str
    mechanism: str | None = None


class ClaimedInjury(BaseModel):
    """One injury the case claims. ``body_sites`` drive the Injury filter."""

    id: str
    label: str
    body_sites: list[str] = Field(default_factory=list)


class ChronologyBundle(BaseModel):
    bundle_version: str = BUNDLE_VERSION
    case_id: str
    generated_at: str
    pipeline_version: str
    index_event: IndexEvent | None = None
    claimed_injuries: list[ClaimedInjury] = Field(default_factory=list)
    documents: list[SourceDocument] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    spans: list[EvidenceSpan] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    mappings: list[ConceptMapping] = Field(default_factory=list)
    events: list[ChronologyEvent] = Field(default_factory=list)


def load_bundle(path: str | Path) -> ChronologyBundle:
    return ChronologyBundle.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Problem:
    kind: str  # "broken_reference" | "quote_mismatch" | "bates_mismatch"
    ref: str  # the id the problem is attached to (event, finding or span)
    message: str


@dataclass
class BundleIndex:
    bundle: ChronologyBundle
    documents: dict[str, SourceDocument] = field(default_factory=dict)
    pages: dict[tuple[str, int], Page] = field(default_factory=dict)
    spans: dict[str, EvidenceSpan] = field(default_factory=dict)
    findings: dict[str, Finding] = field(default_factory=dict)
    mappings: dict[str, ConceptMapping] = field(default_factory=dict)
    verified: dict[str, bool] = field(default_factory=dict)  # span_id -> exact quote check
    problems: list[Problem] = field(default_factory=list)

    def problems_for(self, ref: str) -> list[Problem]:
        return [p for p in self.problems if p.ref == ref]


def index_bundle(bundle: ChronologyBundle) -> BundleIndex:
    ix = BundleIndex(bundle=bundle)
    ix.documents = {d.doc_id: d for d in bundle.documents}
    ix.pages = {(p.doc_id, p.page_index): p for p in bundle.pages}
    ix.spans = {s.span_id: s for s in bundle.spans}
    ix.findings = {f.finding_id: f for f in bundle.findings}
    ix.mappings = {m.finding_id: m for m in bundle.mappings}
    add = ix.problems.append

    for page in bundle.pages:
        if page.doc_id not in ix.documents:
            add(Problem("broken_reference", f"{page.doc_id}:{page.page_index}",
                        f"page {page.page_index + 1} names document {page.doc_id!r}, which is not in the bundle"))

    for span in bundle.spans:
        page = ix.pages.get((span.doc_id, span.page_index))
        if page is None:
            ix.verified[span.span_id] = False
            add(Problem("broken_reference", span.span_id,
                        f"span cites page {span.page_index + 1} of {span.doc_id!r}, which is not in the bundle"))
            continue
        ok = quote_matches_page(span, page)
        ix.verified[span.span_id] = ok
        if not ok:
            add(Problem("quote_mismatch", span.span_id,
                        "quote is not the exact text at the cited characters of the cited page"))
        if span.bates_label != page.bates_label:
            add(Problem("bates_mismatch", span.span_id,
                        f"span says {span.bates_label!r} but the page is {page.bates_label!r}"))

    for finding in bundle.findings:
        for sid in finding.span_ids:
            if sid not in ix.spans:
                add(Problem("broken_reference", finding.finding_id,
                            f"finding points at span {sid!r}, which is not in the bundle"))

    for event in bundle.events:
        for fid in event.finding_ids + event.conflicts:
            if fid not in ix.findings:
                add(Problem("broken_reference", event.event_id,
                            f"event points at finding {fid!r}, which is not in the bundle"))
        for fid in event.conflicts:
            if fid not in event.finding_ids:
                add(Problem("broken_reference", event.event_id,
                            f"conflict {fid!r} is not one of the event's findings"))
    return ix
