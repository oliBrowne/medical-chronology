"""The tool-calling loop every agent runs on.

Send the conversation, run whatever tools the model asks for, feed the results
back, and stop when the model calls the *finish tool* successfully. The finish
tool does its own validation: if it fails, the error goes back to the model so
it can fix its answer. Every tool call is kept in ``trace`` for audit.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from chronology.llm import ollama
from chronology.tools.registry import ToolBox


@dataclass
class AgentResult:
    status: Literal["finished", "max_steps", "no_tool_call"]
    output: dict[str, Any] | None  # the arguments of the accepted finish call
    steps: int
    trace: list[dict[str, Any]] = field(default_factory=list)


def run_agent(
    system: str,
    task: str,
    toolbox: ToolBox,
    *,
    finish_tool: str,
    max_steps: int = 6,
    chat_fn: Callable[..., dict[str, Any]] = ollama.chat,
    **chat_kwargs: Any,
) -> AgentResult:
    """Run one agent to completion. ``chat_fn`` is injectable so tests can fake the model."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    trace: list[dict[str, Any]] = []
    nudged = False

    for step in range(1, max_steps + 1):
        try:
            reply = chat_fn(messages, tools=toolbox.specs(), **chat_kwargs)
        except RuntimeError as err:
            # The model wrote a tool call that Ollama could not parse (malformed
            # JSON). Count it as a failed step and ask again; anything else is a
            # real failure (server down, bad request) and propagates.
            if "error parsing tool call" not in str(err):
                raise
            trace.append({"step": step, "tool": None, "arguments": None,
                          "result": {"ok": False, "error": "tool call was not valid JSON"}})
            messages.append({"role": "user", "content": (
                f"Your last tool call was not valid JSON. Call {finish_tool} again with valid "
                "JSON that uses exactly the field names in the tool's parameter schema.")})
            continue
        messages.append(reply)
        calls = reply.get("tool_calls") or []

        if not calls:
            if nudged:
                return AgentResult("no_tool_call", None, step, trace)
            nudged = True
            messages.append({"role": "user",
                             "content": f"Call a tool. When you are done, call {finish_tool}."})
            continue

        for call in calls:
            name = call["function"]["name"]
            arguments = call["function"].get("arguments") or {}
            result = toolbox.call(name, arguments)
            trace.append({"step": step, "tool": name, "arguments": arguments, "result": result})
            if name == finish_tool and result["ok"]:
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                return AgentResult("finished", arguments, step, trace)
            messages.append({"role": "tool", "tool_name": name,
                             "content": json.dumps(result, default=str)})

    return AgentResult("max_steps", None, max_steps, trace)
