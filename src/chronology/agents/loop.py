"""Shared tool-calling loop: step cap and a log of every tool call.

Runs until the model answers without tool calls, or until it calls the
*finish tool* successfully (``finish_tool``), or until ``max_steps``. A finish
tool does its own validation: if it raises, the error goes back to the model so
it can fix its answer.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from chronology.llm.base import ChatClient, MalformedToolCall
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
    output: dict[str, Any] | None = None  # the arguments of the accepted finish call


def run_agent(client: ChatClient, registry: Registry, system: str, user: str,
              tool_names: list[str], max_steps: int,
              response_schema: dict | None = None,
              finish_tool: str | None = None) -> AgentResult:
    """Run until the model answers without tool calls or ``max_steps`` is hit.

    Only tools named in ``tool_names`` are offered or executed. With
    ``finish_tool``, a successful call to it ends the run and its arguments
    are returned in ``output``; a plain-text answer before that gets one nudge.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    specs = registry.specs(tool_names)
    log: list[ToolCallRecord] = []
    nudged = False
    for step in range(1, max_steps + 1):
        try:
            reply = client.chat(messages, tools=specs, response_schema=response_schema)
        except MalformedToolCall as err:
            log.append(ToolCallRecord(step=step, name="(unparseable tool call)", arguments={},
                                      error="tool call was not valid JSON"))
            messages.append({"role": "user", "content": (
                "Your last tool call was not valid JSON. Call the tool again with valid JSON "
                "that uses exactly the field names in its parameter schema.")})
            continue
        if not reply.tool_calls:
            if finish_tool and not nudged:
                nudged = True
                messages.append({"role": "assistant", "content": reply.content})
                messages.append({"role": "user",
                                 "content": f"Call a tool. When you are done, call {finish_tool}."})
                continue
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
            if call.name == finish_tool and record.error is None:
                return AgentResult(content=reply.content, stopped="final", steps=step,
                                   log=log, output=call.arguments)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
    return AgentResult(content=None, stopped="step_cap", steps=max_steps, log=log)
