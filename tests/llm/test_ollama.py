import io
import json
import urllib.error
from unittest import mock

import pytest

from chronology.llm.base import MalformedToolCall
from chronology.llm.ollama import OllamaClient, _to_ollama


def response(body: dict):
    context = mock.MagicMock()
    context.__enter__.return_value = io.BytesIO(json.dumps(body).encode())
    return context


def test_loop_messages_are_converted_to_ollamas_shape():
    out = _to_ollama([
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_0", "name": "echo", "arguments": {"a": 1}}]},
        {"role": "tool", "tool_call_id": "call_0", "content": "{}"},
    ])
    assert out[1]["tool_calls"] == [{"function": {"name": "echo", "arguments": {"a": 1}}}]
    assert out[2] == {"role": "tool", "tool_name": "echo", "content": "{}"}


def test_a_tool_call_reply_becomes_a_chat_reply_with_token_counts():
    body = {"message": {"content": "", "tool_calls": [
        {"function": {"name": "submit_page", "arguments": {"dates": []}}}]},
        "prompt_eval_count": 5, "eval_count": 7}
    with mock.patch("urllib.request.urlopen", return_value=response(body)):
        reply = OllamaClient("m").chat([{"role": "user", "content": "hi"}])
    assert reply.tool_calls[0].name == "submit_page"
    assert reply.tool_calls[0].id == "call_0" and reply.tool_calls[0].arguments == {"dates": []}
    assert (reply.input_tokens, reply.output_tokens) == (5, 7)


def test_think_schema_and_options_are_sent():
    sent = {}

    def capture(request, timeout=None):
        sent.update(json.loads(request.data))
        return response({"message": {"content": "ok"}})

    with mock.patch("urllib.request.urlopen", side_effect=capture):
        OllamaClient("gpt-oss:20b", think="medium", num_ctx=4096).chat(
            [{"role": "user", "content": "hi"}], response_schema={"type": "object"})
    assert sent["think"] == "medium" and sent["format"] == {"type": "object"}
    assert sent["options"]["num_ctx"] == 4096 and sent["model"] == "gpt-oss:20b"


def test_an_unparseable_tool_call_raises_malformed_tool_call():
    error = urllib.error.HTTPError(
        "http://x", 500, "err", {}, io.BytesIO(b'{"error":"error parsing tool call: raw=..."}'))
    with mock.patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(MalformedToolCall):
            OllamaClient("m").chat([{"role": "user", "content": "hi"}])


def test_other_http_errors_stay_runtime_errors():
    error = urllib.error.HTTPError("http://x", 400, "err", {}, io.BytesIO(b'{"error":"nope"}'))
    with mock.patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="HTTP 400"):
            OllamaClient("m").chat([{"role": "user", "content": "hi"}])
