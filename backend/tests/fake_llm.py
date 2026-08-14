"""Fake LLM harness for hermetic agent tests.

Drives the entire tool surface with a scripted, deterministic "model" so tests
run offline, fast and reproducibly — no API keys, no network.
"""

from __future__ import annotations

from typing import Any


class ScriptedChatModel:
    """Emits a fixed script of text/tool_call events once, then done.

    Subsequent calls in the same loop iteration emit nothing (just done) so
    the agent can terminate cleanly after the tool turn.
    """

    def __init__(self, script: list[dict[str, Any]]):
        self.script = script
        self.calls: list[dict[str, Any]] = []
        self._consumed = False

    def stream_tool_calls(self, messages, tools, system_prompt):
        self.calls.append(
            {"messages": messages, "tools": tools, "system_prompt": system_prompt}
        )
        if not self._consumed:
            self._consumed = True
            for event in self.script:
                yield event
        yield {"type": "done"}


class FailingChatModel:
    """Raises like a real provider outage; used to test fallback behavior."""

    def __init__(self, error_type: str, message: str):
        self.error_type = error_type
        self.message = message

    def stream_tool_calls(self, messages, tools, system_prompt):
        from llm.base import ProviderError

        raise ProviderError(self.error_type, self.message)


class ToolCallingModel:
    """A smarter fake: given a question, returns a scripted tool sequence.

    Maps known questions to tool-call scripts so integration tests can verify
    the whole loop (tool call -> execute -> chart) without a real LLM.
    """

    def __init__(self, behavior: dict[str, list[dict[str, Any]]]):
        self.behavior = behavior
        self.calls: list[dict[str, Any]] = []
        self._acted = False

    def stream_tool_calls(self, messages, tools, system_prompt):
        self.calls.append(
            {"messages": messages, "tools": tools, "system_prompt": system_prompt}
        )
        # Only respond with the scripted behavior on the FIRST call; after the
        # tool results are fed back, emit a plain text answer so the loop ends.
        if self._acted:
            yield {"type": "text", "text": "Here are the results."}
            yield {"type": "done"}
            return
        self._acted = True
        # Inspect the last user message to pick behavior.
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = m.get("content", "")
                break
        script = self.behavior.get(user_text.lower(), [])
        if not script:
            # Default: no tools, just a text answer.
            script = [{"type": "text", "text": "I found the answer."}]
        for event in script:
            yield event
        yield {"type": "done"}