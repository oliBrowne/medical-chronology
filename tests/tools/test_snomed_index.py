"""The local SNOMED index, built from a tiny made-up UMLS release.

Every CUI and code here is invented (C9xxxxxx, 9000xxx); only the shape of
the RRF files matches a real release.
"""

import zipfile

import pytest

from chronology.tools import umls
from chronology.tools.snomed_index import (
    SnomedIndex,
    build_index,
    guess_release,
    normalize,
)

# CUI|LAT|TS|LUI|STT|SUI|ISPREF|AUI|SAUI|SCUI|SDUI|SAB|TTY|CODE|STR|SRL|SUPPRESS|CVF|
MRCONSO = [
    ("C9000001", "ENG", "Y", "SNOMEDCT_US", "PT", "9000001", "Neck pain", "N"),
    ("C9000001", "ENG", "N", "SNOMEDCT_US", "SY", "9000001", "Cervicalgia", "N"),
    ("C9000001", "ENG", "N", "SNOMEDCT_US", "FN", "9000001", "Neck pain (finding)", "N"),
    ("C9000002", "ENG", "Y", "SNOMEDCT_US", "PT", "9000002", "Loss of consciousness", "N"),
    ("C9000002", "ENG", "N", "SNOMEDCT_US", "FN", "9000002", "Loss of consciousness (finding)", "N"),
    ("C9000003", "ENG", "Y", "SNOMEDCT_US", "PT", "9000003", "Strain of lumbar region", "N"),
    ("C9000003", "ENG", "N", "SNOMEDCT_US", "FN", "9000003", "Strain of lumbar region (disorder)", "N"),
    ("C9000004", "ENG", "Y", "SNOMEDCT_US", "PT", "9000004", "Radiography of cervical spine", "N"),
    ("C9000004", "ENG", "N", "SNOMEDCT_US", "FN", "9000004", "Radiography of cervical spine (procedure)", "N"),
    ("C9000005", "ENG", "Y", "SNOMEDCT_US", "PT", "9000005", "Old neck pain term", "O"),     # suppressed
    ("C9000001", "SPA", "Y", "SNOMEDCT_US", "PT", "9000001", "Dolor de cuello", "N"),        # not English
    ("C9000001", "ENG", "Y", "MSH", "MH", "D999999", "Neck Pain", "N"),                      # not SNOMED
]
MRSTY = [("C9000001", "T184", "Sign or Symptom"), ("C9000002", "T184", "Sign or Symptom"),
         ("C9000003", "T037", "Injury or Poisoning"), ("C9000004", "T060", "Diagnostic Procedure")]


def rrf(rows):
    return "".join("|".join(r) + "|\n" for r in rows)


def conso_line(cui, lat, ispref, sab, tty, code, text, suppress):
    return (cui, lat, "P", "L1", "PF", "S1", ispref, "A1", "", code, "", sab, tty, code, text, "0", suppress, "")


@pytest.fixture
def release_zip(tmp_path):
    path = tmp_path / "umls-2099AA-metathesaurus-full.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("2099AA/META/MRCONSO.RRF", rrf(conso_line(*r) for r in MRCONSO))
        z.writestr("2099AA/META/MRSTY.RRF", rrf((c, t, "A1.1", s, "AT1", "") for c, t, s in MRSTY))
    return path


@pytest.fixture
def index(release_zip, tmp_path):
    counts = build_index(release_zip, tmp_path / "snomed_2099AA.sqlite")
    assert counts["release"] == "2099AA" and counts["concepts"] == 4
    return SnomedIndex(tmp_path / "snomed_2099AA.sqlite")


def test_release_comes_from_the_path():
    assert guess_release("umls-2025AB-metathesaurus-full.zip") == "2025AB"
    assert guess_release("/home/me/umls/2026AA/META") == "2026AA"
    assert guess_release("/home/me/downloads/meta") is None


def test_exact_match_ignores_case_and_punctuation(index):
    best = index.search("NECK PAIN.")[0]
    assert (best.code, best.cui, best.match, best.score) == ("9000001", "C9000001", "exact", 1.0)
    assert best.tag == "finding" and best.semantic_types == ("Sign or Symptom",)
    assert best.release == "2099AA"
    assert normalize(" Neck  pain. ") == "neck pain"


def test_synonyms_find_the_preferred_term(index):
    best = index.search("cervicalgia")[0]
    assert best.preferred_name == "Neck pain" and best.name == "Cervicalgia"


def test_word_search_when_nothing_matches_exactly(index):
    found = index.search("lumbar strain")
    assert [c.code for c in found] == ["9000003"]
    assert found[0].match == "text" and 0 < found[0].score < 1


def test_one_result_per_code_and_filters(index):
    neck = index.search("neck")
    assert len({c.code for c in neck}) == len(neck)
    assert "9000005" not in {c.code for c in neck}             # suppressed names are left out
    assert all(c.code.startswith("9") for c in neck)            # only SNOMED, not MeSH
    assert [c.code for c in index.search("cervical", semantic_types=["Diagnostic Procedure"])] == ["9000004"]
    assert index.search("cervical", semantic_types=["Sign or Symptom"]) == []
    assert index.search("dolor de cuello") == [] and index.search("...") == []


def test_folder_release_works_too(tmp_path):
    meta = tmp_path / "2099AB" / "META"
    meta.mkdir(parents=True)
    (meta / "MRCONSO.RRF").write_text(rrf(conso_line(*r) for r in MRCONSO[:3]), encoding="utf-8")
    (meta / "MRSTY.RRF").write_text(rrf([("C9000001", "T184", "A1.1", "Sign or Symptom", "AT1", "")]),
                                    encoding="utf-8")
    counts = build_index(tmp_path / "2099AB" / "META", tmp_path / "idx.sqlite")
    assert counts["release"] == "2099AB" and counts["names"] == 3


def test_umls_search_uses_the_local_index_and_never_the_web(index, monkeypatch):
    monkeypatch.setenv("SNOMED_INDEX", str(index.path))
    monkeypatch.setattr(umls, "_web_search", lambda *a: pytest.fail("web API called"))
    umls._index.cache_clear()
    assert umls.umls_search("loss of consciousness")[0]["code"] == "9000002"
    umls._index.cache_clear()


def test_no_index_and_no_fallback_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("SNOMED_INDEX", raising=False)
    monkeypatch.delenv("UMLS_WEB_FALLBACK", raising=False)
    monkeypatch.setattr(umls, "default_index_path", lambda: None)
    umls._index.cache_clear()
    with pytest.raises(FileNotFoundError):
        umls.umls_search("neck pain")
    umls._index.cache_clear()
