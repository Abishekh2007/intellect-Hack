"""Conversation memory: bounded sliding window + last-results re-injection."""

from __future__ import annotations

from typing import Any


class ConversationMemory:
    """Maintains the last N turns so follow-up questions ("these products")
    can resolve without re-querying the database."""

    def __init__(self, max_turns: int = 6):
        self.max_turns = max_turns
        self.messages: list[dict[str, Any]] = []
        self.last_result: dict[str, Any] | None = None

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})
        self._trim()

    def set_last_result(self, result: dict[str, Any]) -> None:
        self.last_result = result

    def get_messages(self) -> list[dict[str, Any]]:
        return list(self.messages)

    def _trim(self) -> None:
        # Keep at most max_turns * 2 messages (user+assistant pairs).
        while len(self.messages) > self.max_turns * 2:
            self.messages.pop(0)

    def last_result_context(self, max_rows: int = 10) -> str:
        """Serialize last result into the prompt so pronouns resolve."""
        if not self.last_result:
            return ""
        result = self.last_result
        columns = result.get("columns", [])
        rows = result.get("rows", [])[:max_rows]
        if not columns:
            return ""
        lines = [f"Previous query result ({result.get('row_count', len(rows))} rows total):"]
        for row in rows:
            lines.append(", ".join(f"{c}={v}" for c, v in zip(columns, row)))
        return "\n".join(lines)