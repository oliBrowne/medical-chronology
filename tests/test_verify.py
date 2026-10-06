from chronology.schemas import EvidenceSpan, Page
from chronology.stages.verify import quote_matches_page

PAGE = Page(doc_id="d1", page_index=2, bates_label="DOE 000003",
            text="Pt denies chest pain. Abdominal pain 7/10.", text_source="native")


def span(start, end, quote, page_index=2):
    return EvidenceSpan(span_id="s", doc_id="d1", page_index=page_index,
                        char_start=start, char_end=end, quote=quote)


def test_exact_quote_passes():
    assert quote_matches_page(span(22, 36, "Abdominal pain"), PAGE)


def test_paraphrase_fails():
    assert not quote_matches_page(span(22, 36, "abdominal pain"), PAGE)


def test_wrong_page_fails():
    assert not quote_matches_page(span(22, 36, "Abdominal pain", page_index=3), PAGE)


def test_out_of_bounds_fails():
    assert not quote_matches_page(span(40, 400, "x"), PAGE)
