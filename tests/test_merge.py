from chronology.stages.merge import merge_views, render_merged_markdown


def evidence(event_id, date, quote="evidence text"):
    return {"event_id": event_id, "date": date, "date_precision": "day" if date else "unknown",
            "category": "symptom", "assertion": "present", "subject": "patient",
            "body_site": None, "quote": quote, "flags": [], "conflicts": [],
            "sources": [{"file": "records.md", "role": "record", "bates_label": "X 000001",
                         "page_index": 0, "char_start": 0, "char_end": 5,
                         "facility": "Clinic", "provider": "Dr A"}],
            "review_status": "pending"}


def claim(claim_id, about_date, quote="claim text", end=None, claimed_on="2024-07-15"):
    return {"claim_id": claim_id, "type": "incident_fact", "quote": quote, "assertion": None,
            "body_site": None, "about_date": about_date, "about_date_end": end, "flags": [],
            "claimed_on": claimed_on, "status": "unchecked",
            "source": {"file": "case_summary.md", "page_index": 0, "char_start": 0, "char_end": 5}}


def test_claims_and_evidence_are_interleaved_by_date_with_undated_last():
    rows = merge_views([evidence("e1", "2024-05-09"), evidence("e2", "2024-06-20"),
                        evidence("e3", None)],
                       [claim("c1", "2024-05-16"), claim("c2", None)])
    assert [(r["kind"], r["event_id"]) for r in rows] == [
        ("evidence", "e1"), ("claim", "c1"), ("evidence", "e2"), ("evidence", "e3"), ("claim", "c2")]


def test_on_the_same_date_evidence_comes_before_claims():
    rows = merge_views([evidence("e1", "2024-05-09")], [claim("c1", "2024-05-09")])
    assert [r["kind"] for r in rows] == ["evidence", "claim"]


def test_claims_keep_both_dates_and_stay_unchecked():
    row = merge_views([], [claim("c1", "2024-04-03", end="2024-05-15")])[0]
    assert (row["date"], row["about_date_end"], row["claimed_on"], row["status"]) == \
        ("2024-04-03", "2024-05-15", "2024-07-15", "unchecked")


def test_merging_leaves_the_inputs_unchanged():
    chronology, claims = [evidence("e1", "2024-05-09")], [claim("c1", "2024-05-09")]
    merge_views(chronology, claims)
    assert "kind" not in chronology[0] and "kind" not in claims[0]


def test_markdown_labels_each_row_and_shows_when_it_was_claimed():
    rows = merge_views([evidence("e1", "2024-05-09")],
                       [claim("c1", "2024-04-03", end="2024-05-15")])
    table = render_merged_markdown("case_x", rows)
    assert "| evidence |" in table and "| claim |" in table
    assert "2024-04-03 to 2024-05-15" in table and "2024-07-15" in table
    assert "1 evidence events and 1 claims" in table
