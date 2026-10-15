"""Thin Ollama client for local development: chat, tools, JSON-schema output.

Local dev only, on synthetic pages. The team's hosted path for real records is
Jev (page triage, UMLS candidate choice) plus a hosted extraction model, so
nothing outside ``llm/`` should import this module directly. Standard library
only. The host comes from ``OLLAMA_HOST`` unless one is passed.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from chronology.llm.base import ChatReply, MalformedToolCall, ToolCall

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "gpt-oss:20b"
# Ollama's own default context is much smaller and truncates silently.
DEFAULT_NUM_CTX = 8192


def _host(host: str | None) -> str:
    value = host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
    return value if value.startswith("http") else f"http://{value}"


def _to_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert the loop's generic messages to Ollama's shape: tool calls nest under
    ``function``, and a tool result names the tool instead of a call id."""
    names: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            for c in m["tool_calls"]:
                names[c["id"]] = c["name"]
            out.append({"role": "assistant", "content": m.get("content") or "",
                        "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                                       for c in m["tool_calls"]]})
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_name": names.get(m.get("tool_call_id"), ""),
                        "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


class OllamaClient:
    """A ``ChatClient`` backed by a local Ollama server."""

    def __init__(self, model: str = DEFAULT_MODEL, host: str | None = None, *,
                 think: str | bool | None = None, num_ctx: int = DEFAULT_NUM_CTX,
                 temperature: float = 0.0, seed: int = 0, timeout: float = 300):
        self.model = model
        self.host = _host(host)
        self.think = think  # "low" / "medium" / "high" for gpt-oss, True / False otherwise
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout

    def chat(self, messages, tools=None, response_schema=None) -> ChatReply:
        payload: dict[str, Any] = {
            "model": self.model, "messages": _to_ollama(messages), "stream": False,
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature,
                        "seed": self.seed},
        }
        if tools:
            payload["tools"] = tools
        if response_schema is not None:
            payload["format"] = response_schema
        if self.think is not None:
            payload["think"] = self.think

        request = urllib.request.Request(
            f"{self.host}/api/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:500]
            if "error parsing tool call" in detail:
                raise MalformedToolCall(detail) from err
            raise RuntimeError(f"Ollama returned HTTP {err.code}: {detail}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"Could not reach Ollama at {self.host}: {err.reason}") from err

        message = data["message"]
        calls = []
        for n, c in enumerate(message.get("tool_calls") or []):
            arguments = c["function"].get("arguments") or {}
            if isinstance(arguments, str):
                arguments = json.loads(arguments or "{}")
            calls.append(ToolCall(id=c.get("id") or f"call_{n}", name=c["function"]["name"],
                                  arguments=arguments))
        return ChatReply(content=message.get("content") or None, tool_calls=calls,
                         input_tokens=data.get("prompt_eval_count", 0),
                         output_tokens=data.get("eval_count", 0))
