"""Tool definitions the agents can call.

A tool is a plain function plus the JSON schema the model sees. Tools never
call a model, so each one can be tested on its own. Anything the model must
not choose (which page, which case) is bound when the tool is built, never
passed as an argument.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


def object_schema(properties: dict[str, dict[str, Any]] | None = None,
                  required: list[str] | None = None) -> dict[str, Any]:
    """JSON schema for a tool's arguments."""
    return {"type": "object", "properties": properties or {}, "required": required or []}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def call(self, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
        """Run the tool. Never raises: a failure comes back as
        ``{"ok": False, "error": ...}`` so the model can see it and recover."""
        try:
            if isinstance(arguments, str):
                arguments = json.loads(arguments or "{}")
            return {"ok": True, "result": self.fn(**(arguments or {}))}
        except Exception as err:  # noqa: BLE001 - reported to the model, not swallowed
            return {"ok": False, "error": f"{type(err).__name__}: {err}"}


class ToolBox:
    """The tools one agent run is allowed to use."""

    def __init__(self, tools: list[Tool]):
        names = [t.name for t in tools]
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate tool names: {names}")
        self._tools = {t.name: t for t in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def call(self, name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool {name!r}. Available: {self.names}"}
        return tool.call(arguments)
