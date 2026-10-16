"""Local SNOMED CT index: build from a made-up UMLS release, then search."""

import json
from pathlib import Path
from unittest import mock

import pytest

from chronology.tools import snomed, umls
from chronology.tools.snomed_index import SnomedIndex, build_index, main, normalize

META = Path(__file__).parents[1] / "fixtures" / "umls_mini" / "META"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("umls") / "snomed.sqlite"
    build_index(META, path, progress=False)
    return path


@pytest.fixture
def index(db):
    idx = SnomedIndex(db)
    yield idx
    idx.close()


def test_build_keeps_english_current_snomed_terms_only(index):
    info = index.info
    assert info["umls_release"] == "2099AA"
    assert info["snomed_version"] == "2099_03_01"
    assert info["concepts"] == "6"
    # 21 rows: drop 1 obsolete, 1 MeSH, 1 Spanish
    assert info["terms"] == "18"
    terms = index.concept("900001")["terms"]
    assert "Cervicalgia" in terms and "Dolor de cuello" not in terms and "Old neck ache term" not in terms


def test_exact_match_on_preferred_term_and_on_a_synonym(index):
    hit = index.search("Neck pain")[0]
    assert (hit.code, hit.cui, hit.name, hit.match, hit.tag) == ("900001", "C9000001", "Neck pain", "exact", "finding")
    assert hit.semantic_types == ["Sign or Symptom"]
    assert hit.release == "2099AA"
    syn = index.search("cervicalgia")[0]
    assert syn.code == "900001" and syn.name == "Neck pain" and syn.matched == "Cervicalgia"


def test_punctuation_and_case_do_not_matter(index):
    assert index.search("  NECK-pain! ")[0].match == "exact"
    assert normalize("Neck-pain!") == "neck pain"


def test_word_order_and_word_forms(index):
    hit = index.search("pain, neck")[0]
    assert hit.code == "900001" and hit.match == "all_words"
    # porter stemming: "fractures" finds "fracture"
    assert index.search("wrist fractures")[0].code == "900006"


def test_one_result_per_concept_best_match_first(index):
    hits = index.search("neck pain")
    codes = [h.code for h in hits]
    assert len(codes) == len(set(codes))
    assert codes[0] == "900001"


def test_filters_by_semantic_type_and_tag(index):
    phrase = "cervical radiculopathy neck pain"
    assert {h.code for h in index.search(phrase)} >= {"900001", "900003"}
    assert [h.code for h in index.search(phrase, semantic_types=["Disease or Syndrome"])] == ["900003"]
    findings = [h.code for h in index.search(phrase, tags=["finding"])]
    assert findings[0] == "900001" and "900003" not in findings   # "low back pain" may follow


def test_no_match_returns_empty(index):
    assert index.search("zzzz qqqq") == []
    assert index.search("") == []


def test_missing_index_says_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="snomed_index build"):
        SnomedIndex(tmp_path / "nope.sqlite")


def test_index_is_opened_read_only(index):
    with pytest.raises(Exception):
        index._con.execute("INSERT INTO meta VALUES ('x', 'y')")


def test_rebuild_replaces_the_index(tmp_path):
    path = tmp_path / "s.sqlite"
    build_index(META, path, progress=False)
    build_index(META, path, release="2099AB", progress=False)
    assert SnomedIndex(path).info["umls_release"] == "2099AB"
    assert not path.with_suffix(".building").exists()


def test_build_needs_the_meta_files(tmp_path):
    with pytest.raises(FileNotFoundError, match="META"):
        build_index(tmp_path, tmp_path / "s.sqlite", progress=False)


def test_cli_build_search_info(tmp_path, capsys):
    path = tmp_path / "cli.sqlite"
    main(["build", str(META), "--db", str(path)])
    assert json.loads(capsys.readouterr().out)["concepts"] == "6"
    main(["search", "lumbago", "--db", str(path)])
    assert "900004" in capsys.readouterr().out
    main(["info", "--db", str(path)])
    assert json.loads(capsys.readouterr().out)["source"] == "SNOMEDCT_US"


# --- the tool the TermResolver calls ---------------------------------------

def test_snomed_search_uses_the_local_index(db, monkeypatch):
    monkeypatch.setenv("SNOMED_INDEX", str(db))
    hits = snomed.snomed_search("LBP low back pain", max_results=3)
    assert hits[0]["code"] == "900004" and hits[0]["source"] == "local"


def test_snomed_search_category_drops_the_wrong_kind_of_concept(db, monkeypatch):
    monkeypatch.setenv("SNOMED_INDEX", str(db))
    phrase = "cervical radiculopathy neck pain"
    symptom = {h["code"] for h in snomed.snomed_search(phrase, category="symptom")}
    diagnosis = {h["code"] for h in snomed.snomed_search(phrase, category="diagnosis")}
    assert "900003" not in symptom and "900001" in symptom
    assert "900003" in diagnosis


def test_without_an_index_web_fallback_needs_an_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOMED_INDEX", str(tmp_path / "missing.sqlite"))
    monkeypatch.delenv("UMLS_WEB_FALLBACK", raising=False)
    with pytest.raises(FileNotFoundError, match="UMLS_WEB_FALLBACK"):
        snomed.snomed_search("neck pain")


def test_umls_web_search_is_off_by_default(monkeypatch):
    monkeypatch.delenv("UMLS_WEB_FALLBACK", raising=False)
    with pytest.raises(PermissionError):
        umls.umls_search("neck pain")


def test_umls_web_search_shape_and_only_the_phrase_is_sent(monkeypatch):
    monkeypatch.setenv("UMLS_WEB_FALLBACK", "1")
    monkeypatch.setenv("UMLS_API_KEY", "test-key")
    sent = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"result": {"results": [
                {"ui": "900001", "name": "Neck pain"}, {"ui": "NONE", "name": "NO RESULTS"}]}}).encode()

    def fake_urlopen(url, timeout=30):
        sent.append(url)
        return Response()

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        hits = umls.umls_search("neck pain", max_results=5)
    assert hits == [{"code": "900001", "cui": None, "name": "Neck pain", "matched": "Neck pain",
                     "tag": None, "semantic_types": [], "match": "web", "score": 0.0, "release": "current"}]
    assert "string=neck+pain" in sent[0] and "sabs=SNOMEDCT_US" in sent[0]


def test_default_index_location_is_gitignored():
    from chronology.tools.snomed_index import DEFAULT_DB
    assert DEFAULT_DB.parts[0] == "data"
    gitignore = (Path(__file__).parents[2] / ".gitignore").read_text(encoding="utf-8")
    assert "data/*" in gitignore
