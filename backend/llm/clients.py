"""Concrete provider implementations.

- OpenAIProvider: OpenAI-compatible function calling (works for any
  OpenAI-compatible endpoint).
- GeminiProvider: Google Gemini function declarations via google-genai SDK.
- AnthropicProvider: Anthropic tool_use blocks.

Each streams events through a shared generator protocol. Providers raise
:class:`ProviderError` on auth/quota/transport failures so failover can try
the next one.
"""

from __future__ import annotations

import json
from typing import Any

from llm.providers import messages_to_openai

from .base import ProviderError


_GEMINI_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "properties",
    "required",
    "items",
}


def gemini_schema(schema: Any) -> Any:
    """Reduce a Pydantic JSON Schema to the subset Gemini accepts.

    Pydantic emits ``title``, ``default`` and — for any ``X | None`` field —
    an ``anyOf`` union with a null branch. Gemini's function declarations
    reject all of those, so an optional field is enough to break the whole
    tool call. Unions are collapsed to their non-null branch and marked
    nullable instead.
    """
    if not isinstance(schema, dict):
        return schema

    union = schema.get("anyOf") or schema.get("oneOf")
    if union:
        non_null = [s for s in union if s.get("type") != "null"]
        collapsed = gemini_schema(non_null[0]) if non_null else {"type": "string"}
        if isinstance(collapsed, dict) and len(non_null) < len(union):
            collapsed["nullable"] = True
        if isinstance(collapsed, dict) and schema.get("description"):
            collapsed.setdefault("description", schema["description"])
        return collapsed

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: gemini_schema(sub) for name, sub in value.items()}
        elif key == "items":
            out[key] = gemini_schema(value)
        else:
            out[key] = value
    out.setdefault("type", "object" if "properties" in out else "string")
    # A required field that no longer exists would be rejected outright.
    if "required" in out and "properties" in out:
        out["required"] = [r for r in out["required"] if r in out["properties"]]
    return out


def _as_object(value: Any) -> dict[str, Any]:
    """Coerce tool arguments to a dict, whichever shape the SDK handed back."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str | None = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def stream_tool_calls(self, messages, tools, system_prompt):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError("openai-sdk-not-installed", str(exc)) from exc

        try:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            # `name` on tool results is carried for Gemini's benefit; strip it
            # here, since OpenAI-compatible endpoints vary in how they treat
            # unexpected fields.
            oai_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
            oai_messages.extend(
                {k: v for k, v in m.items() if k != "name"} for m in messages_to_openai(messages)
            )

            def tool_schema(m: dict[str, Any]) -> dict[str, Any]:
                return {
                    "type": "function",
                    "function": {
                        "name": m["name"],
                        "description": m["description"],
                        "parameters": m.get("schema", {"type": "object", "properties": {}}),
                    },
                }

            stream = client.chat.completions.create(
                model=self.model,
                messages=oai_messages,
                tools=[tool_schema(t) for t in tools] if tools else None,
                temperature=0,
                stream=True,
            )
            tool_call_acc: dict[int, dict[str, Any]] = {}
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                if delta.content:
                    yield {"type": "text", "text": delta.content}
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        acc = tool_call_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.id:
                            acc["id"] = tc.id
                        if tc.function and tc.function.name:
                            acc["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            acc["arguments"] += tc.function.arguments
            if tool_call_acc:
                for acc in tool_call_acc.values():
                    if not acc["name"]:
                        continue
                    try:
                        arguments = json.loads(acc["arguments"]) if acc["arguments"] else {}
                    except json.JSONDecodeError:
                        arguments = {}
                    yield {
                        "type": "tool_call",
                        "id": acc["id"],
                        "name": acc["name"],
                        "arguments": arguments,
                    }
            yield {"type": "done"}
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("openai_error", str(exc)) from exc


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-opus-5"):
        self.api_key = api_key
        self.model = model

    def stream_tool_calls(self, messages, tools, system_prompt):
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError("anthropic-sdk-not-installed", str(exc)) from exc

        try:
            client = anthropic.Anthropic(api_key=self.api_key)

            def to_anthropic_tool(m: dict[str, Any]) -> dict[str, Any]:
                return {
                    "name": m["name"],
                    "description": m["description"],
                    "input_schema": m.get("schema", {"type": "object", "properties": {}}),
                }

            oai_messages = messages_to_openai(messages)
            # Convert OpenAI-shaped messages to Anthropic format.
            anthropic_messages: list[dict[str, Any]] = []
            for m in oai_messages:
                if m["role"] == "assistant" and m.get("tool_calls"):
                    blocks: list[dict[str, Any]] = []
                    if m.get("content"):
                        blocks.append({"type": "text", "text": m["content"]})
                    for tc in m["tool_calls"]:
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                # OpenAI shape carries arguments as a JSON
                                # string; Anthropic wants the object itself.
                                "input": _as_object(tc["function"]["arguments"]),
                            }
                        )
                    anthropic_messages.append({"role": "assistant", "content": blocks})
                elif m["role"] == "tool":
                    anthropic_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": m["tool_call_id"],
                                    "content": m["content"],
                                }
                            ],
                        }
                    )
                else:
                    anthropic_messages.append({"role": m["role"], "content": m.get("content", "")})

            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": anthropic_messages,
                "temperature": 0,
            }
            if tools:
                kwargs["tools"] = [to_anthropic_tool(t) for t in tools]

            with client.messages.stream(**kwargs) as stream:
                # Stream prose as it arrives so the UI stays live.
                for text in stream.text_stream:
                    yield {"type": "text", "text": text}
                # tool_use arguments arrive as partial JSON fragments; the
                # assembled message is the reliable place to read them.
                final = stream.get_final_message()

            for block in final.content:
                if getattr(block, "type", None) == "tool_use":
                    yield {
                        "type": "tool_call",
                        "id": block.id,
                        "name": block.name,
                        "arguments": _as_object(block.input),
                    }
            yield {"type": "done"}
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("anthropic_error", str(exc)) from exc


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model

    def stream_tool_calls(self, messages, tools, system_prompt):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ProviderError("google-genai-not-installed", str(exc)) from exc

        try:
            client = genai.Client(api_key=self.api_key)

            def to_gemini_tool(m: dict[str, Any]) -> dict[str, Any]:
                return {
                    "name": m["name"],
                    "description": m["description"],
                    "parameters": gemini_schema(
                        m.get("schema", {"type": "object", "properties": {}})
                    ),
                }

            oai_messages = messages_to_openai(messages)
            gemini_contents: list[dict[str, Any]] = []
            for m in oai_messages:
                role = "model" if m["role"] == "assistant" else "user"
                if m["role"] == "tool":
                    # Gemini matches a response to its call by function name,
                    # so an empty name here silently breaks the tool loop.
                    gemini_contents.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "functionResponse": {
                                        "name": m.get("name") or "tool",
                                        "response": {"result": m["content"]},
                                    }
                                }
                            ],
                        }
                    )
                    continue

                parts: list[dict[str, Any]] = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                for tc in m.get("tool_calls", []):
                    parts.append(
                        {
                            "functionCall": {
                                "name": tc["function"]["name"],
                                "args": _as_object(tc["function"]["arguments"]),
                            }
                        }
                    )
                if not parts:
                    continue
                gemini_contents.append({"role": role, "parts": parts})

            # google-genai expects declarations grouped under a Tool, not a
            # bare list of function declarations.
            tools_config = (
                [{"function_declarations": [to_gemini_tool(t) for t in tools]}] if tools else None
            )
            response = client.models.generate_content_stream(
                model=self.model,
                contents=gemini_contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=tools_config,
                    temperature=0,
                ),
            )
            for chunk in response:
                if not chunk.candidates:
                    continue
                content = getattr(chunk.candidates[0], "content", None)
                # Gemini sends chunks whose content, or whose parts list, is
                # null — a safety stop or a finish-reason-only chunk. Iterating
                # that raised TypeError and the whole turn failed over.
                for part in (getattr(content, "parts", None) or []):
                    if part.text:
                        yield {"type": "text", "text": part.text}
                    if part.function_call:
                        yield {
                            "type": "tool_call",
                            "id": part.function_call.id or f"call_{abs(hash(str(part.function_call.name)))}",
                            "name": part.function_call.name,
                            "arguments": dict(part.function_call.args or {}),
                        }
            yield {"type": "done"}
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("gemini_error", str(exc)) from exc