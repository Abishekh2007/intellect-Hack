"""The agent loop.

A hand-written tool-calling loop (deliberately not LangChain/LangGraph) that:

- keeps result rows server-side (the LLM never sees raw rows, only a summary),
- bounds iterations to avoid runaway loops,
- feeds tool errors back so the model can self-correct,
- falls back to the offline engine if every provider fails or none is set.
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

from config import get_settings
from db.engine import create_readonly_connection
from db.schema_discovery import discover_schema, schema_to_prompt
from llm.base import AllProvidersFailed, ProviderError
from llm.failover import FailoverProvider, build_providers
from llm.offline import answer_offline, classify_intent
from llm.rate_limiter import SlidingWindowLimiter
from memory.conversation_memory import ConversationMemory
from memory.session_context import SessionScope, get_current_session_id
from tools.builder import build_registry, default_context

MAX_AGENT_STEPS = 8

SYSTEM_PROMPT = """You are DataPilot, an AI agent that helps users query and understand a database using natural language.

You have access to tools. Use them in this order when needed:
1. get_schema - understand available tables/columns (call at least once per new database).
2. execute_query - run a read-only SELECT query. NEVER write to the database.
3. generate_chart - visualize a result set. Pass the rows as a list of objects.
4. generate_flowchart - draw ER/process/decision diagrams.
5. explain_data - give grounded insights over a result set.
6. verify_response - before finishing, check you delivered what was asked.

Rules:
- Only generate SELECT queries. The system blocks everything else.
- If a query fails, read the error and retry with a corrected query (at most twice).
- When the user asks for a chart, first fetch the data with execute_query, then call generate_chart with those rows.
- If asked for an ER diagram, call generate_flowchart with diagram_type='er'.
- Keep explanations short, useful, and grounded in the data you actually retrieved.
- If the user greets you or asks about capabilities, just answer conversationally without tools.
"""

_CONVERSATIONAL_RE = re.compile(
    r"^(hi|hello|hey|thanks|thank you|who are you|what can you do|help)\b", re.IGNORECASE
)


def _is_conversational(prompt: str) -> str | None:
    m = _CONVERSATIONAL_RE.match(prompt.strip())
    if not m:
        return None
    key = m.group(1).lower()
    replies = {
        "hi": "Hello! I'm DataPilot, your AI data analyst. Try asking me things like \"top 5 products by revenue\" or \"show me the ER diagram\".",
        "hello": "Hello! I'm DataPilot, your AI data analyst. Try asking me things like \"top 5 products by revenue\" or \"show me the ER diagram\".",
        "hey": "Hey! How can I help you explore your data today?",
        "thanks": "You're welcome! Anything else you'd like to explore?",
        "thank you": "You're welcome! Anything else you'd like to explore?",
        "who are you": "I'm DataPilot, an AI agent that turns natural language into database queries, charts and insights.",
        "what can you do": "I can query your database, build charts (bar/line/pie/scatter), draw ER and process diagrams, and explain the results.",
        "help": "Try questions like: \"top products by revenue\", \"monthly sales trend\", \"ER diagram\", or \"why did revenue drop?\"",
    }
    return replies.get(key)


class DataPilotAgent:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.registry = build_registry()
        self.rate_limiter = SlidingWindowLimiter(self.settings.llm_rpm)
        self.providers = build_providers(self.settings)
        self.failover = FailoverProvider(self.providers) if self.providers else None
        self._sessions: dict[str, ConversationMemory] = {}

    # --- public entry point: async generator of SSE events ---
    async def stream_turn(self, message: str, session_id: str) -> AsyncIterator[dict[str, Any]]:
        with SessionScope(session_id):
            memory = self._sessions.setdefault(session_id, ConversationMemory(self.settings.max_history_turns))
            memory.add_user(message)
            async for event in self._process(message, memory):
                yield event

    async def _process(self, message: str, memory: ConversationMemory) -> AsyncIterator[dict[str, Any]]:
        # 1. Conversational short-circuit (zero LLM/tool cost).
        casual = _is_conversational(message)
        if casual:
            memory.add_assistant(casual)
            yield {"type": "final", "answer": casual, "sql": None, "chart": None, "diagram": None, "mode": "rule"}
            return

        # 2. Offline engine first (if no providers configured).
        if not self.failover:
            offline_reply = answer_offline(message, self.settings)
            if offline_reply and offline_reply.get("type") == "final":
                memory.add_assistant(offline_reply.get("answer", ""))
                yield offline_reply
                return
            yield {
                "type": "final",
                "answer": "I need an LLM API key to answer that. Please set one in the .env file, or try a data question.",
                "mode": "error",
            }
            return

        # 3. Real agent loop.
        context = default_context(self.settings)
        context["db_path"] = self.settings.db_path

        # Inject schema into system prompt (refreshed per turn).
        system_prompt = SYSTEM_PROMPT + "\n\nDATABASE SCHEMA:\n" + self._current_schema_text()

        messages: list[dict[str, Any]] = []
        for m in memory.get_messages():
            messages.append(m)
        # Re-inject last result so follow-ups resolve.
        if memory.last_result:
            context_text = memory.last_result_context()
            if context_text:
                messages = messages + [{"role": "system", "content": context_text}]

        yield {"type": "status", "label": "Thinking..."}
        last_result: dict[str, Any] | None = None
        tool_calls_total = 0

        for step in range(MAX_AGENT_STEPS):
            tool_calls_total += 1
            self.rate_limiter.wait()

            try:
                provider_events = self.failover.stream_tool_calls(messages, self._tool_specs(), system_prompt)
            except AllProvidersFailed as exc:
                yield {"type": "error", "message": f"All LLM providers failed: {exc}"}
                break

            text_parts: list[str] = []
            pending_tool_calls: list[dict[str, Any]] = []
            try:
                for event in provider_events:
                    if event["type"] == "text":
                        text_parts.append(event["text"])
                        yield {"type": "token", "text": event["text"]}
                    elif event["type"] == "tool_call":
                        pending_tool_calls.append(event)
                    elif event["type"] == "error":
                        yield {"type": "error", "message": event.get("message", "")}
            except ProviderError as exc:
                yield {"type": "error", "message": f"Provider failed mid-stream: {exc}"}
                break
            full_text = "".join(text_parts)

            if not pending_tool_calls:
                # Model finished; wrap up.
                answer = full_text.strip()
                if not answer:
                    answer = self._fallback_answer(last_result)
                memory.add_assistant(answer)
                memory.set_last_result(last_result or {})
                yield {"type": "final", "answer": answer, "sql": None, "chart": None, "diagram": None, "mode": "agent"}
                return

            # Execute tool calls.
            messages.append({"role": "assistant", "content": full_text, "tool_calls": pending_tool_calls})
            for call in pending_tool_calls:
                yield {"type": "tool_call", "name": call["name"], "arguments": call.get("arguments", {})}
                result = self.registry.dispatch(call["name"], call.get("arguments", {}), context)
                tool_payload = result.get("data", {}) if result.get("success") else result
                # Capture SQL result for chart follow-through.
                if call["name"] == "execute_query" and result.get("success"):
                    last_result = tool_payload
                    yield {"type": "sql", "sql": tool_payload.get("sql", "")}
                    yield {
                        "type": "table",
                        "columns": tool_payload.get("columns", []),
                        "rows": tool_payload.get("rows", []),
                        "truncated": tool_payload.get("truncated", False),
                    }
                elif call["name"] == "generate_chart" and result.get("success"):
                    chart = tool_payload.get("chart")
                    if chart:
                        yield {"type": "chart", "chart": chart}
                elif call["name"] == "generate_flowchart" and result.get("success"):
                    diagram = tool_payload
                    if "mermaid" in diagram:
                        yield {"type": "diagram", "diagram": diagram}
                elif not result.get("success"):
                    yield {"type": "tool_result", "name": call["name"], "error": result.get("error", {})}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": json.dumps(tool_payload, default=str),
                    }
                )

        # Step cap reached without a clean finish.
        answer = self._fallback_answer(last_result) or "I ran out of steps. Please ask a more specific question."
        memory.add_assistant(answer)
        yield {"type": "final", "answer": answer, "sql": None, "chart": None, "diagram": None, "mode": "agent"}

    def _tool_specs(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.registry.all()]

    def _current_schema_text(self) -> str:
        try:
            conn = create_readonly_connection(self.settings.db_path)
            try:
                schema = discover_schema(conn)
            finally:
                conn.close()
            return schema_to_prompt(schema)
        except Exception:  # noqa: BLE001
            return "(schema unavailable)"

    def _fallback_answer(self, last_result: dict[str, Any] | None) -> str:
        if last_result:
            n = last_result.get("row_count", 0)
            return f"I retrieved {n} rows. Ask me to chart or explain this data for more detail."
        return "I retrieved no data. Try asking a more specific question."