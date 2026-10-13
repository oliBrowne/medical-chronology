import json
from pathlib import Path

from chronology import jev, readers, triage

PAGES = {p["id"]: p for p in json.loads(
    (Path(__file__).parents[1] / "scripts/jev/efficiency_pages.json").read_text())}


def test_table_reader_quotes_are_verbatim_slices():
    text = PAGES["eff-12"]["text"]
    table = readers.read_table(text, "medication_record")
    assert table.accepted
    for row in table.rows:
        assert text[row.char_start:row.char_end] == row.quote


def test_table_reader_reads_billing_codes_and_diagnoses():
    text = "DOS 03/21/2024  99213 Office visit  $145.00\nDOS 03/21/2024  Dx: S16.1XXA"
    rows = readers.read_table(text, "billing").rows
    assert rows[0].codes == ["99213"] and rows[0].amount == "$145.00"
    assert rows[1].diagnoses == ["S16.1XXA"]


def test_table_reader_refuses_narrative():
    assert not readers.read_table(PAGES["eff-14"]["text"], "medication_record").accepted
    assert not readers.read_table(PAGES["eff-15"]["text"], "lab_result").accepted
    assert not readers.read_table("Anything", "office_visit").accepted


def test_copy_forward_reads_only_new_lines():
    memory = readers.LineMemory()
    first, second = PAGES["eff-06"]["text"], PAGES["eff-08"]["text"]
    memory.add(first)
    cf = memory.diff(second)
    new = "\n".join(second[s:e] for s, e in cf.new_spans)
    assert cf.worth_it
    assert "new tingling in left thumb" in new
    assert "Paraspinal tenderness" not in new


def test_reader_model():
    assert readers.reader_model("lab_result", 500) == "small"
    assert readers.reader_model("lab_result", 5000) == "large"
    assert readers.reader_model("office_visit", 500) == "large"
    assert readers.reader_model(None, 100) == "large"


def _ask_by_marker(table):
    def ask(state, qs):
        this = state.split("[THIS PAGE]\n", 1)[1].split("\n\n[", 1)[0]
        page_type, clinical = next(v for k, v in table.items() if k in this)
        return {"answers": {"page_type": {"choice": page_type, "probabilities": {page_type: 0.99}},
                            "clinical": {"choice": clinical, "probabilities": {clinical: 0.99}}},
                "usage": {"input_tokens": 1}}
    ask.calls = 0
    return ask


def test_template_reuse_skips_jev_but_not_a_page_with_a_clinical_comment():
    pages = [dict(PAGES[i]) for i in ("eff-09", "eff-10", "eff-11")]
    calls = []
    inner = _ask_by_marker({"FAX COVER": ("fax_cover", "no")})

    def ask(state, qs):
        calls.append(state)
        return inner(state, qs)

    res = {r.id: r for r in triage.triage_pages(pages, ask, jev.PAGE_TYPES, use_templates=True)}
    assert res["eff-10"].decision.type_source == "template"
    assert res["eff-10"].decision.route == "skip"
    assert res["eff-11"].decision.route == "full"   # new comment line: no reuse, keyword net
    assert len(calls) == 2


def test_billing_run_inherits_and_goes_to_table_reader():
    pages = [dict(PAGES[f"eff-0{i}"]) for i in range(1, 6)]
    calls = []
    inner = _ask_by_marker({"ITEMIZED": ("billing", "no")})

    def ask(state, qs):
        calls.append(state)
        return inner(state, qs)

    res = triage.triage_pages(pages, ask, jev.PAGE_TYPES, use_runs=True, use_readers=True)
    assert [r.decision.type_source for r in res] == ["direct", "direct", "run", "run", "run"]
    assert all(r.decision.route == "reader" for r in res)
    assert len(calls) == 2
