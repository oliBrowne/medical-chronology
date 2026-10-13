"""The output step against the synthetic case SYN-001.

Ports chrono's ``test_timeline_html_links_every_locator_and_places_the_incident``
and adds the cases this data model brings: denials, partial and unknown dates,
conflicts, unstamped pages and altered quotes.
"""

from __future__ import annotations

import html
import importlib.util
import re
from pathlib import Path

import pytest

from chronology.output import dates
from chronology.output.bundle import index_bundle
from chronology.output.timeline_html import render, write_outputs

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "build_fixture", REPO / "scripts" / "fixtures" / "build_fixture.py")
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    root = tmp_path_factory.mktemp("case")
    bundle = fixture.write_case(root / "data" / "SYN-001", root / "examples")
    out = root / "outputs" / "SYN-001"
    paths = write_outputs(bundle, case_dir=root / "data" / "SYN-001", out_dir=out)
    return bundle, paths["html"].read_text(encoding="utf-8"), out, root


def entries(page: str) -> list[str]:
    return re.findall(r'<article class="entry[^"]*" id="([^"]+)"', page)


def test_every_locator_links_to_its_page(case):
    bundle, page, out, _ = case
    docs = {d.doc_id: d for d in bundle.documents}
    for span in bundle.spans:
        block = page.split(f'data-span="{span.span_id}"', 1)[1].split("</div>", 1)[0]
        href = html.unescape(re.search(r'href="([^"]+)"', block).group(1))
        path, _, frag = href.partition("#")
        assert frag == f"page={span.page_index + 1}"
        from urllib.parse import unquote
        target = (out / unquote(path)).resolve()
        assert target.name == docs[span.doc_id].path and target.is_file()


def test_exactly_one_incident_bar_with_correct_split(case):
    bundle, page, _, _ = case
    assert page.count('class="incident"') == 1
    before, after = page.split('class="incident"')
    after = after.split('id="undated"')[0]
    for ev in bundle.events:
        if ev.date is None:
            continue
        side = before if ev.date < bundle.index_event.date else after
        assert f'id="{ev.event_id}"' in side, ev.event_id


def test_dated_events_are_in_order_and_undated_come_last(case):
    bundle, page, _, _ = case
    order = entries(page)
    by_id = {ev.event_id: ev for ev in bundle.events}
    dated = [by_id[i].date for i in order if by_id[i].date]
    assert dated == sorted(dated)
    undated = [i for i in order if by_id[i].date is None]
    assert order[-len(undated):] == undated
    assert page.index('id="undated"') < page.index(f'id="{undated[0]}"')


def test_quotes_are_shown_exactly(case):
    bundle, page, _, _ = case
    for span in bundle.spans:
        shown = re.search(rf'<pre class="quote[^"]*" data-span="{span.span_id}">(.*?)</pre>',
                          page, re.S).group(1)
        assert html.unescape(shown) == span.quote


def test_denials_have_their_own_badge(case):
    bundle, page, _, _ = case
    for f in bundle.findings:
        if f.assertion == "absent":
            sid = f.span_ids[0]
            entry = page.split(f'data-span="{sid}"')[0].rsplit("<article", 1)[1]
            assert "Denied / absent" in entry


def test_partial_dates_stay_partial(case):
    _, page, _, _ = case
    assert ">Jun 2024<" in page and "month only" in page
    assert ">2019<" in page and "year only" in page
    assert "2024-06-01" not in page


def test_unstamped_page_is_labelled_not_invented(case):
    _, page, _, _ = case
    assert "Unstamped · Patient intake packet p.1" in page
    assert "no Bates stamp" in page


def test_conflict_is_shown_not_resolved(case):
    _, page, _, _ = case
    ev = page.split('id="ev-14"')[1].split("</article>")[0]
    assert "conflicting findings, not resolved" in ev
    assert ev.count('class="finding conflicting"') == 2


def test_page_makes_no_network_requests(case):
    _, page, _, _ = case
    assert not re.search(r"https?://", page)
    assert "<link" not in page and "src=" not in page


def test_altered_quote_is_flagged_not_dropped(case):
    bundle, _, out, root = case
    bad = fixture.broken(bundle)
    page = render(bad, case_dir=root / "data" / "SYN-001", out_dir=out)
    assert len(entries(page)) == len(bad.events)
    assert "quote not verified verbatim" in page
    assert "1 problem in this output" in page
    problems = index_bundle(bad).problems
    assert [p.kind for p in problems] == ["quote_mismatch"]


def test_missing_pdf_renders_unlinked(case):
    bundle, _, out, root = case
    page = render(bundle, case_dir=root / "nowhere", out_dir=out)
    assert 'class="bates nolink"' in page and 'class="bates"' not in page


def test_broken_reference_is_shown(case):
    bundle, _, out, root = case
    b = bundle.model_copy(deep=True)
    b.events[0].finding_ids.append("f-missing")
    page = render(b, case_dir=root / "data" / "SYN-001", out_dir=out)
    assert "Missing finding f-missing" in page
    assert "f-missing" in page.split("</header>")[0]


@pytest.mark.parametrize("iso,index,expected", [
    ("2024-03-14", "2024-03-14", "day of incident"),
    ("2024-03-13", "2024-03-14", "1 day before"),
    ("2024-03-26", "2024-03-14", "+12 days"),
    ("2024-03", "2024-03-14", "month of incident"),
    ("2024-06", "2024-03-14", "~3 months after"),
    ("2019", "2024-03-14", "~5 years before"),
    (None, "2024-03-14", ""),
])
def test_relative_dates(iso, index, expected):
    assert dates.relative(iso, index) == expected


def test_partial_month_sorts_before_days_in_it():
    assert sorted(["2024-03-01", "2024-03", "2024"], key=dates.sort_key) == [
        "2024", "2024-03", "2024-03-01"]


def test_outputs_use_unix_line_endings(case):
    """Re-running on Windows must not turn \n into \r\n and dirty examples/."""
    _, _, out, root = case
    for path in [out / "timeline.html", out / "timeline.json",
                 root / "examples" / "syn-001.bundle.json",
                 root / "examples" / "syn-001-broken.bundle.json"]:
        assert b"\r\n" not in path.read_bytes(), path.name
