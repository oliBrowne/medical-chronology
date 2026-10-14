"""Minimal client for a local Ollama server.

Standard library only. Record text goes to the local server and nowhere else.
The host comes from OLLAMA_HOST (default http://127.0.0.1:11434).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_MODEL = "gpt-oss:20b"
# Ollama's own default context is much smaller and truncates silently.
DEFAULT_NUM_CTX = 8192


def host() -> str:
    value = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    return value if value.startswith("http") else f"http://{value}"


def chat(
    messages: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    tools: list[dict[str, Any]] | None = None,
    format: dict[str, Any] | str | None = None,
    num_ctx: int = DEFAULT_NUM_CTX,
    temperature: float = 0.0,
    seed: int = 0,
    think: str | bool | None = None,
    timeout: float = 300,
) -> dict[str, Any]:
    """POST /api/chat and return the assistant message.

    The message looks like ``{"role": "assistant", "content": "...",
    "tool_calls": [{"function": {"name": ..., "arguments": {...}}}]}``;
    ``tool_calls`` is absent when the model answered in plain text.
    ``format`` takes a JSON schema to constrain the output. ``think`` takes
    "low" / "medium" / "high" for gpt-oss.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": temperature, "seed": seed},
    }
    if tools:
        payload["tools"] = tools
    if format is not None:
        payload["format"] = format
    if think is not None:
        payload["think"] = think

    request = urllib.request.Request(
        f"{host()}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)["message"]
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Ollama returned HTTP {err.code}: {detail}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"Could not reach Ollama at {host()}: {err.reason}") from err
