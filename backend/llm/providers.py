"""Provider abstraction.

Every LLM provider implements :class:`ProviderClient`, normalizing to a single
internal message/tool shape so the agent loop never cares which model is
behind it. Failover logic lives in :mod:`llm.failover`.
"""

from __future__ import annotations

import json
from typing import Any, Protocol


class ProviderClient(Protocol):
    name: str

    def stream_tool_calls(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: str,
    ) -> Any:
        """Yield events: {"type": "text", "text": ...} or
        {"type": "tool_call", "name": ..., "arguments": {...}} or
        {"type": "error", ...} or {"type": "done"}."""
        ...


def messages_to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal messages to OpenAI format.

    Internal shape: {"role": "system"|"user"|"assistant"|"tool",
                     "content": str,
                     "tool_calls": [...], "tool_call_id": str}
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            # The turn's system prompt is passed to providers separately, so a
            # system message *inside* the history is mid-conversation context.
            # Carry it as a user turn — dropping it loses information silently.
            content = m.get("content", "")
            if content:
                out.append({"role": "user", "content": f"[context]\n{content}"})
            continue
        if role == "assistant" and m.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "tool_calls": [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("arguments", {})),
                            },
                        }
                        for i, tc in enumerate(m.get("tool_calls", []))
                    ],
                }
            )
        elif role == "tool":
            # Tool content arrives already serialized from the agent loop.
            # Re-encoding it would hand the model an escaped string instead of
            # an object, at double the tokens.
            content = m.get("content", "")
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    # Carried for providers that key results by function name
                    # (Gemini); OpenAI-shaped requests drop it before sending.
                    "name": m.get("name", ""),
                    "content": content if isinstance(content, str) else json.dumps(content, default=str),
                }
            )
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out