from chronology.schemas import Page
from chronology.stages.tables import find_tables, vital_findings, vital_table_rows

TEXT = """Intro line

| Vital | Value |
|---|---|
| BP | 136/84 |
| Temp | 98.2 F |

Between tables

| Intervention | Time |
|---|---|
| Moist heat | 10 min |

| Plain | Row |
| no | header |
"""


def test_tables_are_split_into_header_and_data_rows():
    vitals, interventions, headerless = find_tables(TEXT)
    assert vitals.header == ("Vital", "Value")
    assert [r.cells for r in vitals.rows] == [("BP", "136/84"), ("Temp", "98.2 F")]
    assert interventions.header == ("Intervention", "Time")
    assert headerless.header == () and len(headerless.rows) == 2


def test_row_offsets_point_at_the_exact_row_text():
    for table in find_tables(TEXT):
        for row in table.rows:
            assert TEXT[row.start:row.end] == row.text


def test_only_vital_tables_are_picked_up():
    assert [r.text for r in vital_table_rows(TEXT)] == ["| BP | 136/84 |", "| Temp | 98.2 F |"]


def test_vital_findings_quote_the_row_as_printed():
    page = Page(doc_id="d", page_index=0, bates_label="X 000001", text=TEXT, text_source="native")
    spans, findings = vital_findings(page, "2024-05-09", "2024-05-10")
    assert [s.quote for s in spans] == ["| BP | 136/84 |", "| Temp | 98.2 F |"]
    assert all(f.category == "vital" and f.assertion == "present" for f in findings)
    assert findings[0].event_date == "2024-05-09" and findings[0].document_date == "2024-05-10"
    assert TEXT[spans[0].char_start:spans[0].char_end] == spans[0].quote


def test_text_without_tables_gives_nothing():
    assert find_tables("just a sentence | with a pipe in it") == []
