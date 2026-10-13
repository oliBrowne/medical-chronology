from chronology.schemas import Page
from chronology.tools.quotes import find_quote

PAGE = Page(doc_id="d1", page_index=0, text="Neck pain. Neck pain worse.", text_source="native")


def test_find_quote_returns_every_exact_hit():
    assert find_quote(PAGE, "Neck pain") == [(0, 9), (11, 20)]


def test_find_quote_is_case_sensitive():
    assert find_quote(PAGE, "neck pain") == []
