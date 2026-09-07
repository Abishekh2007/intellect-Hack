"""Bedrock Converse provider tests.

The event-stream decoder and the message conversion are the two places where
a mistake is invisible until a live turn fails, so both are exercised here
with hand-built frames -- no API key and no network.
"""

from __future__ import annotations

import json
import struct

from config import Settings
from llm.bedrock import BedrockProvider, iter_event_stream, to_bedrock_messages
from llm.failover import build_providers
from tools.builder import build_registry

TOOLS = [t.to_dict() for t in build_registry().all()]


def frame(event_type: str, payload: dict, message_type: str = "event") -> bytes:
    """Encode one AWS event-stream frame the way Bedrock does."""
    headers = b""
    for name, value in ((":event-type", event_type), (":message-type", message_type)):
        headers += bytes([len(name)]) + name.encode() + b"\x07"
        headers += struct.pack(">H", len(value)) + value.encode()
    body = json.dumps(payload).encode()
    total = 12 + len(headers) + len(body) + 4
    return struct.pack(">III", total, len(headers), 0) + headers + body + b"\x00\x00\x00\x00"


def tool_call_stream() -> bytes:
    return b"".join(
        [
            frame("messageStart", {"role": "assistant"}),
            frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Checking"}}),
            frame("contentBlockStop", {"contentBlockIndex": 0}),
            frame(
                "contentBlockStart",
                {
                    "contentBlockIndex": 1,
                    "start": {"toolUse": {"name": "execute_query", "toolUseId": "tu_1"}},
                },
            ),
            frame(
                "contentBlockDelta",
                {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '{"query": "SELECT '}}},
            ),
            frame(
                "contentBlockDelta",
                {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '1"}'}}},
            ),
            frame("contentBlockStop", {"contentBlockIndex": 1}),
            frame("messageStop", {"stopReason": "tool_use"}),
        ]
    )


# --- event-stream framing --------------------------------------------------

def test_frames_are_decoded_in_order():
    decoded = list(iter_event_stream(iter([tool_call_stream()])))
    assert [h[":event-type"] for h in (f[0] for f in decoded)] == [
        "messageStart",
        "contentBlockDelta",
        "contentBlockStop",
        "contentBlockStart",
        "contentBlockDelta",
        "contentBlockDelta",
        "contentBlockStop",
        "messageStop",
    ]


def test_frames_split_across_chunks_are_reassembled():
    """The network splits frames at arbitrary offsets, including mid-prelude."""
    raw = tool_call_stream()
    one_byte_at_a_time = (raw[i : i + 1] for i in range(len(raw)))
    assert len(list(iter_event_stream(one_byte_at_a_time))) == 8


def test_stream_yields_text_then_the_assembled_tool_call(monkeypatch):
    provider = BedrockProvider("test-key")

    class FakeResponse:
        status_code = 200

        def iter_bytes(self):
            # Fragment sizes that fall inside frames, as a real socket would.
            raw = tool_call_stream()
            for i in range(0, len(raw), 37):
                yield raw[i : i + 37]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("llm.bedrock.httpx.Client", lambda **kwargs: FakeClient())
    events = list(provider.stream_tool_calls([{"role": "user", "content": "hi"}], TOOLS, "sys"))

    assert {"type": "text", "text": "Checking"} in events
    call = next(e for e in events if e["type"] == "tool_call")
    # Argument JSON arrives in fragments; only the joined string parses.
    assert call["name"] == "execute_query"
    assert call["arguments"] == {"query": "SELECT 1"}
    assert events[-1] == {"type": "done"}


# --- request shape ---------------------------------------------------------

def test_tools_are_wrapped_in_a_toolspec():
    body = BedrockProvider("k").build_body([{"role": "user", "content": "hi"}], TOOLS, "sys")
    assert body["system"] == [{"text": "sys"}]
    spec = body["toolConfig"]["tools"][0]["toolSpec"]
    assert set(spec) == {"name", "description", "inputSchema"}
    assert spec["inputSchema"]["json"]["type"] == "object"


def test_tool_results_become_user_turns_and_consecutive_roles_merge():
    """Converse wants toolResult blocks on a user turn, with roles alternating."""
    converted = to_bedrock_messages(
        [
            {"role": "user", "content": "top products"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "get_schema", "arguments": "{}"}},
                    {
                        "id": "b",
                        "type": "function",
                        "function": {"name": "execute_query", "arguments": '{"query": "SELECT 1"}'},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "a", "content": "schema"},
            {"role": "tool", "tool_call_id": "b", "content": "rows"},
        ]
    )
    assert [m["role"] for m in converted] == ["user", "assistant", "user"]
    # An empty assistant content string must not become an empty text block.
    assert all(block.get("text") != "" for block in converted[1]["content"])
    assert converted[1]["content"][1]["toolUse"]["input"] == {"query": "SELECT 1"}
    assert [b["toolResult"]["toolUseId"] for b in converted[2]["content"]] == ["a", "b"]


def test_history_starting_on_the_assistant_is_trimmed():
    converted = to_bedrock_messages(
        [{"role": "assistant", "content": "earlier answer"}, {"role": "user", "content": "and now?"}]
    )
    assert [m["role"] for m in converted] == ["user"]


# --- wiring ----------------------------------------------------------------

def test_bedrock_key_is_accepted_by_field_name_and_by_alias(monkeypatch):
    """The alias must not cost the field its ordinary keyword/env-name path."""
    assert Settings(_env_file=None, bedrock_api_key="ABSKkwarg").bedrock_api_key == "ABSKkwarg"
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "ABSKalias")
    assert Settings(_env_file=None).bedrock_api_key == "ABSKalias"


def test_bedrock_is_primary_by_default(settings):
    """Bedrock leads the chain even when other providers are configured."""
    assert Settings(_env_file=None).llm_provider == "bedrock"
    providers = build_providers(
        Settings(_env_file=None, bedrock_api_key="ABSKtest", gemini_api_key="AIzatest")
    )
    assert [p.name for p in providers] == ["bedrock", "gemini"]


def test_bedrock_is_built_and_ordered_first(settings):
    settings.bedrock_api_key = "ABSKtest"
    settings.llm_provider = "bedrock"
    providers = build_providers(settings)
    assert providers[0].name == "bedrock"
    assert providers[0].model == settings.bedrock_model
    assert providers[0].endpoint.startswith(
        f"https://bedrock-runtime.{settings.bedrock_region}.amazonaws.com/model/"
    )
