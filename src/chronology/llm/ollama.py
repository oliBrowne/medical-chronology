"""Thin Ollama client for local development: chat, tools, JSON-schema output.

Local dev only, on synthetic pages. The team's hosted path for real records is
Jev (page triage, UMLS candidate choice) plus a hosted extraction model, so
nothing outside ``llm/`` should import this module directly.
"""

from __future__ import annotations

from chronology.llm.base import ChatReply

DEFAULT_HOST = "http://localhost:11434"


class OllamaClient:
    def __init__(self, model: str, host: str = DEFAULT_HOST):
        self.model = model
        self.host = host

    def chat(self, messages, tools=None, response_schema=None) -> ChatReply:
        raise NotImplementedError
