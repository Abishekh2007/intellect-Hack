"""Provider conversion tests.

These exercise the real provider code paths with the SDK's network client
swapped out, so the request shapes are verified without an API key. They cover
the two defects that made a provider look configured while being unable to
call a tool at all.
"""

from __future__ import annotations

import json

import pytest

from llm.clients import AnthropicProvider, GeminiProvider, gemini_schema
from tools.builder import build_registry

TOOLS = [t.to_dict() for t in build_registry().all()]


# --- Gemini schema sanitising ---------------------------------------------

def test_optional_field_does_not_emit_a_union():
    """`X | None` becomes anyOf-with-null in Pydantic, which Gemini rejects."""
    schema = {
        "type": "object",
        "title": "GenerateChartInput",
        "properties": {
            "result_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Result Id",
                "description": "id",
            }
        },
    }
    out = gemini_schema(schema)
    assert "title" not in out
    assert out["properties"]["result_id"] == {
        "type": "string",
        "nullable": True,
        "description": "id",
    }


def test_every_real_tool_schema_survives_sanitising():
    banned = {"anyOf", "oneOf", "$defs", "$ref", "default", "title", "additionalProperties"}
    for tool in TOOLS:
        out = gemini_schema(tool["schema"])
        # Walk the sanitised schema looking for keys Gemini refuses.
        stack = [out]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "properties" and isinstance(value, dict):
                        stack.extend(value.values())
                        continue
                    assert key not in banned, f"{tool['name']} leaked {key!r}"
                    stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
        assert out["type"] == "object"


def test_required_list_never_references_a_dropped_property():
    out = gemini_schema(
        {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a", "ghost"]}
    )
    assert out["required"] == ["a"]


# --- BUG-04: Anthropic must emit tool calls -------------------------------

class _FakeAnthropicStream:
    def __init__(self, final):
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        yield "Let me look that up."

    def get_final_message(self):
        return self._final


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_anthropic_emits_tool_calls(monkeypatch):
    """It used to iterate text_stream only, so tool_use blocks were dropped
    and the agent silently lost all database access."""
    import anthropic

    final = _Block(
        content=[
            _Block(type="text", text="Let me look that up."),
            _Block(type="tool_use", id="tu_1", name="execute_query",
                   input={"query": "SELECT 1"}),
        ]
    )
    captured = {}

    class FakeMessages:
        def stream(self, **kwargs):
            captured.update(kwargs)
            return _FakeAnthropicStream(final)

    class FakeAnthropic:
        def __init__(self, **kw):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)

    events = list(
        AnthropicProvider("k").stream_tool_calls(
            [{"role": "user", "content": "how many orders?"}], TOOLS, "sys"
        )
    )
    kinds = [e["type"] for e in events]
    assert "text" in kinds
    calls = [e for e in events if e["type"] == "tool_call"]
    assert len(calls) == 1
    assert calls[0]["name"] == "execute_query"
    assert calls[0]["arguments"] == {"query": "SELECT 1"}
    assert captured["tools"], "tools were not sent to the model"


def test_anthropic_tool_arguments_are_objects_not_strings(monkeypatch):
    """messages_to_openai serialises arguments to a JSON string; Anthropic
    needs the object back or it rejects the tool_use block."""
    import anthropic

    captured = {}

    class FakeMessages:
        def stream(self, **kwargs):
            captured.update(kwargs)
            return _FakeAnthropicStream(_Block(content=[]))

    class FakeAnthropic:
        def __init__(self, **kw):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)

    history = [
        {"role": "user", "content": "top products"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "execute_query", "arguments": {"query": "SELECT 1"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "execute_query", "content": "{\"rows\": []}"},
    ]
    list(AnthropicProvider("k").stream_tool_calls(history, TOOLS, "sys"))

    assistant = [m for m in captured["messages"] if m["role"] == "assistant"][0]
    tool_use = [b for b in assistant["content"] if b["type"] == "tool_use"][0]
    assert tool_use["input"] == {"query": "SELECT 1"}


# --- BUG-11: Gemini tool wiring -------------------------------------------

def _run_gemini(monkeypatch, messages):
    from google import genai

    captured = {}

    class FakeModels:
        def generate_content_stream(self, **kwargs):
            captured.update(kwargs)
            return iter(())

    class FakeClient:
        def __init__(self, **kw):
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    list(GeminiProvider("k").stream_tool_calls(messages, TOOLS, "sys"))
    return captured


def test_gemini_wraps_declarations_in_a_tool(monkeypatch):
    """A bare list of function declarations is not a Tool; the SDK needs them
    grouped under function_declarations."""
    captured = _run_gemini(monkeypatch, [{"role": "user", "content": "hi"}])
    tools = captured["config"].tools
    assert len(tools) == 1
    declarations = tools[0].function_declarations
    assert {d.name for d in declarations} >= {"execute_query", "generate_chart"}


def test_gemini_tool_response_carries_the_function_name(monkeypatch):
    """Gemini matches a response to its call by name; an empty name breaks
    the loop on the second step."""
    history = [
        {"role": "user", "content": "how many orders?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "execute_query", "arguments": {"query": "SELECT 1"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "execute_query", "content": "{\"rows\": []}"},
    ]
    captured = _run_gemini(monkeypatch, history)
    responses = [
        part["functionResponse"]
        for content in captured["contents"]
        for part in content["parts"]
        if "functionResponse" in part
    ]
    assert responses and responses[0]["name"] == "execute_query"


def test_gemini_sends_function_call_args_as_objects(monkeypatch):
    history = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "execute_query", "arguments": {"query": "SELECT 1"}}],
        },
    ]
    captured = _run_gemini(monkeypatch, history)
    calls = [
        part["functionCall"]
        for content in captured["contents"]
        for part in content["parts"]
        if "functionCall" in part
    ]
    assert calls and calls[0]["args"] == {"query": "SELECT 1"}
