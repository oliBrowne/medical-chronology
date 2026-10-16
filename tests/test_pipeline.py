import json
from pathlib import Path

import pytest
from helpers import ConstantChatClient, submit_reply

from chronology.pipeline import case_files, file_role, run_case, triage_asker
from chronology.stages.parse import parse_markdown

RECORDS = """Clinic

**Date of Service:** 05/09/2024

Pt reports wrist pain.

BELL 000101

{1}------------------------------------------------

Clinic

**Date of Service:** 05/16/2024

Pt reports back pain.

BELL 000102
"""
INCIDENT = "Store\n\n# INCIDENT REPORT\n\n| HFM-1 | 05/09/2024 | 14:15 |\n\nCustomer slipped.\n"
SUMMARY = "# CASE SUMMARY\n\nClient denies prior back problems.\n"


def make_case(tmp_path: Path) -> Path:
    case = tmp_path / "case_x"
    case.mkdir()
    (case / "medical_records.md").write_text(RECORDS)
    (case / "incident_report.md").write_text(INCIDENT)
    (case / "case_summary.md").write_text(SUMMARY)
    (case / "README.md").write_text("notes about the case, not a case file")
    (case / "expected_output.json").write_text("{}")
    return case


def empty_submission():
    """A model that submits nothing for every page."""
    return ConstantChatClient(submit_reply([], []))


def test_roles_come_from_the_file_name():
    assert file_role(Path("medical_records.md")) == "record"
    assert file_role(Path("incident_report.md")) == "incident"
    assert file_role(Path("police_crash_report.md")) == "incident"
    assert file_role(Path("case_summary.md")) == "claims"
    assert file_role(Path("Presbyterian recs.md")) == "record"


def test_every_markdown_file_is_found_except_readmes_and_non_markdown(tmp_path):
    names = [p.name for p in case_files(make_case(tmp_path))]
    assert names == ["case_summary.md", "incident_report.md", "medical_records.md"]


def test_all_files_are_read_and_each_gets_its_role(tmp_path):
    case = make_case(tmp_path)
    path = run_case(case, tmp_path / "out", client=empty_submission())
    data = json.loads(path.read_text())

    sources = {s["path"]: s for s in data["sources"]}
    assert set(sources) == {"case_summary.md", "incident_report.md", "medical_records.md"}
    assert all(s["processed"] for s in sources.values())
    assert sources["medical_records.md"]["page_count"] == 2

    pages = [(p["file"], p["role"], p["bates_label"]) for p in data["pages"]]
    assert pages == [("case_summary.md", "claims", None),
                     ("incident_report.md", "incident", None),
                     ("medical_records.md", "record", "BELL 000101"),
                     ("medical_records.md", "record", "BELL 000102")]


def test_claims_and_evidence_go_to_separate_files(tmp_path):
    case = make_case(tmp_path)
    folder = run_case(case, tmp_path / "out", client=empty_submission()).parent
    assert {p.name for p in folder.iterdir()} == {
        "pages.json", "chronology.json", "chronology.md", "claims.json", "claims.md",
        "merged.json", "merged.md"}
    assert json.loads((folder / "chronology.json").read_text())["case"] == "case_x"
    assert json.loads((folder / "claims.json").read_text())["claims"] == []
    assert json.loads((folder / "merged.json").read_text())["rows"] == []


FAX = "FAX COVER SHEET\n\nTo: Records Department\nFrom: Example Clinic\nPages: 3\n\nBELL 000100\n"


def fax_sorting_ask(state: str, questions: dict) -> dict:
    """Stand-in for Jev: the fax cover is an admin page with no clinical content,
    every other page is a clinical note that starts a document."""
    page = state.split("[THIS PAGE]\n", 1)[-1]
    fax = "FAX COVER" in page

    def pick(criteria: dict) -> str:
        for want in (("fax_cover", "no") if fax else ("progress_note", "yes", "notes")):
            if want in criteria:
                return want
        return next(iter(criteria))

    return {"answers": {name: {"choice": (c := pick(q["criteria"])), "probabilities": {c: 0.99}}
                        for name, q in questions.items()}}


def test_triage_holds_back_admin_pages_and_lists_them_without_text(tmp_path):
    case = make_case(tmp_path)
    records = case / "medical_records.md"
    records.write_text(FAX + "\n{0}------------------------------------------------\n\n" + RECORDS)
    data = json.loads(run_case(case, tmp_path / "out", client=empty_submission(),
                               triage_ask=fax_sorting_ask).read_text())

    read = [p["bates_label"] for p in data["pages"] if p["file"] == "medical_records.md"]
    assert read == ["BELL 000101", "BELL 000102"]
    routes = {row["page_id"]: row["route"] for row in data["triage"]}
    assert routes["BELL 000100"] == "skip"
    assert routes["BELL 000101"] == routes["BELL 000102"] == "full"
    assert all("text" not in row for row in data["triage"])
    assert {p["role"] for p in data["pages"]} == {"claims", "incident", "record"}  # the summary is never triaged


def test_code_only_triage_reads_every_page(tmp_path):
    case = make_case(tmp_path)
    ask = triage_asker("code", case, zdr_confirmed=False)
    data = json.loads(run_case(case, tmp_path / "out", client=empty_submission(), triage_ask=ask).read_text())
    assert len(data["pages"]) == 4
    assert {row["route"] for row in data["triage"]} == {"full"}


def test_jev_triage_is_refused_on_a_real_case(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_ZDR_CONFIRMED", raising=False)
    case = make_case(tmp_path)
    assert triage_asker("off", case, zdr_confirmed=True) is None
    with pytest.raises(SystemExit):
        triage_asker("jev", case, zdr_confirmed=True)


def test_windows_line_endings_still_split_pages(tmp_path):
    path = tmp_path / "medical_records.md"
    path.write_bytes(RECORDS.replace("\n", "\r\n").encode("utf-8"))
    _, pages = parse_markdown(path)
    assert [p.bates_label for p in pages] == ["BELL 000101", "BELL 000102"]
