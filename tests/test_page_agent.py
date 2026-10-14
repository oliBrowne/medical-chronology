from chronology.agents.page_agent import extract_page
from chronology.schemas import Page

TEXT = """Fairview Urgent Care

**Date of Service:** 05/09/2024

Pt reports left wrist pain 7/10 with swelling. Denies back pain.

| Vital | Value |
|---|---|
| BP | 136/84 |
| HR | 84 |

R wrist: Normal

Electronically signed: A. Mehta, MD 05/10/2024 08:05"""

PAGE = Page(doc_id="d", page_index=0, bates_label="X 000001", text=TEXT, text_source="native")
DATES = [{"date": "05/09/2024", "role": "service_date"},
         {"date": "05/10/2024", "role": "signature"}]


def finding(body, category="symptom", assertion="present", **extra):
    return {"body": body, "category": category, "assertion": assertion, **extra}


def submit(findings, dates=DATES):
    call = {"function": {"name": "submit_page",
                         "arguments": {"dates": dates, "findings": findings}}}
    return {"role": "assistant", "content": "", "tool_calls": [call]}


def fake_model(*replies):
    queue = iter(replies)
    return lambda messages, **kwargs: next(queue)


GOOD = [finding("left wrist pain 7/10 with swelling"),
        finding("Denies back pain", assertion="absent")]
BAD = finding("a paraphrase that is not on the page")
TEXT_ONLY = {"role": "assistant", "content": "done"}


def test_valid_findings_survive_when_one_is_rejected_and_never_fixed():
    result = extract_page(PAGE, chat_fn=fake_model(submit(GOOD + [BAD]), TEXT_ONLY, TEXT_ONLY))
    assert result.status == "partial"
    quotes = [s.quote for s in result.spans]
    assert "left wrist pain 7/10 with swelling" in quotes and "Denies back pain" in quotes
    assert not any("paraphrase" in q for q in quotes)
    assert any("rejected and not corrected" in u for u in result.unresolved)


def test_a_corrected_item_is_added_without_duplicating_the_accepted_ones():
    fixed = finding("R wrist: Normal", category="exam_finding")
    result = extract_page(PAGE, chat_fn=fake_model(submit(GOOD + [BAD]),
                                                   submit([fixed]),
                                                   ))
    assert result.status == "finished"
    quotes = [s.quote for s in result.spans]
    assert quotes.count("left wrist pain 7/10 with swelling") == 1
    assert "R wrist: Normal" in quotes


def test_resending_everything_does_not_duplicate_findings():
    result = extract_page(PAGE, chat_fn=fake_model(submit(GOOD + [BAD]), submit(GOOD)))
    assert [s.quote for s in result.spans].count("Denies back pain") == 1


def test_vital_table_rows_come_from_code_and_overlapping_model_findings_are_dropped():
    from_model = finding("| BP | 136/84 |", category="vital")
    result = extract_page(PAGE, chat_fn=fake_model(submit(GOOD + [from_model])))
    assert result.status == "finished"
    vitals = [(s.quote, f.category) for s, f in zip(result.spans, result.findings)
              if f.category == "vital"]
    assert vitals == [("| BP | 136/84 |", "vital"), ("| HR | 84 |", "vital")]
    starts = [s.char_start for s in result.spans]
    assert starts == sorted(starts)  # findings are in page order


def test_nothing_accepted_and_no_finish_is_a_failure_with_no_findings():
    result = extract_page(PAGE, chat_fn=fake_model(TEXT_ONLY, TEXT_ONLY))
    assert result.status == "no_tool_call" and result.findings == []


def test_event_date_comes_from_the_service_date_not_the_signature():
    result = extract_page(PAGE, chat_fn=fake_model(submit(GOOD)))
    assert {f.event_date for f in result.findings} == {"2024-05-09"}
    assert {f.document_date for f in result.findings} == {"2024-05-10"}
