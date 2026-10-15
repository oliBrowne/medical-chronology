import json
from pathlib import Path

from helpers import ConstantChatClient, submit_reply

from chronology.pipeline import case_files, file_role, run_case

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
