"""Regression tests for the code-review findings fixed with v7, each built
from the failing example in the review."""

from chronology import jev, readers, triage


def _resp(page_type, tp, clinical="yes", cp=0.99):
    return {"answers": {"page_type": {"choice": page_type, "probabilities": {page_type: tp}},
                        "clinical": {"choice": clinical, "probabilities": {clinical: cp}}},
            "usage": {"input_tokens": 10}}


LONG_FAX = ("FAX COVER SHEET\nTo: Records Unit\nFrom: Example Clinic\nPages: 4\n"
            + "\n".join(f"Routing line {i}: this transmission is intended only for the named recipient."
                        for i in range(30)))


def test_failed_confirm_does_not_create_a_template():
    """Glance says fax cover / no clinical, the full-page check times out: the
    next copy of the form must not be skipped on that glance answer."""
    def ask(state, qs):
        if "Routing line 29" in state:   # only the full page reaches the bottom
            raise TimeoutError("confirm timed out")
        return _resp("fax_cover", 0.99, "no", 0.99)
    second = LONG_FAX.replace("From: Example Clinic", "From: Northside Imaging Group Records Office Annex")
    pages = [{"id": "p1", "doc": "d", "seq": 1, "text": LONG_FAX},
             {"id": "p2", "doc": "d", "seq": 2, "text": second}]
    res = {r.id: r for r in triage.triage_pages(pages, ask)}
    assert res["p2"].decision.route != "duplicate"   # the test needs a second form, not a copy
    assert res["p1"].decision.route == "full"
    assert res["p2"].decision.type_source != "template"


def test_reader_types_keep_the_normal_bar():
    taus = triage.clinical_type_thresholds(jev.PAGE_TYPES_EXTENDED)
    assert "lab_result" not in taus and "medication_record" not in taus and "billing" not in taus
    assert taus["office_visit"] == triage.CLINICAL_TYPE_THRESHOLD


def test_glance_typed_medication_page_is_checked_on_the_full_page():
    """A medication list whose lower part has a clinician's comment: in glance
    mode the type comes from the top only, so the page is asked again whole."""
    rows = "\n".join(f"0{i % 9 + 1}/0{i % 9 + 1}/2024  ibuprofen 600 mg  #30" for i in range(40))
    text = "MEDICATION LIST\n" + rows + "\nPatient tolerating this regimen poorly per spouse, wants to stop"
    states = []

    def ask(state, qs):
        states.append(state)
        return _resp("medication_record", 0.99, "yes", 0.99)
    triage.triage_pages([{"id": "m", "text": text}], ask)
    assert any("wants to stop" in s for s in states)   # the full page was sent at least once


def test_inherited_run_page_with_written_text_is_not_read_by_a_table_reader():
    line = "DOS 03/21/2024  99213 Office visit  $145.00"
    text = "EXAMPLE ORTHOPEDICS STATEMENT\n" + "\n".join([line] * 6) + \
           "\nPatient seen for follow-up today and doing better with the home program"
    strict = readers.read_table(text, "billing", strict=True)
    assert not strict.accepted
    assert readers.read_table(text, "billing").accepted   # a page Jev typed itself may still use it


def test_field_labels_are_not_bates_stamps():
    page = "PRESCRIPTION\nMRN 1234567\nRX 123456\nDOB 01151980\nACCT 00012345\nTEST 000123"
    assert triage.clean_for_jev(page) == "PRESCRIPTION\nMRN 1234567\nRX 123456\nDOB 01151980\nACCT 00012345"


def test_changed_dose_is_not_a_duplicate():
    meds = "\n".join(f"Medication line {i}: continue as directed by the treating physician" for i in range(12))
    first = meds + "\nOxycodone 5 mg every six hours as needed"
    index = triage.DuplicateIndex()
    assert index.check_and_add("a", first) is None
    assert index.check_and_add("b", first.replace("5 mg", "50 mg")) is None


def test_code_first_charge_line_without_date_or_amount_is_a_row():
    text = ("STATEMENT\nDates of service 04/02/24\n99213 Office visit  $145.00\n97140 Manual therapy  $80.00\n"
            "97110 Therapeutic exercise x2")
    table = readers.read_table(text, "billing")
    assert table.accepted
    assert any("97110" in r.codes for r in table.rows if r.kind == "billing")
    zip_row = readers._row("billing", 0, 21, "Springfield, IL 62704")
    assert zip_row is None
