from chronology.schemas import EvidenceSpan, Finding, Page
from chronology.stages.flags import check_finding, uncovered_lines

PAGE = ("Pt reports numbness. No numbness or weakness.\n"
        "R wrist: Normal\n"
        "PMH: None\nMedications: None\n"
        "L-spine: TTP L4-L5 paraspinals bilat, SLR neg bilat, flexion limited to 60 deg")


def finding(assertion="present", site=None):
    return Finding(finding_id="f", span_ids=["s"], category="symptom", original_phrase="x",
                   assertion=assertion, body_site=site)


def rules(f, quote, page=PAGE):
    return [flag["rule"] for flag in check_finding(f, quote, page)]


def test_negation_word_in_present_finding_is_flagged():
    assert "negation_vs_assertion" in rules(finding("present"), "No numbness or weakness.")


def test_absent_without_negation_word_is_flagged():
    assert "negation_vs_assertion" in rules(finding("absent"), "flexion limited to 60 deg")


def test_consistent_labels_are_not_flagged():
    assert rules(finding("absent"), "SLR neg bilat") == []
    assert rules(finding("present"), "R wrist: Normal") == []


def test_laterality_mismatch_is_flagged():
    assert "laterality" in rules(finding(site="left wrist"), "R wrist: Normal")


def test_laterality_matching_or_missing_is_not_flagged():
    assert "laterality" not in rules(finding(site="right wrist"), "R wrist: Normal")
    assert "laterality" not in rules(finding(site=None), "R wrist: Normal")


def test_l_spine_and_vertebra_names_are_not_read_as_left():
    assert "laterality" not in rules(finding(site="right shoulder"), "L-spine: TTP L4-L5")


def test_single_word_quote_is_flagged():
    assert "weak_quote" in rules(finding(), "Normal")


def test_quote_that_appears_twice_is_flagged():
    flags = check_finding(finding(), "None", PAGE)
    assert any(f["rule"] == "weak_quote" and "2 times" in f["detail"] for f in flags)


def test_comma_list_is_flagged_as_possibly_several_facts():
    quote = "TTP L4-L5 paraspinals bilat, SLR neg bilat, flexion limited to 60 deg"
    assert "multi_fact" in rules(finding("present"), quote)


def test_single_fact_is_not_flagged_as_multi_fact():
    assert "multi_fact" not in rules(finding(), "R wrist: Normal")


COVERAGE_PAGE = """Fairview Urgent Care

# URGENT CARE NOTE

**Patient:** BELL, MARCUS T **DOB:** 04/17/1985
**Date of Service:** 05/09/2024 **Provider:** A. Mehta, MD

## Physical Exam

| Vital | Value |
|---|---|
| BP | 136/84 |

General: NAD, A&O x3
R wrist: Normal
Back: No TTP thoracic or lumbar spine

Electronically signed: A. Mehta, MD 05/10/2024 08:05

BELL 000101"""


def covering(text):
    start = COVERAGE_PAGE.index(text)
    return EvidenceSpan(span_id="s", doc_id="d", page_index=0, char_start=start,
                        char_end=start + len(text), quote=text)


def uncovered(*covered_texts):
    page = Page(doc_id="d", page_index=0, text=COVERAGE_PAGE, text_source="native")
    dates = [{"text": "05/09/2024"}, {"text": "04/17/1985"}]
    return [u["text"] for u in uncovered_lines(
        page, [covering(t) for t in covered_texts], dates, "Fairview Urgent Care")]


def test_headings_dates_stamps_and_header_fields_are_not_reported():
    reported = uncovered()
    assert reported == ["| BP | 136/84 |", "General: NAD, A&O x3", "R wrist: Normal",
                        "Back: No TTP thoracic or lumbar spine"]


def test_a_finding_covers_its_line():
    reported = uncovered("R wrist: Normal", "No TTP thoracic or lumbar spine")
    assert "R wrist: Normal" not in reported
    assert "Back: No TTP thoracic or lumbar spine" not in reported
    assert "General: NAD, A&O x3" in reported


def test_dropped_vitals_row_is_reported():
    assert "| BP | 136/84 |" in uncovered("R wrist: Normal")
