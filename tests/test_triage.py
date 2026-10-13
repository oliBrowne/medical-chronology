import json
from pathlib import Path

import pytest

from chronology import jev, triage


def test_admin_page_with_no_clinical_content_is_skipped():
    d = triage.route("fax_cover", 0.97, "no", 0.95)
    assert d.route == "skip"


def test_admin_page_with_clinical_content_is_read_in_full():
    d = triage.route("fax_cover", 0.97, "yes", 0.80)
    assert d.route == "full"


def test_low_confidence_admin_page_fails_open():
    assert triage.route("records_admin", 0.70, "no", 0.99).route == "full"
    assert triage.route("records_admin", 0.99, "no", 0.70).route == "full"


def test_clinical_page_types_are_never_skipped():
    for label in set(jev.PAGE_TYPES) - triage.SKIPPABLE_TYPES - triage.BILLING_TYPES:
        assert triage.route(label, 1.0, "no", 1.0).route == "full"


def test_billing_route_needs_both_keys():
    assert triage.route("billing", 0.95, "no", 0.95).route == "billing"
    assert triage.route("billing", 0.95, "yes", 0.95).route == "full"


def test_missing_answer_fails_open():
    assert triage.route(None, None, None, None).route == "full"


def test_duplicate_index_links_near_copies():
    index = triage.DuplicateIndex()
    base = ("Patient seen in clinic today for neck pain after a rear-end collision last week. "
            "Exam shows paraspinal tenderness and reduced rotation. Plan physical therapy twice weekly.")
    assert index.check_and_add("p1", base) is None
    assert index.check_and_add("p2", "FAX 03/22/2024 page 3 " + base) == "p1"
    assert index.check_and_add("p3", "MRI lumbar spine shows a small L4-L5 disc bulge without stenosis or root contact.") is None
    assert index.check_and_add("p4", "Page intentionally left blank.") is None
    assert index.check_and_add("p5", "Page intentionally left blank.") is None  # too short to call


def test_ece_is_zero_when_calibrated_and_positive_when_overconfident():
    assert triage.expected_calibration_error([1.0, 1.0], [True, True]) == pytest.approx(0)
    assert triage.expected_calibration_error([0.95] * 4, [True, False, True, False]) == pytest.approx(0.45)


def test_risk_coverage_reports_accuracy_on_covered_pages():
    rows = triage.risk_coverage([0.99, 0.6, 0.95], [True, False, True], [0.9])
    assert rows[0][1] == pytest.approx(2 / 3)
    assert rows[0][2] == pytest.approx(1.0)


def test_hard_pages_are_well_formed():
    pages = json.loads((Path(__file__).parents[1] / "scripts/jev/hard_pages.json").read_text())
    assert len({p["id"] for p in pages}) == len(pages)
    for p in pages:
        assert p["label"] in jev.PAGE_TYPES
        assert p["clinical"] in triage.CLINICAL_CONTENT
        assert p["text"].strip()


# --- triage_pages ----------------------------------------------------------

def _resp(page_type, tp, clinical="yes", cp=0.99, others=None):
    probs = {page_type: tp, **(others or {})}
    return {"answers": {"page_type": {"choice": page_type, "probabilities": probs},
                        "clinical": {"choice": clinical, "probabilities": {clinical: cp}}},
            "usage": {"input_tokens": 10}}


def _scripted(answers):
    """ask() that answers by the page marker found in [THIS PAGE]; a list of
    answers is consumed in order (first pass, then second pass)."""
    def ask(state, qs):
        this = state.split("[THIS PAGE]\n", 1)[1].split("\n\n[", 1)[0]
        a = answers[this]
        return a.pop(0) if isinstance(a, list) else a
    return ask


def test_unsure_page_borrows_confident_neighbor_type_but_cannot_be_skipped():
    pages = [{"id": "a", "doc": "d", "seq": 1, "text": "page A ed note"},
             {"id": "b", "doc": "d", "seq": 2, "text": "page B continuation"}]
    ask = _scripted({"page A ed note": _resp("ed_note", 0.98),
                     "page B continuation": _resp("fax_cover", 0.5, "no", 0.99, {"ed_note": 0.4})})
    res = {r.id: r for r in triage.triage_pages(pages, ask, jev.PAGE_TYPES)}
    assert res["b"].decision.page_type == "ed_note"
    assert res["b"].decision.type_source == "document"
    assert res["b"].decision.route == "full"


def test_second_pass_resolves_unsure_page():
    pages = [{"id": "a", "text": "lonely page"}]
    ask = _scripted({"lonely page": [_resp("other", 0.5, others={"lab_result": 0.45}),
                                     _resp("lab_result", 0.95)]})
    (r,) = triage.triage_pages(pages, ask, jev.PAGE_TYPES)
    assert r.decision.page_type == "lab_result"
    assert r.decision.type_source == "second_pass"
    assert r.calls == 2


def test_still_unsure_page_gets_full_read_without_hint():
    pages = [{"id": "a", "text": "mystery"}]
    ask = _scripted({"mystery": _resp("fax_cover", 0.6, "no", 0.99)})
    (r,) = triage.triage_pages(pages, ask, jev.PAGE_TYPES)
    assert r.decision.type_source == "none"
    assert r.decision.route == "full"


def test_keyword_backstop_stops_a_confident_skip():
    pages = [{"id": "a", "text": "FAX COVER. Comments: pt called reporting new numbness"}]
    ask = _scripted({pages[0]["text"]: _resp("fax_cover", 0.99, "no", 0.99)})
    (r,) = triage.triage_pages(pages, ask, jev.PAGE_TYPES)
    assert r.decision.route == "full"
    assert r.decision.reason.startswith("keyword")


def test_clean_admin_page_is_skipped():
    pages = [{"id": "a", "text": "FAX COVER SHEET To: Records From: Clinic Pages: 3"}]
    ask = _scripted({pages[0]["text"]: _resp("fax_cover", 0.99, "no", 0.99)})
    (r,) = triage.triage_pages(pages, ask, jev.PAGE_TYPES)
    assert r.decision.route == "skip"


def test_failed_call_fails_open():
    def ask(state, qs):
        raise RuntimeError("timeout")
    (r,) = triage.triage_pages([{"id": "a", "text": "anything"}], ask, jev.PAGE_TYPES)
    assert r.decision.route == "full"
    assert r.error


def test_safety_nets():
    assert triage.clinical_keyword("Dx: S16.1XXA") == "S16.1XXA"
    assert triage.clinical_keyword("Ibuprofen 600 mg") == "600 mg"
    assert triage.clinical_keyword("Number of pages including cover: 3") is None
    assert triage.text_quality("a clean line of text") == 1.0
    assert triage.text_quality("n~ois|y ^text `here") < triage.MIN_TEXT_QUALITY


def test_glance_keeps_top_and_last_lines():
    text = "HEADER LINE\n" + "\n".join(f"middle line {i} with some words" for i in range(40)) + "\nLAST LINE"
    g = triage.glance_text(text, bottom_lines=1)
    assert g.startswith("HEADER LINE") and g.endswith("LAST LINE")
    assert "middle of page not shown" in g and len(g) < len(text) / 2
    assert triage.glance_text("short page") == "short page"
    top = triage.glance_text(text, bottom_lines=0)
    assert top.startswith("HEADER LINE") and "LAST LINE" not in top


def test_glance_confirms_on_full_page_before_skipping():
    middle = "\n".join(f"routing detail number {i} for records" for i in range(30))
    text = "FAX COVER SHEET\nTo: Records\n" + middle + "\nComments: pt reports new numbness\nCONFIDENTIAL"
    seen = []

    def ask(state, qs):
        seen.append(state)
        full = "numbness" in state.split("[THIS PAGE]\n", 1)[1]
        clinical = ("yes", 1.0) if full else ("no", 0.99)
        return {"answers": {"page_type": {"choice": "fax_cover", "probabilities": {"fax_cover": 0.99}},
                            "clinical": {"choice": clinical[0], "probabilities": {clinical[0]: clinical[1]}}}}

    (r,) = triage.triage_pages([{"id": "a", "text": text}], ask, jev.PAGE_TYPES,
                               glance=True, use_safety_nets=False)
    assert r.confirmed and len(seen) == 2
    assert r.decision.route == "full"


def test_boilerplate_does_not_make_pages_duplicates():
    footer = "\n".join(f"This production notice line {i} is printed on every page of the set." for i in range(12))
    pages = [{"id": f"p{i}", "text": f"Visit {i}: patient reports neck pain level {i}, exam note {i * 7}.\n{footer}"}
             for i in range(10)]

    def ask(state, qs):
        return {"answers": {"page_type": {"choice": "office_visit", "probabilities": {"office_visit": 0.99}},
                            "clinical": {"choice": "yes", "probabilities": {"yes": 0.99}}}}

    res = triage.triage_pages(pages, ask, jev.PAGE_TYPES, use_templates=True)
    assert not any(r.decision.route == "duplicate" for r in res)
    assert not any(r.decision.type_source == "template" for r in res)


def test_keyword_catches_bare_order_line():
    assert triage.clinical_keyword("Fax cover sheet\nPages: 3\nMRI ordered") == "MRI"
    assert triage.clinical_keyword("Fax cover sheet\nPages: 3\nPlease call to confirm") is None
