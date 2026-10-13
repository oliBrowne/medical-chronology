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
    assert index.check_and_add("p2", "COPY\n" + base) == "p1"
    # a stamp line is removed before the check (clean_for_jev), so it never counts
    assert index.check_and_add("p2b", triage.clean_for_jev("04/22/2024 09:14 FROM 555-0100 FAX P.003\n" + base)) == "p1"
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


def test_clean_for_jev_drops_stamps_but_keeps_content():
    text = ("04/02/2024 14:22 FROM 555-0100 TO 555-0199 P.003\nOFFICE VISIT\n"
            "Neck pain since the collision.\nPage 3 of 12\nEXM0001234")
    clean = triage.clean_for_jev(text)
    assert clean == "OFFICE VISIT\nNeck pain since the collision."
    assert triage.clean_for_jev("Page 1 of 1") == "Page 1 of 1"   # never empties a page


def test_three_way_clinical_answer_maps_to_yes_no():
    resp = {"answers": {"clinical": {"choice": "table",
                                     "probabilities": {"notes": 0.3, "table": 0.65, "no": 0.05}}}}
    c, cp, kind, kp = triage._clinical_answer(resp)
    assert (c, kind) == ("yes", "table") and cp == pytest.approx(0.95) and kp == 0.65


def _fixed(page_type, p, clinical="yes", position=None, pos_p=0.99, seen=None):
    def ask(state, qs):
        if seen is not None:
            seen.append(state)
        page = state.split("[THIS PAGE]\n", 1)[1]
        t, tp = page_type(page) if callable(page_type) else (page_type, p)
        out = {"page_type": {"choice": t, "probabilities": {t: tp, "other": 1 - tp}},
               "clinical": {"choice": clinical, "probabilities": {clinical: 0.99}}}
        if "position" in qs:
            pos = position(page) if callable(position) else position
            out["position"] = {"choice": pos, "probabilities": {pos: pos_p}}
        return {"answers": out}
    return ask


def test_continuation_borrows_previous_type_only_when_confident():
    pages = [{"id": "a", "doc": "d", "seq": 1, "text": "PHYSICAL THERAPY DAILY NOTE\ncervical ROM improved"},
             {"id": "b", "doc": "d", "seq": 2, "text": "tolerated exercises, plan continue 2x weekly"}]
    page_type = lambda page: ("therapy_note", 0.97) if "THERAPY" in page else ("other", 0.5)
    position = lambda page: "starts" if "THERAPY" in page else "continues"
    res = triage.triage_pages(pages, _fixed(page_type, None, position=position), jev.PAGE_TYPES,
                              use_second_pass=False, ask_position=True)
    b = next(r for r in res if r.id == "b")
    assert b.decision.page_type == "therapy_note" and b.decision.type_source == "document"
    assert b.decision.route == "full"   # a borrowed type is a hint only


def test_written_notes_never_go_to_a_table_reader():
    text = "MEDICATION LIST\nibuprofen 600 mg tid\ncyclobenzaprine 10 mg qhs\ntizanidine 2 mg qhs"

    def ask(state, qs):
        detailed = "notes" in qs["clinical"]["criteria"]
        c = "notes" if detailed else "yes"
        return {"answers": {"page_type": {"choice": "medication_record",
                                          "probabilities": {"medication_record": 0.99}},
                            "clinical": {"choice": c, "probabilities": {c: 0.97}}}}

    (plain,) = triage.triage_pages([{"id": "a", "text": text}], ask, jev.PAGE_TYPES, split_clinical=False)
    (split,) = triage.triage_pages([{"id": "a", "text": text}], ask, jev.PAGE_TYPES, use_readers=True,
                                   split_clinical=True)
    assert plain.decision.route == "reader" and split.decision.route == "full"


def test_same_header_reuses_type_with_spot_checks():
    head = "RIVERSIDE PHYSICAL THERAPY\nDaily Treatment Note"
    pages = [{"id": f"p{i}", "doc": "d", "seq": i,
              "text": f"{head}\nVisit {i}: worked on {['lifting', 'posture', 'range', 'gait', 'balance', 'core'][i]} drills"}
             for i in range(6)]
    pages += [{"id": f"x{i}", "doc": f"x{i}", "text": f"unrelated page {i}"} for i in range(8)]
    seen = []
    res = triage.triage_pages(pages, _fixed("therapy_note", 0.98, seen=seen), jev.PAGE_TYPES,
                              use_headers=True)
    reused = [r for r in res if r.decision.type_source == "header"]
    # p0 asked; p1-p3 reuse its type; p4 is the spot check (asked); p5 reuses
    assert [r.id for r in reused] == ["p1", "p2", "p3", "p5"]
    assert len(seen) == len(pages) - 4
    assert all(r.decision.page_type == "therapy_note" and r.decision.route == "full" for r in reused)


def test_same_header_never_reuses_a_skippable_type():
    head = "RECORDS DEPARTMENT\nRequest for records"
    pages = [{"id": f"p{i}", "doc": "d", "seq": i, "text": f"{head}\nRequest number {i} item {'abcdef'[i]}"}
             for i in range(4)]
    pages += [{"id": f"x{i}", "doc": f"x{i}", "text": f"unrelated page {i}"} for i in range(8)]
    seen = []
    triage.triage_pages(pages, _fixed("records_admin", 0.98, clinical="no", seen=seen), jev.PAGE_TYPES,
                        glance=False)
    assert len(seen) == len(pages)


def test_jev_cleaning_keeps_a_documents_own_letterhead():
    head = "EXAMPLE SPINE CLINIC - ITEMIZED STATEMENT"
    texts = [f"{head}\ncharge line {i}" for i in range(6)] + ["Production notice\nother"] * 6
    docs = ["bill"] * 6 + [f"d{i}" for i in range(6)]
    bp = triage.boilerplate_lines(texts, 0.5, docs=docs, min_docs=3)
    assert triage.norm_line(head) not in bp and "production notice" in bp


def test_heldout_pages_are_well_formed():
    pages = json.loads((Path(__file__).parents[1] / "scripts/jev/heldout_pages.json").read_text())
    assert len({p["id"] for p in pages}) == len(pages)
    for p in pages:
        assert p["label"] in jev.PAGE_TYPES
        assert p["clinical"] in triage.CLINICAL_CONTENT
        assert p["text"].strip()

def test_longer_page_containing_a_short_one_is_not_its_duplicate():
    index = triage.DuplicateIndex()
    stub = "EMERGENCY DEPARTMENT PHYSICIAN RECORD Example General Hospital arrival by private vehicle"
    assert index.check_and_add("p1", stub) is None
    note = stub + (" Chief complaint neck pain after collision. Exam paraspinal tenderness. "
                   "Impression cervical strain. Discharged with ibuprofen.")
    assert index.check_and_add("p2", note) is None


def test_copy_with_an_added_clinical_word_is_not_a_duplicate():
    index = triage.DuplicateIndex()
    base = ("Physical therapy daily note. Exercises completed as planned: chin tucks, rows, "
            "wall angels, thoracic extension. Next visit Thursday.")
    assert index.check_and_add("p1", base) is None
    assert index.check_and_add("p2", base + " Swelling noted.") is None


def test_stamp_cleaning_keeps_clinical_lines():
    for line in ["04/02/2024 14:22 Report given to RN, P 88 irregular", "Tylenol 1000",
                 "Page 2: pain worse at night"]:
        assert triage.clean_for_jev("HEADER\n" + line) == "HEADER\n" + line


def _glance_aware(page_type, hidden_word):
    """Jev stand-in that only sees ``hidden_word`` when it reads the full page."""
    def ask(state, qs):
        page = state.split("[THIS PAGE]\n", 1)[1]
        c = "yes" if hidden_word in page else "no"
        return {"answers": {"page_type": {"choice": page_type, "probabilities": {page_type: 0.99}},
                            "clinical": {"choice": c, "probabilities": {c: 0.99}}}}
    return ask


def test_glance_template_is_confirmed_on_the_full_page_first():
    middle = "\n".join(f"routing detail number {i} for the records office" for i in range(30))
    form = "RECORDS RELEASE FORM\nRequester: Example Law Group\n" + middle
    pages = [{"id": "a", "doc": "a", "text": form + "\nHANDWRITTEN: zzclinical"},
             {"id": "b", "doc": "b", "text": form + "\nsigned"}]
    res = {r.id: r for r in triage.triage_pages(pages, _glance_aware("records_admin", "zzclinical"),
                                                use_safety_nets=False)}
    assert res["a"].confirmed and res["a"].decision.route == "full"
    assert res["b"].decision.type_source != "template"


def test_glance_confirms_billing_when_no_table_reader_checks_it():
    middle = "\n".join(f"04/{i % 28 + 1:02d}/24  97110  Therapeutic exercise  $96.00" for i in range(30))
    text = "ITEMIZED STATEMENT\n" + middle + "\nzzclinical addendum"
    (r,) = triage.triage_pages([{"id": "a", "text": text}], _glance_aware("billing", "zzclinical"),
                               use_readers=False, use_safety_nets=False)
    assert r.confirmed and r.decision.route == "full"


def test_poor_quality_page_never_goes_to_a_table_reader():
    rows = "\n".join(f"ibuprofen {i}00 mg tid" for i in range(2, 8))
    text = "MEDICATION LIST\n" + rows + "\n" + " ".join(["c0mpl@ins", "n€ck", "p4in", "~~", "|x|"] * 4)

    def ask(state, qs):
        return {"answers": {"page_type": {"choice": "medication_record", "probabilities": {"medication_record": 0.99}},
                            "clinical": {"choice": "table", "probabilities": {"table": 0.99}}}}

    (r,) = triage.triage_pages([{"id": "a", "text": text}], ask)
    assert r.decision.route == "full"


def test_addendum_without_clinical_words_is_not_a_duplicate():
    note = "OFFICE VISIT\n" + " ".join(f"Line {i} of the exam documented normal findings in region {i}." for i in range(40))
    index = triage.DuplicateIndex()
    index.check_and_add("a", note)
    assert index.check_and_add("b", note + "\nADDENDUM: patient states the brace helps at work") is None


def test_glance_with_a_character_budget():
    text = "HEADER\n" + "\n".join(f"line {i} " + "x" * 40 for i in range(200))
    g = triage.glance_text(text, 0, max_chars=700)
    assert 700 <= len(g.split("\n[...")[0]) < 760
    assert triage.glance_text("short\npage", 0, max_chars=700) == "short\npage"


def test_parallel_documents_match_serial_order():
    import json as _json
    from concurrent.futures import ThreadPoolExecutor
    pages = _json.loads((Path(__file__).parents[1] / "scripts/jev/efficiency_pages.json").read_text())

    def ask(state, qs):
        page = state.split("[THIS PAGE]\n", 1)[1].lower()
        t = "billing" if "$" in page else "fax_cover" if "fax" in page else "office_visit"
        c = "no" if t != "office_visit" else "yes"
        return {"answers": {"page_type": {"choice": t, "probabilities": {t: 0.97}},
                            "clinical": {"choice": c, "probabilities": {c: 0.97}}}}

    def summary(**kw):
        return {r.id: (r.decision.route, r.decision.page_type, r.decision.type_source)
                for r in triage.triage_pages(pages, ask, **kw)}

    with ThreadPoolExecutor(4) as pool:
        assert summary(parallel_docs=False) == summary(parallel_docs=True, pool_map=pool.map)
