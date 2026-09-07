"""The agent loop.

A hand-written tool-calling loop (deliberately not LangChain/LangGraph) that:

- keeps result rows server-side, handing the model a shape summary plus a
  short preview and referring to the full set by ``result_id``,
- bounds iterations to avoid runaway loops,
- feeds tool errors back so the model can self-correct,
- falls back to the offline engine if every provider fails or none is set.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import OrderedDict
from datetime import date
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

# Conversation memories are held per session for the life of the process. An
# unbounded dict grew by one entry per distinct session id and never shrank.
MAX_CACHED_SESSIONS = 200

# Provider SDK exceptions can carry the request URL, and some providers put the
# API key in it. Only a curated summary reaches the browser; the detail goes to
# the log, where it belongs.
_SAFE_PROVIDER_HINTS = (
    ("api key", "The configured LLM API key was rejected. Check it in the .env file."),
    ("unauthor", "The configured LLM API key was rejected. Check it in the .env file."),
    ("permission", "The configured LLM API key was rejected. Check it in the .env file."),
    ("quota", "The LLM provider is out of quota. Try again later or add another key."),
    ("rate limit", "The LLM provider is rate-limiting this key. Try again in a moment."),
    ("429", "The LLM provider is rate-limiting this key. Try again in a moment."),
    ("timeout", "The LLM provider timed out. Try again."),
    ("connect", "Could not reach the LLM provider. Check your network connection."),
)


def _model_view(tool_name: str, payload: dict[str, Any], success: bool) -> dict[str, Any]:
    """What the *model* sees of a tool result, as opposed to the browser.

    Rendered artifacts are for the reader, not the writer. Handed the raw
    Mermaid source, the model copied all thirty lines of it into its answer as
    a code block — and the diagram then rendered underneath, so the user got
    the picture twice, once unreadable. The same applies to a finished chart
    spec: its rows are the ones already on screen in the results table.

    They still reach the browser in full; only the model's copy is trimmed.
    """
    if not success or not isinstance(payload, dict):
        return payload

    if tool_name == "generate_flowchart":
        return {
            "diagram_type": payload.get("diagram_type"),
            "rendered": True,
            "note": (
                "The diagram is rendered and already visible to the user. Do "
                "not reproduce the Mermaid source, and do not describe the "
                "diagram box by box — say what the structure means."
            ),
        }

    if tool_name == "generate_chart":
        chart = payload.get("chart") or {}
        return {
            "chart_type": chart.get("type"),
            "x_axis": chart.get("x_key"),
            "y_axis": chart.get("y_key"),
            "series_length": len(chart.get("rows") or []),
            "rendered": True,
            "note": (
                "The chart is rendered and already visible to the user. Do not "
                "restate its values or announce that a chart was created; "
                "interpret what it shows."
            ),
        }

    return payload


def _dispatch_in_session(registry, name, arguments, context, session_id):
    """Run a tool on a worker thread, carrying the session id across.

    ContextVars do not follow a call into `asyncio.to_thread`, and tools read
    the session from one (`execute_query` scopes its stored result by it), so
    the scope has to be re-entered on the far side.
    """
    with SessionScope(session_id):
        return registry.dispatch(name, arguments, context)


def _provider_failure_message(exc: Exception) -> str:
    """A user-safe explanation of a provider failure."""
    detail = str(exc).lower()
    logging.error("LLM provider chain failed: %s", exc, exc_info=True)
    for needle, message in _SAFE_PROVIDER_HINTS:
        if needle in detail:
            return message
    return (
        "The AI provider could not be reached. The server log has the details; "
        "you can still run SQL directly from the Data tab."
    )

SYSTEM_PROMPT = """You are DataPilot, a data analyst who answers questions about a database in plain language.

## Four rules that override everything else

1. NO CURRENCY SYMBOLS OR UNITS. The database stores bare numbers and names no
   currency anywhere. Write `63,589`. Never `$63,589`, never `63,589 USD`,
   never "sixty-three thousand dollars". Adding a unit the data does not
   contain is a factual error, and revenue figures are not dollars just
   because they are revenue.
2. NO REPEATING THE DATA. The results table is on screen beside your answer.
   Do not restate rows as a Markdown table, a code block, a `key = value`
   list, or a bullet per row. Quote at most the two or three figures your
   point actually rests on, inline in a sentence.
3. NO CLOSING SUMMARY. Do not end with "Thus…", "Overall…", "In summary…",
   "This indicates…" or an offer to help further. Your last sentence must
   carry new information or you must not write it.
4. NO SECTION HEADINGS. No "Explanation", "What it means", "Summary",
   "Results". Write prose and bullets only.

## Tools
1. get_schema — tables, columns, keys. Call once per new database.
2. execute_query — run one read-only SELECT. Never write.
3. generate_chart — visualise a result set. Pass the result_id.
4. generate_flowchart — ER / process / decision diagrams.
5. explain_data — computed statistics over a result set.
6. verify_response — check you delivered what was asked, before finishing.

## Using tools
- SELECT only. The system blocks everything else, so do not try.
- If a query fails, read the error and correct it. At most two retries.
- execute_query returns a result_id and a short preview. Pass the result_id to
  generate_chart and explain_data. Never copy rows between tool calls.
- For a chart: execute_query first, then generate_chart with the result_id.
- Let generate_chart choose the type. Set chart_type only if the user named one.
- For an ER diagram call generate_flowchart with diagram_type='er'.
- Greetings and questions about your capabilities need no tools at all.

## What the user can already see
The SQL you ran, the full results table, and any chart or diagram are rendered
on screen next to your answer, as proper interactive components. This changes
what your answer is for.

NEVER do any of these — each one duplicates something already on screen and
makes the answer worse:
- Reproduce Mermaid source, or any diagram markup, in your reply.
- Re-type the result rows as a Markdown table or a list of every value.
- Restate the SQL you just ran.
- Announce the artifact: "Here is a chart showing…", "The table below lists…",
  "I have generated a diagram". The user can see it. Say what it *means*.
- Write a heading like "Explanation", "Summary" or "Results". Just write.

## Grounding
- Every number you state must come from a tool result. Never estimate, never
  extrapolate, never carry a figure over from an earlier turn.
- Percentages and differences you compute from returned numbers are fine.
- If a result was truncated, say so before drawing a conclusion from it.
- If the data cannot answer the question, say that plainly and say what would.

## How to write the answer
Lead with the finding, in one sentence — the single thing the user would tell a
colleague. Then at most three short bullets of support: the comparison that
matters, an outlier, a trend, a caveat. Stop there.

Use **bold** for the figures that carry the point and `code` for column and
table names. Two to five sentences in total for a simple question.

Follow this shape exactly:

    <one sentence naming the answer and the figure that proves it>

    - <a comparison, trend, outlier or caveat, as a full sentence>
    - <another, only if it adds something>

Every bullet must be a sentence that makes a point. A bullet that only names a
value — "category = Electronics, revenue = 63,589", "Gap: 57,501" — is a row of
the table, and the table is already on screen. Delete it.

Worked example. For "which category earns the most and by how much?" over a
result of Electronics 63589, Accessories 6088, Home 2397, write:

    **Electronics** earns the most at **63,589** — about ten times
    `Accessories`, the next category at 6,088.

    - `Home` is the weakest at 2,397, under 4% of the total.
    - This covers only 16 order lines, so a single large order shifts the
      ranking noticeably.

That answer names three figures, each inside a sentence that says why it
matters. It has no currency symbol, no table, no heading, and no closing
paragraph restating what the reader just read.
"""

# Anchored at both ends, with only punctuation allowed after. A greeting is a
# whole message; matching a prefix meant "help me find the top 5 products by
# revenue" and "hey what is our revenue?" were answered with a canned hello and
# never reached the database at all.
_CONVERSATIONAL_RE = re.compile(
    r"^(hi|hello|hey|thanks|thank you|who are you|what can you do|help)"
    r"(?:\s+there)?[\s!.,?]*$",
    re.IGNORECASE,
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
        self._sessions: "OrderedDict[str, ConversationMemory]" = OrderedDict()

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
                # Evicting the least recently used session bounds the cache.
                # Nothing is lost: a dropped session rehydrates from storage on
                # its next turn, which is the same path a restart takes.
                while len(self._sessions) > MAX_CACHED_SESSIONS:
                    self._sessions.popitem(last=False)
            self._sessions.move_to_end(session_id)
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

        # Whichever database this session is pointed at. Resolved here, not by
        # the model, and refreshed per turn so a mid-conversation switch takes
        # effect immediately. Resolved before the offline branch too, which
        # used to ignore it and always answer from the bundled demo file.
        connection = get_session_connection(get_current_session_id())

        # 2. Offline engine first (if no providers configured).
        if not self.failover:
            offline_reply = answer_offline(message, self.settings, connection)
            if offline_reply and offline_reply.get("type") == "final":
                memory.add_assistant(offline_reply.get("answer", ""))
                if offline_reply.get("table"):
                    memory.set_last_result(offline_reply["table"])
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
            + "\n\n## This database\n"
            + f"{connection.name} ({connection.kind}). Write {connection.dialect} SQL.\n"
            # Today's date: without it "last month" and "this year" are
            # unanswerable, and the model silently guessed a year instead.
            + f"Today is {date.today().isoformat()}.\n"
            # The ceiling is enforced by the SQL guard whatever the model does.
            # Telling it up front stops it writing a LIMIT the guard rejects,
            # and lets it aggregate rather than fetch when a table is large.
            + f"Results are capped at {self.settings.hard_row_ceiling} rows; "
            + "aggregate in SQL rather than pulling rows and counting them.\n"
            + "\n## Schema\n"
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
            # The limiter sleeps, and the whole app runs on one event loop, so
            # calling it directly froze every other request — health checks,
            # other chats, the schema panel — for the length of the wait.
            try:
                await asyncio.to_thread(self.rate_limiter.wait)
            except TimeoutError as exc:
                yield {"type": "error", "message": str(exc)}
                break

            yield {"type": "status_step", "step": "generating_plan"}

            text_parts: list[str] = []
            pending_tool_calls: list[dict[str, Any]] = []
            try:
                # stream_tool_calls is a generator, so calling it raises
                # nothing — AllProvidersFailed surfaces here, on the first
                # iteration. Catching it around the call (as before) caught
                # nothing and the exception escaped into the SSE response.
                for event in self.failover.stream_tool_calls(
                    messages, self._tool_specs(), system_prompt
                ):
                    if event["type"] == "text":
                        text_parts.append(event["text"])
                        yield {"type": "token", "text": event["text"]}
                    elif event["type"] == "tool_call":
                        pending_tool_calls.append(event)
                    elif event["type"] == "error":
                        yield {"type": "error", "message": event.get("message", "")}
            except AllProvidersFailed as exc:
                yield {"type": "error", "message": _provider_failure_message(exc)}
                break
            except ProviderError as exc:
                yield {"type": "error", "message": _provider_failure_message(exc)}
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
                # Tool handlers are synchronous and some are slow — a SQLite
                # query with a 15s watchdog, or explain_data's own LLM call.
                # Running them inline blocked the event loop for that whole
                # time, freezing every other request in the process.
                result = await asyncio.to_thread(
                    _dispatch_in_session,
                    self.registry,
                    call["name"],
                    call.get("arguments", {}),
                    context,
                    get_current_session_id(),
                )
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
                        "content": json.dumps(
                            _model_view(call["name"], tool_payload, result.get("success", False)),
                            default=str,
                        ),
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