"""Tool name -> function + JSON schema, so agents list tools by name."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


def object_schema(properties: dict[str, dict[str, Any]] | None = None,
                  required: list[str] | None = None) -> dict[str, Any]:
    """JSON schema for a tool's arguments object."""
    return {"type": "object", "properties": properties or {}, "required": required or []}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments object
    fn: Callable[..., Any]


@dataclass
class Registry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self.tools[tool.name] = tool

    def specs(self, names: list[str]) -> list[dict[str, Any]]:
        """Tool specs in the common function-calling shape, in ``names`` order."""
        return [
            {"type": "function",
             "function": {"name": t.name, "description": t.description,
                          "parameters": t.parameters}}
            for t in (self.tools[n] for n in names)
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        return self.tools[name].fn(**arguments)
