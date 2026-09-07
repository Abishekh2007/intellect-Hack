"""Amazon Bedrock Converse provider.

Talks to the Bedrock runtime over plain HTTPS with a Bedrock API key
(``Authorization: Bearer ...``), so no boto3/SigV4 dependency is needed --
httpx is already a requirement. Streaming uses ``converse-stream``, whose
response is the AWS ``vnd.amazon.eventstream`` binary framing decoded by
:func:`iter_event_stream` below.

Any Converse-capable Bedrock model works; the default is Qwen3-Next-80B.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Iterator

import httpx

from llm.providers import messages_to_openai

from .base import ProviderError

# Frame layout: total_len(4) header_len(4) prelude_crc(4) headers payload crc(4)
_PRELUDE = 12
_TRAILER = 4
# Header value types that carry no length prefix, mapped to their byte width.
_FIXED_HEADER_WIDTHS = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4, 5: 8, 8: 8, 9: 16}


def _decode_headers(raw: bytes) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    i = 0
    while i < len(raw):
        name_len = raw[i]
        i += 1
        name = raw[i : i + name_len].decode("utf-8", "replace")
        i += name_len
        value_type = raw[i]
        i += 1
        if value_type in (6, 7):  # byte array / string, 2-byte length prefix
            (length,) = struct.unpack_from(">H", raw, i)
            i += 2
            value: Any = raw[i : i + length]
            if value_type == 7:
                value = value.decode("utf-8", "replace")
            i += length
        else:
            width = _FIXED_HEADER_WIDTHS.get(value_type)
            if width is None:  # unknown type: the rest of the block is unreadable
                break
            value = raw[i : i + width]
            i += width
        headers[name] = value
    return headers


def iter_event_stream(chunks: Iterator[bytes]) -> Iterator[tuple[dict[str, Any], bytes]]:
    """Yield ``(headers, payload)`` per frame from an AWS event stream.

    Network chunks split frames at arbitrary offsets, so bytes are buffered
    until a whole frame (its own prelude declares the length) has arrived.
    """
    buffer = bytearray()
    for chunk in chunks:
        buffer.extend(chunk)
        while len(buffer) >= _PRELUDE:
            total_len, header_len = struct.unpack_from(">II", buffer, 0)
            if total_len < _PRELUDE + _TRAILER or len(buffer) < total_len:
                break
            headers = _decode_headers(bytes(buffer[_PRELUDE : _PRELUDE + header_len]))
            payload = bytes(buffer[_PRELUDE + header_len : total_len - _TRAILER])
            del buffer[:total_len]
            yield headers, payload


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_error(status: int | None, text: str) -> str:
    """Summarize a Bedrock error without echoing the request (or the key)."""
    message = text.strip()
    try:
        parsed = json.loads(message)
        if isinstance(parsed, dict):
            message = parsed.get("message") or parsed.get("Message") or message
    except json.JSONDecodeError:
        pass
    message = message[:300]
    if status == 403:
        return f"credentials rejected: {message}"
    if status == 429:
        return f"throttled: {message}"
    return message or f"HTTP {status}"


def to_bedrock_messages(oai_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-shaped messages to the Converse message list.

    Converse is stricter than the OpenAI shape in three ways this handles:
    tool results are ``toolResult`` blocks on a *user* turn, empty text blocks
    are rejected outright, and roles must alternate -- so consecutive turns of
    the same role (two tool results in a row, say) are merged into one.
    """
    converted: list[dict[str, Any]] = []
    for m in oai_messages:
        role = m.get("role", "user")
        blocks: list[dict[str, Any]] = []
        if role == "tool":
            content = m.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, default=str)
            blocks.append(
                {
                    "toolResult": {
                        "toolUseId": m.get("tool_call_id") or "tool",
                        "content": [{"text": content or "(empty)"}],
                    }
                }
            )
            role = "user"
        else:
            if m.get("content"):
                blocks.append({"text": m["content"]})
            for tc in m.get("tool_calls") or []:
                arguments = tc["function"]["arguments"]
                if isinstance(arguments, str):
                    arguments = _parse_arguments(arguments)
                blocks.append(
                    {
                        "toolUse": {
                            "toolUseId": tc.get("id") or "tool",
                            "name": tc["function"]["name"],
                            "input": arguments,
                        }
                    }
                )
        if not blocks:
            continue
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})

    # A history that opens on an assistant turn (a rehydrated session) is
    # rejected; Converse requires the conversation to start with the user.
    while converted and converted[0]["role"] != "user":
        converted.pop(0)
    return converted


class BedrockProvider:
    """Bedrock Converse / ConverseStream over an API-key bearer token."""

    name = "bedrock"

    def __init__(
        self,
        api_key: str,
        model: str = "qwen.qwen3-next-80b-a3b",
        region: str = "us-east-1",
        max_tokens: int = 4096,
    ):
        self.api_key = api_key
        self.model = model
        self.region = region
        self.max_tokens = max_tokens

    @property
    def endpoint(self) -> str:
        return (
            f"https://bedrock-runtime.{self.region}.amazonaws.com"
            f"/model/{self.model}/converse-stream"
        )

    def build_body(self, messages, tools, system_prompt) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messages": to_bedrock_messages(messages_to_openai(messages)),
            "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": 0},
        }
        if system_prompt:
            body["system"] = [{"text": system_prompt}]
        if tools:
            body["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["name"],
                            "description": t["description"],
                            "inputSchema": {
                                "json": t.get("schema", {"type": "object", "properties": {}})
                            },
                        }
                    }
                    for t in tools
                ]
            }
        return body

    def stream_tool_calls(self, messages, tools, system_prompt):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.amazon.eventstream",
        }
        # Blocks are tracked by index: a turn can interleave prose with one or
        # more tool_use blocks, and their argument JSON arrives in fragments.
        pending: dict[int, dict[str, str]] = {}
        try:
            with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
                with client.stream(
                    "POST",
                    self.endpoint,
                    headers=headers,
                    json=self.build_body(messages, tools, system_prompt),
                ) as response:
                    if response.status_code != 200:
                        response.read()
                        raise ProviderError(
                            f"bedrock_http_{response.status_code}",
                            _safe_error(response.status_code, response.text),
                        )
                    for frame_headers, payload in iter_event_stream(response.iter_bytes()):
                        event_type = frame_headers.get(":event-type", "")
                        if frame_headers.get(":message-type") == "exception":
                            raise ProviderError(
                                f"bedrock_{event_type or 'exception'}",
                                _safe_error(None, payload.decode("utf-8", "replace")),
                            )
                        try:
                            event = json.loads(payload) if payload else {}
                        except json.JSONDecodeError:
                            continue

                        index = event.get("contentBlockIndex", 0)
                        if event_type == "contentBlockStart":
                            tool_use = (event.get("start") or {}).get("toolUse")
                            if tool_use:
                                pending[index] = {
                                    "id": tool_use.get("toolUseId", ""),
                                    "name": tool_use.get("name", ""),
                                    "arguments": "",
                                }
                        elif event_type == "contentBlockDelta":
                            delta = event.get("delta") or {}
                            if delta.get("text"):
                                yield {"type": "text", "text": delta["text"]}
                            tool_delta = delta.get("toolUse")
                            if tool_delta and index in pending:
                                pending[index]["arguments"] += tool_delta.get("input", "")
                        elif event_type == "contentBlockStop":
                            acc = pending.pop(index, None)
                            if acc and acc["name"]:
                                yield {
                                    "type": "tool_call",
                                    "id": acc["id"],
                                    "name": acc["name"],
                                    "arguments": _parse_arguments(acc["arguments"]),
                                }
            yield {"type": "done"}
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("bedrock_error", str(exc)) from exc
