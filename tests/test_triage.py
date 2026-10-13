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
