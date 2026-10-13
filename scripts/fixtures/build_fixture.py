"""Build the synthetic case SYN-001 for the output step.

Writes:
- ``examples/syn-001.bundle.json``: the bundle the renderer reads (fake data,
  safe to commit).
- ``examples/syn-001-broken.bundle.json``: the same with one quote altered, to
  prove the output flags it.
- ``data/synthetic/SYN-001/*.pdf``: one PDF per document, named for its Bates
  range like a real production, so the Bates links open the right page.
  PDFs are gitignored; re-run this script to regenerate them.

Every page comes from ``scripts/jev/synthetic_pages.json`` (made up). Findings
are given as quote text; the script finds the quote on the page, builds the
span from the offsets, and asserts the repo's own ``quote_matches_page``
passes, so the fixture cannot drift from the verifier.

Several synthetic pages carry no date. Event dates for those are assigned by
hand here so the renderer has something to sort; in the real pipeline they
come from extraction, and pages without one stay undated.

    python scripts/fixtures/build_fixture.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from chronology.output.bundle import (  # noqa: E402
    ChronologyBundle, ClaimedInjury, IndexEvent,
)
from chronology.schemas import (  # noqa: E402
    ChronologyEvent, ConceptMapping, EvidenceSpan, Finding, Page, SourceDocument,
)
from chronology.stages.verify import quote_matches_page  # noqa: E402

CASE_ID = "SYN-001"
PAGES_JSON = REPO / "scripts" / "jev" / "synthetic_pages.json"

# (doc_id, file name, Bates prefix, first number or None, doc_type, [(page id, ocr confidence)])
DOCUMENTS = [
    ("d01", "SYN 000001-000003 - Mountain View Regional ED.pdf", "SYN", 1, "medical records",
     [("syn-01", None), ("syn-07", None), ("syn-02", None)]),
    ("d02", "SYN 000004 - Family Medicine Associates.pdf", "SYN", 4, "medical records",
     [("syn-03", None)]),
    ("d03", "SYN 000005-000006 - Peak Physical Therapy.pdf", "SYN", 5, "medical records",
     [("syn-05", None), ("syn-20", None)]),
    ("d04", "SYN 000007 - Front Range Chiropractic.pdf", "SYN", 7, "medical records",
     [("syn-06", 0.62)]),
    ("d05", "SYN 000008-000011 - Sample Orthopedics.pdf", "SYN", 8, "medical records",
     [("syn-04", None), ("syn-08", None), ("syn-09", None), ("syn-10", None)]),
    ("d06", "SYN 000012 - Pharmacy dispensing history.pdf", "SYN", 12, "pharmacy records",
     [("syn-12", None)]),
    ("d07", "SYN 000013-000014 - Billing.pdf", "SYN", 13, "billing",
     [("syn-13", None), ("syn-14", None)]),
    ("d08", "Patient intake packet.pdf", None, None, "medical records",  # unstamped
     [("syn-11", None)]),
]

# finding_id: (page id, exact quote, category, assertion, body_site, event_date, document_date)
FINDINGS = {
    "f01": ("syn-01", "Chief complaint: neck pain after motor vehicle collision",
            "symptom", "present", "neck", "2024-03-14", "2024-03-14"),
    "f02": ("syn-01", "denies LOC", "symptom", "absent", "head", "2024-03-14", "2024-03-14"),
    "f03": ("syn-01", "denies numbness or tingling", "symptom", "absent",
            "upper extremities", "2024-03-14", "2024-03-14"),
    "f04": ("syn-01", "Paraspinal tenderness C4-C6", "exam", "present",
            "cervical spine", "2024-03-14", "2024-03-14"),
    "f05": ("syn-01", "Assessment: Cervical strain.", "diagnosis", "present",
            "cervical spine", "2024-03-14", "2024-03-14"),
    "f06": ("syn-07", "Mild degenerative changes at C5-C6.", "imaging", "present",
            "cervical spine", "2024-03-14", None),
    "f07": ("syn-07", "Impression: No acute fracture.", "imaging", "absent",
            "cervical spine", "2024-03-14", None),
    "f08": ("syn-03", "Cervical strain, improving.", "diagnosis", "present",
            "cervical spine", "2024-03-21", "2024-03-21"),
    "f09": ("syn-03", "Decreased cervical rotation to the right.", "exam", "present",
            "cervical spine", "2024-03-21", "2024-03-21"),
    "f10": ("syn-05", "Dx: Cervical strain (S16.1XXA)", "diagnosis", "present",
            "cervical spine", "2024-04", None),
    "f11": ("syn-14", "A. S16.1XXA", "diagnosis", "present",
            "cervical spine", "2024-04-02", None),
    "f12": ("syn-06", "Lower back tight, 5/10, worse after sitting.", "symptom", "present",
            "lumbar spine", "2024-04-02", "2024-04-02"),
    "f13": ("syn-02", "low back pain, slipped on wet floor at work", "symptom", "present",
            "lumbar spine", None, None),
    "f14": ("syn-04", "prior shoulder injury playing softball in 2019, resolved without treatment",
            "injury", "historical", "shoulder", "2019", None),
    "f15": ("syn-04", "Right shoulder pain for 3 months.", "symptom", "present",
            "right shoulder", "2024-06", None),
    "f16": ("syn-04", "Impression: Right shoulder impingement, rule out rotator cuff tear.",
            "diagnosis", "present", "right shoulder", "2024-06", None),
    "f17": ("syn-08", "1. Partial thickness supraspinatus tear.", "imaging", "present",
            "right shoulder", "2024-07-02", None),
    "f18": ("syn-10", "Findings: Full thickness tear of the supraspinatus, 1.5 cm.",
            "procedure", "present", "right shoulder", "2024-09-12", None),
    "f19": ("syn-09", "Injected 40 mg triamcinolone with 4 mL 1% lidocaine.", "procedure",
            "present", "right shoulder", "2024-07-15", None),
    "f20": ("syn-10", "Procedure: Arthroscopic rotator cuff repair, subacromial decompression",
            "procedure", "present", "right shoulder", "2024-09-12", None),
    "f21": ("syn-12", "IBUPROFEN 800MG TAB", "medication", "present", None, "2024-03-14", None),
    "f22": ("syn-11", "Lisinopril 10 mg tab - 1 tab PO daily", "medication", "present",
            None, None, None),
    "f23": ("syn-11", "Allergies: Penicillin (rash)", "allergy", "present", None, None, None),
}

# event_id: (date, findings, conflicts, review_status)
EVENTS = {
    "ev-01": ("2024-03-14", ["f01"], [], "approved"),
    "ev-02": ("2024-03-14", ["f02"], [], "pending"),
    "ev-03": ("2024-03-14", ["f03"], [], "pending"),
    "ev-04": ("2024-03-14", ["f04"], [], "pending"),
    "ev-05": ("2024-03-14", ["f05", "f08", "f10", "f11"], [], "pending"),  # repeated dx
    "ev-06": ("2024-03-14", ["f06"], [], "pending"),
    "ev-07": ("2024-03-14", ["f07"], [], "pending"),
    "ev-08": ("2024-03-14", ["f21"], [], "rejected"),
    "ev-09": ("2024-03-21", ["f09"], [], "pending"),
    "ev-10": ("2024-04-02", ["f12"], [], "pending"),  # OCR page
    "ev-11": ("2019", ["f14"], [], "pending"),  # year only, before the incident
    "ev-12": ("2024-06", ["f15"], [], "pending"),  # month only
    "ev-13": ("2024-06", ["f16"], [], "pending"),
    "ev-14": ("2024-07-02", ["f17", "f18"], ["f17", "f18"], "pending"),  # partial vs full tear
    "ev-15": ("2024-07-15", ["f19"], [], "pending"),
    "ev-16": ("2024-09-12", ["f20"], [], "pending"),
    "ev-17": (None, ["f13"], [], "pending"),  # undated: a second injury mechanism
    "ev-18": (None, ["f22"], [], "pending"),  # undated, unstamped page
    "ev-19": (None, ["f23"], [], "pending"),
}

# ICD-10-CM codes are real; these mappings are illustrative, not reviewed.
MAPPINGS = [
    ConceptMapping(finding_id="f01", status="mapped", source_vocab="ICD10CM",
                   source_code="M54.2", umls_release="2026AA", iterations=1),
    *[ConceptMapping(finding_id=f, status="mapped", source_vocab="ICD10CM",
                     source_code="S16.1XXA", umls_release="2026AA", iterations=1)
      for f in ("f05", "f08", "f10", "f11")],
    ConceptMapping(finding_id="f16", status="mapped", source_vocab="ICD10CM",
                   source_code="M75.41", umls_release="2026AA", iterations=2),
    ConceptMapping(finding_id="f17", status="needs_review", candidates=["M75.111", "S46.011A"],
                   iterations=3, umls_release="2026AA",
                   rationale="Partial-thickness tear; the record does not say traumatic or degenerative."),
    ConceptMapping(finding_id="f04", status="unmapped", iterations=3, umls_release="2026AA",
                   rationale="No single concept covers paraspinal tenderness over a level range."),
]

INDEX_EVENT = IndexEvent(
    date="2024-03-14",
    description="Rear-end motor vehicle collision at a stoplight, restrained driver",
    mechanism="MVC_rear_end",
)
CLAIMED_INJURIES = [
    ClaimedInjury(id="inj_cervical", label="Cervical strain",
                  body_sites=["neck", "cervical spine"]),
    ClaimedInjury(id="inj_shoulder", label="Right shoulder rotator cuff tear",
                  body_sites=["right shoulder", "shoulder"]),
]


def build() -> tuple[ChronologyBundle, dict[str, list[tuple[str, list[str]]]]]:
    """Return the bundle and, per file name, the (Bates stamp, lines) of each page."""
    raw = {p["id"]: p for p in json.loads(PAGES_JSON.read_text(encoding="utf-8"))}
    documents, pages, pdf_pages = [], [], {}
    page_of: dict[str, Page] = {}
    for doc_id, fname, prefix, start, doc_type, members in DOCUMENTS:
        stamps = []
        for i, (pid, conf) in enumerate(members):
            label = f"{prefix} {start + i:06d}" if prefix else None
            page = Page(doc_id=doc_id, page_index=i, bates_label=label, text=raw[pid]["text"],
                        text_source="ocr" if conf is not None else "native",
                        ocr_confidence=conf, page_type=raw[pid]["label"])
            pages.append(page)
            page_of[pid] = page
            stamps.append((label, page.text.splitlines()))
        pdf_pages[fname] = stamps
        documents.append(SourceDocument(
            doc_id=doc_id, path=fname, sha256="", page_count=len(members),
            bates_prefix=prefix, bates_start=start,
            bates_end=start + len(members) - 1 if prefix else None, doc_type=doc_type))

    spans, findings = [], []
    for n, (fid, (pid, quote, category, assertion, site, ev_date, doc_date)) in enumerate(
            FINDINGS.items(), start=1):
        page = page_of[pid]
        start = page.text.find(quote)
        assert start != -1, f"{fid}: quote not on {pid}: {quote!r}"
        assert page.text.find(quote, start + 1) == -1, f"{fid}: quote occurs twice on {pid}"
        span = EvidenceSpan(span_id=f"s{n:02d}", doc_id=page.doc_id, page_index=page.page_index,
                            bates_label=page.bates_label, char_start=start,
                            char_end=start + len(quote), quote=quote)
        assert quote_matches_page(span, page), fid
        spans.append(span)
        findings.append(Finding(finding_id=fid, span_ids=[span.span_id], category=category,
                                original_phrase=quote, assertion=assertion, body_site=site,
                                event_date=ev_date, document_date=doc_date))

    events = []
    for eid, (when, fids, conflicts, status) in EVENTS.items():
        prec = ("unknown" if when is None else
                {10: "day", 7: "month", 4: "year"}[len(when)])
        events.append(ChronologyEvent(event_id=eid, date=when, date_precision=prec,
                                      finding_ids=fids, conflicts=conflicts,
                                      review_status=status))

    bundle = ChronologyBundle(
        case_id=CASE_ID, generated_at="2026-10-13T00:00:00Z", pipeline_version="fixture",
        index_event=INDEX_EVENT, claimed_injuries=CLAIMED_INJURIES, documents=documents,
        pages=pages, spans=spans, findings=findings, mappings=MAPPINGS, events=events)
    return bundle, pdf_pages


def broken(bundle: ChronologyBundle) -> ChronologyBundle:
    """Same bundle with one quote paraphrased, as a model might."""
    b = bundle.model_copy(deep=True)
    span = next(s for s in b.spans if s.quote == "denies LOC")
    span.quote = "denies loss of consciousness"
    return b


# --- a minimal PDF writer, so the fixture needs no PDF library ---------------

def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(line: str, width: int = 96) -> list[str]:
    out = []
    while len(line) > width:
        cut = line.rfind(" ", 0, width)
        cut = width if cut <= 0 else cut
        out.append(line[:cut])
        line = line[cut:].lstrip()
    out.append(line)
    return out


def write_pdf(path: Path, pages: list[tuple[str | None, list[str]]]) -> None:
    """One page per entry: the lines in Courier, the Bates stamp bottom right."""
    objects: list[bytes] = []

    def obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = obj(b"")  # filled in below
    pages_id = obj(b"")
    font = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    kids = []
    for stamp, lines in pages:
        ops = ["BT /F1 9 Tf 11 TL 40 750 Td"]
        for line in lines:
            for part in _wrap(line):
                ops.append(f"({_pdf_escape(part)}) Tj T*")
        ops.append("ET")
        if stamp:
            ops.append(f"BT /F1 10 Tf 470 28 Td ({_pdf_escape(stamp)}) Tj ET")
        stream = "\n".join(ops).encode("latin-1")
        content = obj(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(obj(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_id, font, content)))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objects[pages_id - 1] = (b"<< /Type /Pages /Kids [%s] /Count %d >>"
                             % (b" ".join(b"%d 0 R" % k for k in kids), len(kids)))

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, catalog, xref)
    path.write_bytes(bytes(out))


def write_case(case_dir: Path, examples_dir: Path) -> ChronologyBundle:
    bundle, pdf_pages = build()
    case_dir.mkdir(parents=True, exist_ok=True)
    for doc in bundle.documents:
        pdf = case_dir / doc.path
        write_pdf(pdf, pdf_pages[doc.path])
        doc.sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    examples_dir.mkdir(parents=True, exist_ok=True)
    (examples_dir / "syn-001.bundle.json").write_text(
        bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (examples_dir / "syn-001-broken.bundle.json").write_text(
        broken(bundle).model_dump_json(indent=2) + "\n", encoding="utf-8")
    return bundle


if __name__ == "__main__":
    b = write_case(REPO / "data" / "synthetic" / CASE_ID, REPO / "examples")
    print(f"{len(b.documents)} PDFs -> data/synthetic/{CASE_ID}/")
    print(f"{len(b.events)} events, {len(b.findings)} findings -> examples/syn-001.bundle.json")
