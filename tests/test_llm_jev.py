import json
from unittest import mock

import pytest

from chronology.llm import jev


def test_page_type_question_is_a_choice_with_every_label():
    q = jev.page_type_question()
    assert q["type"] == "choice"
    assert set(q["criteria"]) == set(jev.PAGE_TYPES)
    assert len(q["criteria"]) <= 255


def test_top_probability_reads_the_chosen_option():
    answer = {"choice": "billing", "probabilities": {"billing": 0.8, "other": 0.2}}
    assert jev.top_probability(answer) == pytest.approx(0.8)


def test_top_probability_accepts_list_shape():
    answer = {"choice": "billing",
              "probabilities": [{"option": "other", "probability": 0.1},
                                {"option": "billing", "probability": 0.9}]}
    assert jev.top_probability(answer) == pytest.approx(0.9)


def test_load_api_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("UMLS_API_KEY=x\nTYPESAFE_API_KEY='abc123'\n")
    assert jev.load_api_key(env) == "abc123"


def test_load_api_key_missing_exits(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        jev.load_api_key(tmp_path / ".env")


def test_ask_sends_pinned_model_and_parses_response():
    payload = {"model": "jev-1.13.0", "answers": {}, "usage": {"input_tokens": 5}}
    fake = mock.MagicMock()
    fake.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    with mock.patch("urllib.request.urlopen", return_value=fake) as urlopen:
        result = jev.ask("page text", {"q": jev.page_type_question()}, "key")
    sent = json.loads(urlopen.call_args.args[0].data)
    assert sent["model"] == jev.DEFAULT_MODEL
    assert sent["state"] == "page text"
    assert urlopen.call_args.args[0].headers["Authorization"] == "Bearer key"
    assert result == payload


def test_synthetic_pages_use_known_labels():
    from pathlib import Path
    pages = json.loads((Path(__file__).parents[1] / "scripts/jev/synthetic_pages.json").read_text())
    assert {p["label"] for p in pages} <= set(jev.PAGE_TYPES)
    assert len({p["id"] for p in pages}) == len(pages)
