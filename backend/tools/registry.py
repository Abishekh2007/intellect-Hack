"""Tool registry.

The single source of truth for every tool the agent can call. Each tool is a
:class:`ToolDefinition` with a Pydantic ``input_model``; the JSON schema for
that model is what we hand to any LLM provider (OpenAI function-calling,
Anthropic tool_use, Gemini functionDeclarations). Validation happens through
Pydantic at dispatch time, so a malformed tool call can never crash the agent.

This is the architecture cornerstone: adding a new tool = one new module +
one registration line.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

# A handler receives validated kwargs plus shared context and returns a dict.
ToolHandler = Callable[..., dict[str, Any]]


class ToolError(Exception):
    """Raise from a tool handler for a recoverable, tool-level failure.

    The registry converts it into a structured ToolResult.error so the LLM can
    read the failure and correct its next call.
    """

    def __init__(self, error_type: str, message: str, recoverable: bool = True):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.recoverable = recoverable


class ToolResult:
    """Uniform tool return contract the LLM can recover from."""

    @staticmethod
    def success(payload: dict[str, Any]) -> dict[str, Any]:
        return {"success": True, "data": payload}

    @staticmethod
    def error(error_type: str, message: str, recoverable: bool = True) -> dict[str, Any]:
        return {
            "success": False,
            "error": {"type": error_type, "message": message, "recoverable": recoverable},
        }


class ToolDefinition:
    def __init__(
        self,
        name: str,
        description: str,
        input_model: type[BaseModel],
        handler: ToolHandler,
    ):
        self.name = name
        self.description = description
        self.input_model = input_model
        self.handler = handler

    def json_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def dispatch(self, raw_args: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate raw_args against the Pydantic model and run the handler."""
        try:
            validated = self.input_model.model_validate(raw_args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.error("invalid_arguments", f"Invalid arguments for {self.name}: {exc}")
        ctx = context or {}
        try:
            result = self.handler(validated, ctx)
            return ToolResult.success(result)
        except ToolError as exc:
            return ToolResult.error(exc.error_type, exc.message, exc.recoverable)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.error(
                "tool_execution_error",
                f"Tool {self.name} failed: {exc}",
                recoverable=False,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def dispatch(self, name: str, raw_args: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.error("unknown_tool", f"Unknown tool: {name}")
        return tool.dispatch(raw_args, context)
