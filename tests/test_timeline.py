from helpers import ConstantChatClient, submit_reply

from chronology.agents.page_agent import extract_page
from chronology.schemas import Finding, Page
from chronology.stages.timeline import build_chronology, build_timeline, date_precision, render_markdown


def finding(fid, phrase, date, assertion="present", category="symptom", subject="patient"):
    return Finding(finding_id=fid, span_ids=[fid + "s"], category=category, original_phrase=phrase,
                   assertion=assertion, subject=subject, event_date=date)


def test_events_are_sorted_by_date_with_undated_last():
    events = build_timeline([finding("a", "later", "2024-05-16"), finding("b", "no date", None),
                             finding("c", "earlier", "2023-02-11"), finding("d", "middle", "2024-05-09")])
    assert [e.date for e in events] == ["2023-02-11", "2024-05-09", "2024-05-16", None]
    assert [e.date_precision for e in events] == ["day", "day", "day", "unknown"]


def test_same_fact_on_the_same_date_is_merged_and_keeps_every_source():
    events = build_timeline([finding("a", "Denies back pain", "2024-05-09", "absent"),
                             finding("b", "- denies back pain.", "2024-05-09", "absent"),
                             finding("c", "Denies back pain", "2024-05-16", "absent")])
    assert [e.finding_ids for e in events] == [["a", "b"], ["c"]]


def test_same_text_on_different_dates_or_categories_is_not_merged():
    events = build_timeline([finding("a", "Low back pain", "2024-05-16", category="symptom"),
                             finding("b", "Low back pain", "2024-05-16", category="diagnosis")])
    assert len(events) == 2


def test_merged_findings_that_disagree_are_flagged_as_a_conflict():
    events = build_timeline([finding("a", "Numbness", "2024-05-09", "present"),
                             finding("b", "numbness", "2024-05-09", "absent"),
                             finding("c", "Numbness", "2024-05-09", "present")])
    assert events[0].finding_ids == ["a", "b", "c"] and events[0].conflicts == ["b"]


def test_date_precision():
    assert [date_precision(d) for d in ("2024-05-09", "2024-05", "2024", None, "x")] == \
        ["day", "month", "year", "unknown", "unknown"]


def page_text(day, line):
    return f"Clinic\n\n**Date of Service:** {day}\n\n{line}\n"


def extraction(day, line, finding_text):
    page = Page(doc_id="d", page_index=0, bates_label="X 000001", text=page_text(day, line),
                text_source="native")
    reply = submit_reply([{"date": day, "role": "service_date"}],
                         [{"body": finding_text, "category": "symptom", "assertion": "present"}])
    return extract_page(page, ConstantChatClient(reply))


def test_chronology_joins_events_to_quotes_and_sorts_across_pages():
    later = extraction("05/16/2024", "Pt now c/o low back pain.", "Pt now c/o low back pain.")
    earlier = extraction("05/09/2024", "Pt reports wrist pain.", "Pt reports wrist pain.")
    rows = build_chronology([("records.md", "record", later), ("records.md", "record", earlier)])

    assert [r["date"] for r in rows] == ["2024-05-09", "2024-05-16"]
    assert rows[0]["quote"] == "Pt reports wrist pain."
    assert rows[0]["sources"][0]["file"] == "records.md"
    assert rows[0]["sources"][0]["bates_label"] == "X 000001"

    table = render_markdown("case_x", rows)
    assert "| 2024-05-09 |" in table and "Pt reports wrist pain." in table
