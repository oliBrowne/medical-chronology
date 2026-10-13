"""Scripted ``ChatClient`` for tests: returns queued replies in order."""

from __future__ import annotations

from typing import Any

from chronology.llm.base import ChatReply


class FakeChatClient:
    def __init__(self, replies: list[ChatReply]):
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, tools=None, response_schema=None) -> ChatReply:
        self.calls.append({"messages": list(messages), "tools": tools,
                           "response_schema": response_schema})
        if not self._replies:
            raise AssertionError("FakeChatClient ran out of scripted replies")
        return self._replies.pop(0)
