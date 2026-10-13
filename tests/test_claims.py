from pathlib import Path

from helpers import ConstantChatClient, submit_reply

from chronology.agents.page_agent import extract_page
from chronology.schemas import Page
from chronology.stages.claims import build_claims, claim_type, heading_before, render_claims_markdown

SUMMARY = Path(__file__).resolve().parent.parent / "sample_data" / "case_2" / "case_summary.md"
TEXT = SUMMARY.read_text()
PAGE = Page(doc_id="case_summary", page_index=0, text=TEXT, text_source="native")

DATES = [{"date": "05/09/2024", "role": "incident_date"},
         {"date": "07/15/2024", "role": "prepared_date"},
         {"date": "04/17/1985", "role": "dob"}]
TREATMENT_ROW = "| 05/09/2024 | Fairview Urgent Care — Dr. A. Mehta | Left wrist X-ray, fracture, splint |"
FINDINGS = [
    {"body": "Client was taken by ambulance to Fairview Urgent Care that afternoon.",
     "category": "history", "assertion": "present"},
    {"body": "Client denies any prior back problems.", "category": "history", "assertion": "absent"},
    {"body": "Lumbar strain with ongoing low back pain", "category": "symptom",
     "assertion": "present", "body_site": "lumbar"},
    {"body": TREATMENT_ROW, "category": "history", "assertion": "present"},  # code makes this one
]


def claims():
    extraction = extract_page(PAGE, ConstantChatClient(submit_reply(DATES, FINDINGS)))
    return build_claims("case_summary.md", extraction)


def test_section_headings_give_the_claim_type():
    assert claim_type("Facts of Incident") == "incident_fact"
    assert claim_type("Claimed Injuries") == "claimed_injury"
    assert claim_type("Prior Medical History") == "claimed_history"
    assert claim_type("Treatment Summary (per client and records received to date)") == "claimed_treatment"
    assert claim_type("Medical Specials (to date)") == "billed_amount"
    assert claim_type("Questions for Reviewing Physician") == "question"
    assert claim_type("Outstanding Records") == "outstanding_record"
    assert claim_type("Something else") == "other" and claim_type(None) == "other"


def test_heading_before_finds_the_nearest_heading_above():
    position = TEXT.index("Client denies any prior back problems.")
    assert heading_before(TEXT, position) == "Prior Medical History"


def test_every_claim_carries_the_date_it_was_claimed():
    result = claims()
    assert result and {c["claimed_on"] for c in result} == {"2024-07-15"}
    assert {c["status"] for c in result} == {"unchecked"}


def test_claims_have_a_type_and_the_date_they_are_about():
    by_quote = {c["quote"]: c for c in claims()}
    ambulance = by_quote["Client was taken by ambulance to Fairview Urgent Care that afternoon."]
    assert ambulance["type"] == "incident_fact" and ambulance["about_date"] == "2024-05-09"
    history = by_quote["Client denies any prior back problems."]
    assert history["type"] == "claimed_history" and history["about_date"] is None
    assert by_quote["Lumbar strain with ongoing low back pain"]["type"] == "claimed_injury"


def test_treatment_and_specials_rows_are_made_by_code_and_not_duplicated():
    result = claims()
    treatment = [c for c in result if c["type"] == "claimed_treatment"]
    assert [c["about_date"] for c in treatment] == ["2024-05-09", "2024-05-16", "2024-06-20"]
    assert [c["quote"] for c in result].count(TREATMENT_ROW) == 1
    billed = [c for c in result if c["type"] == "billed_amount"]
    assert any("$1,120.00" in c["quote"] for c in billed)
    assert all(c["about_date"] is None for c in billed)


def test_a_date_range_in_the_treatment_table_gives_start_and_end():
    text = "# Treatment Summary\n\n| Date | Provider | Summary |\n|---|---|---|\n" \
           "| 04/03/2024 – 05/15/2024 | Peak PT | 12 visits |\n"
    page = Page(doc_id="s", page_index=0, text=text, text_source="native")
    result = build_claims("s.md", extract_page(page, ConstantChatClient(submit_reply([], []))))
    assert (result[0]["about_date"], result[0]["about_date_end"]) == ("2024-04-03", "2024-05-15")


def test_markdown_shows_both_dates():
    table = render_claims_markdown("case_2", claims())
    assert "| About date | Claimed on |" in table
    assert "2024-07-15" in table and "2024-05-16" in table
