"""The agent loop.

A hand-written tool-calling loop (deliberately not LangChain/LangGraph) that:

- keeps result rows server-side, handing the model a shape summary plus a
  short preview and referring to the full set by ``result_id``,
- bounds iterations to avoid runaway loops,
- feeds tool errors back so the model can self-correct,
- falls back to the offline engine if every provider fails or none is set.
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

from config import get_settings
from db.connections import demo_connection, get_session_connection
from db.schema_discovery import discover_schema_for, schema_to_prompt
from llm.base import AllProvidersFailed, ProviderError
from llm.failover import FailoverProvider, build_providers
from llm.offline import answer_offline, classify_intent
from llm.rate_limiter import SlidingWindowLimiter
from memory.conversation_memory import ConversationMemory
from memory.session_context import SessionScope, get_current_session_id
from tools.builder import build_registry, default_context
from store import result_store, session_store
from store.query_store import log_query

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
- execute_query returns a result_id plus a preview. Pass that result_id to generate_chart and explain_data — never copy rows between tool calls, and never re-type numbers you saw in a preview.
- When the user asks for a chart, first fetch the data with execute_query, then call generate_chart with the result_id.
- Let generate_chart pick the chart type. Only set chart_type when the user named one.
- If asked for an ER diagram, call generate_flowchart with diagram_type='er'.
- Keep explanations short, useful, and grounded in the data you actually retrieved.
- If the user greets you or asks about capabilities, just answer conversationally without tools.
- CRITICAL: After executing a tool like `execute_query` or `generate_chart`, you MUST provide a natural language explanation reasoning about the data returned before finishing. Never leave the user with just a raw chart or table without explaining what it means.
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
            memory = self._sessions.get(session_id)
            if memory is None:
                # Nothing cached: either the process restarted or the user
                # reloaded into an older conversation. Rebuild from storage so
                # the agent remembers what the sidebar is already showing.
                memory = self._hydrate_memory(session_id, message)
                self._sessions[session_id] = memory
            memory.add_user(message)
            async for event in self._process(message, memory):
                yield event

    def _hydrate_memory(self, session_id: str, current_message: str) -> ConversationMemory:
        """Rebuild conversation memory from persisted messages."""
        memory = ConversationMemory(self.settings.max_history_turns)
        try:
            stored = session_store.list_messages(session_id)
        except Exception:  # noqa: BLE001
            return memory

        # The chat route persists the question before the turn runs, so the
        # last row is this turn's message — the caller adds it separately.
        if stored and stored[-1]["role"] == "user" and stored[-1]["content"] == current_message:
            stored = stored[:-1]

        for m in stored:
            content = m.get("content") or ""
            if m["role"] == "user":
                memory.add_user(content)
            elif m["role"] == "assistant":
                memory.add_assistant(content)
            # Restore the most recent result so follow-ups still resolve after
            # a reload. Persisted since the Phase 1 artifact fix.
            table = (m.get("payload") or {}).get("table")
            if table and table.get("columns"):
                memory.set_last_result(table)
        return memory

    async def _process(self, message: str, memory: ConversationMemory) -> AsyncIterator[dict[str, Any]]:
        # 1. Conversational short-circuit (zero LLM/tool cost).
        casual = _is_conversational(message)
        if casual:
            memory.add_assistant(casual)
            yield {"type": "final", "answer": casual, "sql": None, "table": None, "chart": None, "diagram": None, "mode": "rule"}
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
        # Whichever database this session is pointed at. Resolved here, not by
        # the model, and refreshed per turn so a mid-conversation switch takes
        # effect immediately.
        connection = get_session_connection(get_current_session_id())
        context["connection"] = connection
        context["db_path"] = connection.db_path or self.settings.db_path
        # generate_chart reads this to spot share-of-total questions, which the
        # result shape alone cannot express.
        context["user_message"] = message
        # explain_data narrates its own computed statistics; give it the same
        # provider chain the loop uses.
        context["llm"] = self.failover

        # Inject schema into system prompt (refreshed per turn).
        yield {"type": "status_step", "step": "inspecting_schema"}
        system_prompt = (
            SYSTEM_PROMPT
            + f"\n\nACTIVE DATABASE: {connection.name} ({connection.kind}). "
            + f"Write {connection.dialect} SQL.\n\nDATABASE SCHEMA:\n"
            + self._current_schema_text(connection)
        )

        # Re-inject the last result so follow-ups ("chart those", "why?") can
        # resolve. This rides on the system prompt because that is the one
        # channel handed to every provider verbatim — a system message placed
        # in `messages` is dropped during provider conversion.
        if memory.last_result:
            context_text = memory.last_result_context()
            if context_text:
                system_prompt += (
                    "\n\nPREVIOUS RESULT (use this to resolve follow-up questions "
                    "like \"chart those\" or \"why did it drop?\"):\n" + context_text
                )

        messages: list[dict[str, Any]] = list(memory.get_messages())

        yield {"type": "status", "label": "Thinking..."}
        last_result: dict[str, Any] | None = None
        # Artifacts produced this turn. They ride on the `final` event so the
        # chat route can persist them and a reload can rebuild the answer.
        artifacts: dict[str, Any] = {"sql": None, "table": None, "chart": None, "diagram": None}

        for step in range(MAX_AGENT_STEPS):
            self.rate_limiter.wait()

            try:
                yield {"type": "status_step", "step": "generating_plan"}
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
                yield self._final(answer, artifacts)
                return

            # Execute tool calls.
            yield {"type": "status_step", "step": "executing_tools"}
            messages.append({"role": "assistant", "content": full_text, "tool_calls": pending_tool_calls})
            for call in pending_tool_calls:
                yield {"type": "tool_call", "name": call["name"], "arguments": call.get("arguments", {})}
                result = self.registry.dispatch(call["name"], call.get("arguments", {}), context)
                tool_payload = result.get("data", {}) if result.get("success") else result
                # Capture SQL result for chart follow-through.
                if call["name"] == "execute_query" and result.get("success"):
                    # The model gets the summary; the browser and our own
                    # bookkeeping get the full rows from the result store.
                    full = result_store.get(tool_payload.get("result_id", "")) or tool_payload
                    last_result = full
                    sql_str = tool_payload.get("sql", "")
                    if sql_str:
                        try:
                            log_query(sql_str)
                        except Exception:
                            pass
                    table = {
                        "columns": full.get("columns", []),
                        "rows": full.get("rows", []),
                        "row_count": full.get("row_count", 0),
                        "truncated": full.get("truncated", False),
                    }
                    artifacts["sql"] = sql_str
                    artifacts["table"] = table
                    yield {"type": "sql", "sql": sql_str}
                    yield {"type": "table", **table}
                elif call["name"] == "generate_chart" and result.get("success"):
                    chart = tool_payload.get("chart")
                    if chart:
                        artifacts["chart"] = chart
                        yield {"type": "chart", "chart": chart}
                elif call["name"] == "generate_flowchart" and result.get("success"):
                    diagram = tool_payload
                    if "mermaid" in diagram:
                        artifacts["diagram"] = diagram
                        yield {"type": "diagram", "diagram": diagram}
                elif not result.get("success"):
                    yield {"type": "tool_result", "name": call["name"], "error": result.get("error", {})}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        # Gemini keys tool results by function name rather than
                        # by call id, so both have to travel with the message.
                        "name": call["name"],
                        "content": json.dumps(tool_payload, default=str),
                    }
                )

        # Step cap reached without a clean finish.
        answer = self._fallback_answer(last_result) or "I ran out of steps. Please ask a more specific question."
        memory.add_assistant(answer)
        memory.set_last_result(last_result or {})
        yield self._final(answer, artifacts)

    @staticmethod
    def _final(answer: str, artifacts: dict[str, Any]) -> dict[str, Any]:
        """The turn's closing event, carrying everything the turn produced.

        The chat route persists these fields, so anything missing here is lost
        when the page reloads.
        """
        return {
            "type": "final",
            "answer": answer,
            "sql": artifacts.get("sql"),
            "table": artifacts.get("table"),
            "chart": artifacts.get("chart"),
            "diagram": artifacts.get("diagram"),
            "mode": "agent",
        }

    def _tool_specs(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.registry.all()]

    def _current_schema_text(self, connection=None) -> str:
        try:
            connection = connection or demo_connection()
            return schema_to_prompt(discover_schema_for(connection))
        except Exception:  # noqa: BLE001
            return "(schema unavailable)"

    def _fallback_answer(self, last_result: dict[str, Any] | None) -> str:
        if last_result:
            n = last_result.get("row_count", 0)
            return f"I retrieved {n} rows. Ask me to chart or explain this data for more detail."
        return "I retrieved no data. Try asking a more specific question."