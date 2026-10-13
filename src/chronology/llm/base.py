"""The interface every chat backend implements."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatReply(BaseModel):
    """One assistant turn: either tool calls to run, or final content."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> ChatReply:
        """Send the conversation so far; return the model's next turn.

        ``tools`` are JSON-schema tool specs from ``tools.registry``.
        ``response_schema`` asks for JSON output matching that schema.
        """
        ...
