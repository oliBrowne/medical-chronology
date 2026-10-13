"""Shared tool-calling loop: step cap and a log of every tool call."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from chronology.llm.base import ChatClient
from chronology.tools.registry import Registry


class ToolCallRecord(BaseModel):
    step: int
    name: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None


class AgentResult(BaseModel):
    content: str | None
    stopped: str  # "final" or "step_cap"
    steps: int
    log: list[ToolCallRecord] = Field(default_factory=list)


def run_agent(client: ChatClient, registry: Registry, system: str, user: str,
              tool_names: list[str], max_steps: int,
              response_schema: dict | None = None) -> AgentResult:
    """Run until the model answers without tool calls or ``max_steps`` is hit.

    Only tools named in ``tool_names`` are offered or executed.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    specs = registry.specs(tool_names)
    log: list[ToolCallRecord] = []
    for step in range(1, max_steps + 1):
        reply = client.chat(messages, tools=specs, response_schema=response_schema)
        if not reply.tool_calls:
            return AgentResult(content=reply.content, stopped="final", steps=step, log=log)
        messages.append({"role": "assistant", "content": reply.content,
                         "tool_calls": [c.model_dump() for c in reply.tool_calls]})
        for call in reply.tool_calls:
            record = ToolCallRecord(step=step, name=call.name, arguments=call.arguments)
            try:
                if call.name not in tool_names:
                    raise KeyError(f"tool {call.name!r} is not allowed for this agent")
                record.result = registry.call(call.name, call.arguments)
                content = json.dumps(record.result, default=str)
            except Exception as err:  # the model sees the error and can retry
                record.error = f"{type(err).__name__}: {err}"
                content = json.dumps({"error": record.error})
            log.append(record)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
    return AgentResult(content=None, stopped="step_cap", steps=max_steps, log=log)
