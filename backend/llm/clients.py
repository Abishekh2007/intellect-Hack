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
            oai_messages = [{"role": "system", "content": system_prompt}]
            oai_messages.extend(messages_to_openai(messages))

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

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
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
                    blocks: list[dict[str, Any]] = [{"type": "text", "text": m.get("content") or ""}]
                    for tc in m["tool_calls"]:
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "input": tc["function"]["arguments"],
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

            with client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=anthropic_messages,
                tools=[to_anthropic_tool(t) for t in tools] if tools else None,
                temperature=0,
            ) as stream:
                for text in stream.text_stream:
                    yield {"type": "text", "text": text}
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
                    "parameters": m.get("schema", {"type": "object", "properties": {}}),
                }

            oai_messages = messages_to_openai(messages)
            gemini_contents: list[dict[str, Any]] = []
            for m in oai_messages:
                role = "model" if m["role"] == "assistant" else "user"
                parts: list[dict[str, Any]] = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                for tc in m.get("tool_calls", []):
                    parts.append(
                        {
                            "functionCall": {
                                "name": tc["function"]["name"],
                                "args": tc["function"]["arguments"],
                            }
                        }
                    )
                if m["role"] == "tool":
                    parts = [
                        {
                            "functionResponse": {
                                "name": "",
                                "response": {"result": m["content"]},
                            }
                        }
                    ]
                gemini_contents.append({"role": role, "parts": parts})

            tools_config = (
                [to_gemini_tool(t) for t in tools]
                if tools
                else None
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
                for part in chunk.candidates[0].content.parts:
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