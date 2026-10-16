"""PDF parsing, document detection, triage wiring and the audit log. Jev is
replaced by a stand-in; PDFs are made up and written to a temp folder."""

import json
import re
import sys
from pathlib import Path

import pytest

from chronology import segment
from chronology.stages import parse

REPO = Path(__file__).parents[1]


# --- document detection ------------------------------------------------------

def test_counter_restart_and_continuation():
    texts = ["DISCHARGE INSTRUCTIONS\nbody\nPage 1 of 2", "more body\nPage 2 of 2",
             "PATIENT STATEMENT\ncharges\nPage 1 of 1"]
    b = segment.code_boundaries(texts)
    assert [x.starts for x in b] == [True, False, True]
    assert b[1].sure and b[2].sure


def test_new_title_starts_and_running_text_continues():
    texts = ["Sample Orthopedics\nPROGRESS NOTE 03/01/2024\nS: neck pain",
             "continues the plan from the visit: home exercises",
             "IMPRESSION:\n1. No acute abnormality.\nSigned Dr. Example, Radiology",
             "EXAMPLE CLINIC - PATIENT STATEMENT (continued)\n99213 $145.00",
             "Example Law Group\nRe: TESTPATIENT, ALEX\nDear Adjuster,"]
    assert [x.starts for x in segment.code_boundaries(texts)] == [True, False, False, False, True]


def test_jev_settles_only_what_code_was_unsure_of():
    bounds = [segment.Boundary(True, "first page", True), segment.Boundary(False, "no title", False),
              segment.Boundary(False, "counter", True), segment.Boundary(True, "title", False)]
    answers = [(None, None), ("starts", 0.97), ("starts", 0.99), ("continues", 0.99)]
    refined = segment.refine_with_jev(bounds, answers)
    # Jev adds a start code missed; a counter wins; Jev never removes a code start
    assert [b.starts for b in refined] == [True, True, False, True]
    assert segment.segment_ids(refined) == [0, 1, 1, 2]
    # an unsure answer changes nothing
    assert segment.refine_with_jev(bounds, [(None, None), ("starts", 0.6), (None, None)])[1].starts is False


def test_boundary_scores_ignore_the_first_page():
    s = segment.boundary_scores([True, True, False, True], [True, False, False, True])
    assert (s["tp"], s["fp"], s["fn"]) == (1, 1, 0)


# --- PDF parsing and the case pipeline ---------------------------------------

fitz = pytest.importorskip("pymupdf")


def _pdf(path: Path, pages: list[str]) -> Path:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(54, 54, 558, 740), text, fontsize=10, fontname="helv")
    doc.save(path)
    doc.close()
    return path


FAX = "FAX COVER SHEET\nTo: Records Unit\nFrom: Example Clinic\nPages: 3\nCONFIDENTIALITY NOTICE"
NOTE = ("PROGRESS NOTE 03/01/2024\nPatient: TESTPATIENT, ALEX\nS: neck pain 6/10 after a collision.\n"
        "A: cervical strain. P: physical therapy.")


def test_parse_document_reads_text_bates_and_segments(tmp_path):
    pdf = _pdf(tmp_path / "TEST 000010-12 - synthetic.pdf", [FAX + "\nTEST 000010", NOTE, "x"])
    doc, pages = parse.parse_document(pdf, tmp_path)
    assert doc.doc_id == "TEST000010" and doc.page_count == 3 and doc.bates_start == 10
    assert "synthetic" not in doc.doc_id   # the id never carries the file name
    assert [p.bates_label for p in pages] == ["TEST 000010", "TEST 000011", "TEST 000012"]
    assert "FAX COVER SHEET" in pages[0].text
    assert pages[2].text == ""             # no usable text layer: kept, empty, read in full later
    assert [p.segment for p in pages] == [0, 1, 1]


def test_printed_stamp_wins_when_it_disagrees(tmp_path):
    pdf = _pdf(tmp_path / "TEST 000020-21 - x.pdf", [NOTE + "\nTEST 000555", NOTE.replace("6/10", "5/10")])
    _, pages = parse.parse_document(pdf)
    assert pages[0].bates_label == "TEST 000555" and pages[1].bates_label == "TEST 000021"


def _ask(state, qs):
    page = state.split("[THIS PAGE]\n", 1)[1]
    t, c = ("fax_cover", "no") if "FAX COVER" in page else ("office_visit", "notes")
    out = {"page_type": {"choice": t, "probabilities": {t: 0.98}},
           "clinical": {"choice": c, "probabilities": {c: 0.98}}}
    if "position" in qs:
        out["position"] = {"choice": "starts", "probabilities": {"starts": 0.95}}
    return {"answers": out, "usage": {"input_tokens": 50}}


def test_triage_case_writes_routes_and_a_text_free_audit(tmp_path):
    pdf = _pdf(tmp_path / "TEST 000001-2 - case.pdf", [FAX, NOTE])
    _, pages = parse.parse_document(pdf)
    results = parse.triage_case(pages, _ask)
    assert [p.triage_route for p in pages] == ["skip", "full"]
    assert pages[0].page_type == "fax_cover"
    rows = parse.audit_rows(pages, results)
    parse.write_audit(tmp_path / "audit.jsonl", rows)
    raw = (tmp_path / "audit.jsonl").read_text()
    for secret in ("TESTPATIENT", "neck pain", "Records Unit"):
        assert secret not in raw
    assert json.loads(raw.splitlines()[0])["text_sha256"] == parse.text_sha256(pages[0].text)


def test_duplicate_bates_labels_are_refused(tmp_path):
    a = _pdf(tmp_path / "TEST 000001-1 - a.pdf", [NOTE])
    b = _pdf(tmp_path / "TEST 000001-1 - b.pdf", [FAX])
    pages = parse.parse_document(a)[1] + parse.parse_document(b)[1]
    with pytest.raises(ValueError):
        parse.triage_case(pages, _ask)


# --- the case runner's guard ----------------------------------------------------

def test_jev_is_refused_for_a_real_case_without_zdr(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO / "scripts" / "case"))
    import triage_case
    monkeypatch.delenv("TYPESAFE_ZDR_CONFIRMED", raising=False)
    assert not triage_case.jev_allowed(tmp_path, zdr_flag=True)[0]       # flag alone is not enough
    monkeypatch.setenv("TYPESAFE_ZDR_CONFIRMED", "yes")
    assert not triage_case.jev_allowed(tmp_path, zdr_flag=False)[0]      # nor the variable alone
    assert triage_case.jev_allowed(tmp_path, zdr_flag=True)[0]
    monkeypatch.delenv("TYPESAFE_ZDR_CONFIRMED")
    (tmp_path / "SYNTHETIC").write_text("made up")
    assert triage_case.jev_allowed(tmp_path, zdr_flag=False)[0]


def test_generated_pages_are_well_formed_and_split_by_file():
    halves = {h: json.loads((REPO / f"scripts/jev/generated_{h}.json").read_text()) for h in ("tune", "test")}
    from chronology import triage
    from chronology.llm import jev
    for pages in halves.values():
        assert len(pages) >= 150
        for p in pages:
            assert p["label"] in jev.PAGE_TYPES and p["clinical"] in triage.CLINICAL_CONTENT
            # the only "SURNAME, FIRST" name anywhere is the made-up patient
            assert set(re.findall(r"[A-Z]{3,}, [A-Z]{3,}", p["text"])) <= {"TESTPATIENT, ALEX"}
    files = {h: {p["doc"] for p in pages} for h, pages in halves.items()}
    assert not files["tune"] & files["test"]
