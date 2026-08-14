# DataPilot AI

A ChatGPT-like agent that answers natural-language questions about your
database, generates safe read-only SQL, renders charts and ER/flow diagrams,
and explains the results — **all runnable with zero API keys**.

- **No keys required**: an offline template engine answers real data questions
  with real generated SQL when no LLM provider is configured (ideal for
  evaluation and demos). Add any of Gemini / OpenAI / Anthropic keys for fully
  open-ended natural-language understanding via a failover chain.
- **Safe by default**: every query passes a defense-in-depth guard (sqlglot AST
  analysis + quote-aware keyword scan + mandatory row limits). Write operations
  are impossible from the agent.
- **Deterministic visualizations**: chart type is chosen by code rules from the
  data shape, so the same question always produces a sensible chart.
- **Anti-hallucination**: result rows stay server-side; the LLM only ever sees
  summaries and the schema, and a `verify_response` tool checks that requested
  artifacts were actually produced.

---

## Quick start

### Option A — no Docker

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt

# Optional: add LLM keys
copy .env.example .env      # Windows
# cp .env.example .env      # macOS/Linux
# ... edit .env and add one or more provider keys ...

uvicorn main:app --reload
```

Open <http://localhost:8000> (API), <http://localhost:8000/docs> (Swagger UI),
or <http://localhost:8000/health>.

### Option B — Docker

```bash
cd backend
docker compose up --build
```

On first boot the demo e-commerce database is created and seeded automatically.

### Run the tests

```bash
cd backend
pip install -r requirements.txt
pytest -q          # 72 tests, fully offline
```

---

## Try it (no keys needed)

Ask the API anything about the seeded demo store:

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "top 5 products by revenue"}'
```

You get an SSE stream ending with a `final` event containing the answer,
the generated SQL, the chart spec, and row data:

```json
{
  "type": "final",
  "answer": "Top 5 products by revenue. Found 5 row(s) ...",
  "sql": "SELECT p.name AS product, SUM(oi.quantity*oi.unit_price) AS revenue ...",
  "chart": {"type": "bar", "columns": ["product", "revenue"], "rows": [...], ...}
}
```

Other questions that work offline:

- `"top 5 products by revenue"`
- `"monthly revenue trend"`
- `"low stock products"`
- `"show me the ER diagram"`
- `"why did revenue drop in May?"` (investigation)
- `"hello"` (casual reply, zero cost)

With an LLM key configured, any natural-language question is understood:
`"Which product category made the most money last quarter and show it as a pie chart?"`

---

## Architecture

```
backend/
├── main.py                 FastAPI app + router wiring + CORS + seeding
├── config.py               pydantic-settings; all knobs + .env resolution
├── agent/loop.py           DataPilotAgent: hand-written tool-calling loop,
│                           SSE event stream, offline fallback, step cap
├── tools/                  ToolRegistry (the architecture cornerstone)
│   ├── registry.py         ToolDefinition / ToolResult / ToolError
│   ├── builder.py          register the 6 tools + default context
│   ├── get_schema_tool.py
│   ├── execute_query_tool.py
│   ├── generate_chart_tool.py
│   ├── generate_flowchart_tool.py
│   ├── explain_data_tool.py
│   └── verify_response_tool.py
├── db/                     engine (read-only URI), access_layer (timeout +
│                           row cap + truncation), schema discovery, seed,
│                           file ingestion (CSV/XLSX/PDF/DOCX/JSON)
├── security/               sql_guard (sqlglot + quote-aware keyword scan)
│                           and PII masking
├── llm/                    provider clients (OpenAI/Anthropic/Gemini),
│                           failover chain, rate limiter, offline engine
├── viz/                    deterministic chart recommender + mermaid builder
├── memory/                 per-session conversation memory + ContextVar scope
├── store/                  SQLite-backed sessions / messages / dashboard
├── routes/                 /api/chat (SSE), /api/schema, /api/query,
│                           /api/sessions, /api/dashboard, /api/upload, /health
└── tests/                  hermetic tests: fake-LLM harness drives the real
                            agent loop with zero network / zero keys
```

### The agent loop

1. **Casual short-circuit** — greetings/help are answered from a rule table
   with zero LLM/tool cost.
2. **Offline fallback** — if no provider is configured (or all fail), a
   template engine classifies the intent, generates real SQL through the same
   guard, executes it, and returns an answer + chart.
3. **Tool loop** — with a provider, the agent streams tool calls until it has
   enough context, capped at 8 steps. Each tool result is fed back so the
   model can self-correct after a blocked query or a bad tool call.
4. **Bounded and safe** — row caps, hard ceilings, query timeouts, and a
   validation layer make the loop impossible to hang or corrupt data.

### Tools (LLM tool contract)

| Tool | Purpose |
|------|---------|
| `get_schema` | tables, columns, types, PK/FK, row counts |
| `execute_query` | run a guarded read-only SELECT; returns columns+rows (capped) |
| `generate_chart` | build a deterministic ChartSpec (bar/line/pie/scatter/area/kpi) |
| `generate_flowchart` | ER diagram or process/decision flowchart (Mermaid) |
| `explain_data` | statistical + textual explanation of a result set |
| `verify_response` | check requested artifacts (chart/explanation/SQL) exist |

Each tool's JSON schema is generated from a Pydantic model and validated at
dispatch time, so malformed tool calls can never crash the agent.

---

## Configuration

Copy `.env.example` to `.env`. Everything is optional.

| Variable | Default | Meaning |
|----------|---------|---------|
| `DB_PATH` | `data/ecommerce.db` | SQLite database (created+seeded if absent) |
| `MAX_QUERY_ROWS` | 500 | rows returned per query |
| `HARD_ROW_CEILING` | 1000 | absolute LIMIT ceiling injected into SQL |
| `LLM_PROVIDER` | `gemini` | preferred provider for failover ordering |
| `GEMINI_API_KEY` | — | enables Gemini |
| `OPENAI_API_KEY` | — | enables OpenAI |
| `ANTHROPIC_API_KEY` | — | enables Anthropic |
| `LLM_RPM` | 10 | per-user request rate limit |
| `SESSION_TTL_SECONDS` | 86400 | session persistence window |
| `MAX_HISTORY_TURNS` | 6 | conversation turns kept for context |

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | status, DB ready, provider mode |
| GET | `/api/schema` | full schema + ER mermaid |
| POST | `/api/query` | run a guarded SQL query `{sql}` |
| POST | `/api/chat` | SSE chat stream `{message, session_id?}` |
| POST | `/api/sessions` | create a session |
| GET/DELETE | `/api/sessions/{id}` | read / delete a session |
| POST | `/api/upload` | upload CSV/XLSX/PDF/DOCX/JSON → new tables |
| POST | `/api/dashboard/pin` | pin an artifact to a dashboard |
| GET | `/api/dashboard/{session_id}` | read a dashboard |
| DELETE | `/api/dashboard/item/{item_id}` | remove a pinned item |

Full interactive docs at `/docs`.

---

## Security model

- **Read-only SQLite**: connection opens with `mode=ro` URI + `PRAGMA
  query_only`; writes are impossible even if a statement slips past the guard.
- **Guard layers**: empty/multi-statement rejection → sqlglot AST write-node
  scan (fails closed on parse error) → quote-masked whole-word keyword scan
  (so a column value `'delete'` is not a false positive) → mandatory row
  limit with ceiling enforcement.
- **Query timeout + row truncation**: runaway queries are interrupted; result
  sets are capped and marked `truncated`.
- **Error sanitization**: file paths / connection strings are scrubbed from
  surfaced messages.
- **Secrets**: keys are read from `.env` only, resolved server-side, never
  sent to the browser, and placeholders are ignored.