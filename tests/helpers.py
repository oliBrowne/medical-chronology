"""Test helpers: scripted model replies built on the team's ``FakeChatClient``."""

from __future__ import annotations

from typing import Any

from chronology.llm.base import ChatReply, ToolCall
from chronology.llm.fake import FakeChatClient

__all__ = ["FakeChatClient", "ConstantChatClient", "TEXT_ONLY", "submit_reply"]

TEXT_ONLY = ChatReply(content="done")  # an answer with no tool call


def submit_reply(dates: list[dict], findings: list[dict], call_id: str = "1") -> ChatReply:
    """A model turn that calls ``submit_page``."""
    return ChatReply(tool_calls=[ToolCall(
        id=call_id, name="submit_page", arguments={"dates": dates, "findings": findings})])


class ConstantChatClient:
    """Gives the same reply to every call, however many pages are processed."""

    def __init__(self, reply: ChatReply):
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, tools=None, response_schema=None) -> ChatReply:
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.reply
