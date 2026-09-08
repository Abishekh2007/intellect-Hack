# DataPilot AI

**Ask your database anything in plain English. Get SQL, tables, charts, diagrams and an explanation.**

DataPilot is a conversational AI agent for database interaction and visualization,
built for **Intellect Hack 2026** — Track 5: Open Innovation, addressing the
challenge *"Building Intelligent LLM Agents for Database Interaction &
Visualization"*.

Type a question. The agent inspects the live schema, writes a **read-only** SQL query,
runs it behind five layers of safety checks, picks a chart type that suits the data,
and explains what the numbers mean — streaming every step to the browser as it happens.


## Quick start

### One click

| Platform | What to run |
| --- | --- |
| Windows | double-click **`DataPilot.exe`** |
| Windows (script) | double-click `start.bat` |
| macOS / Linux | `./start.sh` |

All three do the same thing: on the first run they create a Python virtualenv,
install the backend and frontend packages, and write a `backend/.env`; then they
start both servers, wait for them, and open <http://localhost:8080>. Later runs
skip straight to starting up. Closing the window stops everything.

First run takes 2–3 minutes while packages install. After that it's a few seconds.

To wipe chat history and re-seed the demo database:
`DataPilot.exe reset` · `start.bat reset` · `./start.sh reset`.

> **`DataPilot.exe` needs Python 3.10+ and Node.js on the machine** — it is a
> launcher that removes the setup steps, not a bundle of the whole stack. It tells
> you exactly what's missing and where to get it. Rebuild it any time with
> `tools/build-exe.bat` (needs `pip install pyinstaller`); the source is
> `tools/launcher.py`.

### Docker

```bash
docker compose up --build     # then open http://localhost:8080
```

### Manual

```bash
# API — http://localhost:8000
cd backend
python -m venv .venv && .venv/Scripts/activate      # Windows
# python3 -m venv .venv && source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000

# Web app — http://localhost:8080
cd frontend
npm install        # or: bun install
npm run dev
```

### API keys are optional

Copy `backend/.env.example` to `backend/.env` and add **any one** key:

```ini
OPENAI_API_KEY=sk-...          # or any OpenAI-compatible endpoint
# OPENAI_BASE_URL=https://...  # e.g. DeepSeek, Groq, Together
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
BEDROCK_API_KEY=ABSK...        # Amazon Bedrock API key (bearer token, no SigV4)
# BEDROCK_MODEL=qwen.qwen3-next-80b-a3b
# BEDROCK_REGION=us-east-1
```

**With no key at all the app still works.** A built-in offline engine classifies the
question, runs real template SQL against the real database, and renders real charts.
Nothing is faked and the demo cannot die from an expired key.

---

## What it does

| | |
| --- | --- |
| **Chat** | ChatGPT-style streaming over SSE, with per-step status (`inspecting schema` → `generating plan` → `executing tools`) |
| **SQL** | Generated, shown to you *before* the results, syntax-highlighted, copyable and re-runnable |
| **Charts** | Bar, line, pie, scatter, area and KPI — the type is chosen by server-side rules, not by the model |
| **Diagrams** | ER diagrams from real foreign keys, process flowcharts, decision trees (Mermaid) |
| **Databases** | SQLite and PostgreSQL, switchable per conversation, demo database always one click away |
| **Memory** | Follow-ups resolve against the previous result, and survive a page reload or a server restart |
| **Export** | Charts as PNG or PDF, result sets as CSV |
| **Dashboard** | Pin any chart or diagram, then share it by link |
| **Voice** | Speech-to-text question input where the browser supports it |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser — React 19 · TanStack Start · Tailwind 4           │
│  Chat · ECharts · Mermaid · connection picker · dashboard   │
└───────────────────────────┬─────────────────────────────────┘
                            │  SSE  (token · sql · table · chart · diagram · final)
┌───────────────────────────▼─────────────────────────────────┐
│  FastAPI                                                    │
│                                                             │
│  routes/       chat · connections · database · sessions ·   │
│                dashboard · queries · health                 │
│                                                             │
│  agent/loop.py  hand-written tool-calling loop              │
│                 ├─ bounded to 8 steps                       │
│                 ├─ feeds tool errors back for self-repair   │
│                 └─ falls back to the offline engine         │
│                                                             │
│  tools/         registry of 6 Pydantic-validated tools      │
│  llm/           OpenAI · Anthropic · Gemini + failover      │
│  security/      sql_guard · pii                             │
│  db/            connections · access_layer · schema · pg    │
│  store/         sessions · results · queries                │
│  viz/           chart recommender · mermaid builders        │
└───────────────────────────┬─────────────────────────────────┘
                            │  read-only
                  ┌─────────▼─────────┐
                  │ SQLite │ Postgres │
                  └───────────────────┘
```

### Three deliberate design decisions

**1. The tool registry is the extension point.**
Every tool is a `ToolDefinition` with a Pydantic `input_model`. That model's JSON
Schema is what each provider receives, and validation happens at dispatch, so a
malformed tool call returns a structured error instead of crashing the agent.
Adding a tool is one module plus one line in `tools/builder.py`.

**2. Chart type is decided by code, not by the model.**
`viz/recommender.py` profiles the result columns — numeric ratio, date-likeness,
cardinality — and applies ordered rules. The same question always produces the same
chart, and the model can never pick a type that renders badly. The one thing rules
cannot infer from shape is *intent*: `revenue by category` and `top 5 products by
revenue` are structurally identical, but only the first describes a whole being
divided up. So pie additionally requires share-of-total wording in the question.

**3. Result rows stay on the server.**
`execute_query` returns a `result_id`, the result's shape, and a 20-row preview.
`generate_chart` and `explain_data` take that id and read the full rows server-side.
A 500-row result costs the same context as a 5-row one, charts cover every row
rather than the handful the model could retype, and statistics are computed —
never paraphrased.

---

## The agent tools

All six are defined in `backend/tools/` and registered in `tools/builder.py`.

### `get_schema`
Retrieve tables, columns, types, primary keys and foreign keys.

| | |
| --- | --- |
| **Input** | `scope: str = "full"` — `"full"`, or a table name |
| **Returns** | `{ tables: [{ name, columns: [{name, type, nullable, pk}], primary_keys, foreign_keys }], table_names }` |
| **Errors** | `tool_execution_error` if the database is unreachable |

### `execute_query`
Run one read-only `SELECT` and park the result server-side.

| | |
| --- | --- |
| **Input** | `query: str` — a single read-only SELECT |
| **Returns** | `{ result_id, sql, columns, column_types, row_count, truncated, execution_time_ms, rows_for_your_reasoning_only }` — a bounded row sample, deliberately named so the model treats it as working data rather than output to reprint |
| **Errors** | `unsafe_statement`, `multi_statement`, `forbidden_keyword`, `limit_too_high`, `parse_error`, `timeout`, `sql_error` — all recoverable, so the model reads the message and corrects itself |

### `generate_chart`
Build a chart specification the frontend renders with ECharts.

| | |
| --- | --- |
| **Input** | `result_id: str?` (preferred), `data: [{col: val}]?`, `chart_type: str?`, `title: str` |
| **Returns** | `{ chart: { type, columns, x_key, y_key, rows, title } }` |
| **Types** | `bar` · `line` · `pie` · `scatter` · `area` · `kpi` |
| **Errors** | `unknown_result_id` if the reference expired, `invalid_arguments` on a bad shape |

### `generate_flowchart`
Produce Mermaid diagrams. Generated deterministically, never by the model, so a
diagram can't fail to parse.

| | |
| --- | --- |
| **Input** | `diagram_type: "er" \| "process" \| "decision"`, `steps: [str]?`, `nodes: [{label, type, parent, edge}]?`, `title: str` |
| **Returns** | `{ diagram_type, mermaid }` |

### `explain_data`
Compute descriptive statistics server-side, then narrate them.

| | |
| --- | --- |
| **Input** | `result_id: str?` (preferred), `data: [{col: val}]?`, `context: str` |
| **Returns** | `{ explanation, statistics, grounded_summary, source: "llm" \| "computed" }` |

The model receives only the computed statistics plus a few verbatim rows — never the
full result — so every figure it quotes was actually measured. If no provider is
configured, or one fails, the deterministic summary is returned instead.

### `verify_response`
A self-audit step: compare what the user asked for against what was produced, and
report honestly when something is missing.

| | |
| --- | --- |
| **Input** | `user_request: str`, `produced: {chart: bool, diagram: bool, explanation: bool}` |
| **Returns** | `{ status: "complete"\|"partial"\|"failed", requested_artifacts, delivered_artifacts, missing_artifacts, completion_ratio }` |

---

## Security

Untrusted SQL from a language model is the central risk. Five independent layers
stand between the model and the database, in `security/sql_guard.py`,
`db/engine.py`, `db/access_layer.py` and `db/postgres.py`:

1. **Statement parsing** — sqlglot parses in the *target dialect* and the AST is
   walked for any `Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Create`,
   `TruncateTable`, `Merge`, `Copy`, `Command` or `Pragma` node. Unparseable SQL
   fails closed.
2. **Quote-masked keyword scan** — string literals are blanked before scanning for
   forbidden keywords, so a product literally named `'DROP'` is not a false
   positive while a real `DROP` still is.
3. **Row-limit rewriting** — the AST is rewritten to enforce a `LIMIT`, and a query
   asking for more than the ceiling is rejected.
4. **A physically read-only connection** — SQLite opens `file:...?mode=ro` plus
   `PRAGMA query_only=ON`; PostgreSQL connects with
   `default_transaction_read_only=on`. Even a write that somehow passed every check
   above cannot succeed.
5. **Timeouts** — a watchdog interrupts a long SQLite query; PostgreSQL enforces
   `statement_timeout` server-side, and connections time out in 5s so a wrong host
   fails fast instead of hanging.

Alongside those:

- **PII masking** (`security/pii.py`) runs inside `execute_read_only`, the single
  chokepoint every query passes through — so emails, phone numbers, card and
  government-ID patterns are masked before results reach the browser *or* the model.
- **Multi-statement input is rejected**, closing off stacked-query injection.
- **The database is chosen server-side** from the session id, never from a tool
  argument, so the model cannot redirect a query at a database the user didn't pick.
- **Database errors are sanitized** — file paths and connection strings are stripped.
- **Credentials never reach the browser**: connection URLs are redacted to
  `postgresql://user@host/db` in every API response.
- **No hardcoded keys** — configuration is `.env` only, and `.env` is gitignored.

---

## Requirements coverage

### Required tools (§4.2)

| Tool | Status | Implementation |
| --- | --- | --- |
| `get_schema` | Yes | `tools/get_schema_tool.py` |
| `execute_query` | Yes | `tools/execute_query_tool.py` |
| `generate_chart` | Yes | `tools/generate_chart_tool.py` |
| `generate_flowchart` | Yes | `tools/generate_flowchart_tool.py` |
| `explain_data` | Yes | `tools/explain_data_tool.py` |
| *(extra)* `verify_response` | Yes | `tools/verify_response_tool.py` |

### Visualization (§4.3)

| Requirement | Status | Where |
| --- | --- | --- |
| Bar chart | Yes | `viz/recommender.py` → `components/artifacts.tsx` |
| Line chart | Yes | same |
| Pie chart | Yes | same |
| Scatter plot *(bonus)* | Yes | same |
| ER diagram | Yes | `viz/mermaid_builder.py` — built from real foreign keys |
| Process flow diagram | Yes | same |
| Decision tree *(bonus)* | Yes | same |

### Chat interface (§4.1)

| Requirement | Status |
| --- | --- |
| Real-time streaming responses | Yes — SSE, token by token |
| Message history within a session | Yes — SQLite-backed, survives restart |
| Clear processing indication | Yes — per-step status and a tool chip |
| Embedded visualization in chat | Yes — charts, tables and diagrams render inline |

### Bonus challenges (§10) — all seven

| Challenge | Status |
| --- | --- |
| NL→SQL explanation | Yes — the generated SQL is streamed and rendered ahead of the result table, with a Copy and a Run button. Note it is executed first and displayed immediately after, rather than held for approval before running. |
| Multi-database support | Yes — SQLite + PostgreSQL, switchable per conversation |
| Export as PNG / PDF / CSV | Yes — `lib/export-utils.ts` |
| Voice input | Yes — `hooks/use-speech.ts` |
| Query history & favourites | Yes — `store/query_store.py`, History tab |
| Collaborative sharing | Yes — persisted share links, `/shared/:id` |
| Custom dashboard builder | Yes — pin charts and diagrams, Pinned tab |

### Code requirements (§8.2)

| Requirement | Status |
| --- | --- |
| Clean, commented code | Yes |
| `.env` configuration, no hardcoded keys | Yes |
| Docker support | Yes — `docker compose up --build` |
| Unit tests *(bonus)* | Yes — **125 tests** |

---

## Testing

```bash
cd backend
python -m pytest -q          # 157 tests
```

Coverage includes the SQL guard's bypass attempts, the tool registry and every
tool, the agent loop driven by a scripted fake LLM (no network, no keys), the
offline engine, chart-type selection, provider request shapes with the SDKs patched
out, and a regression test for each defect found during review.

The PostgreSQL tests run against a real server when one is reachable and skip
otherwise:

```bash
docker run -d --name datapilot-pg \
  -e POSTGRES_PASSWORD=datapilot -e POSTGRES_USER=datapilot -e POSTGRES_DB=shop \
  -p 55432:5432 postgres:16-alpine

# optional: point them elsewhere
export DATAPILOT_TEST_PG_URL=postgresql://user:pass@host:5432/db
```

---

## Project layout

```
backend/
  agent/loop.py            the tool-calling loop
  tools/                   registry + the six tools
  llm/                     providers, failover, offline engine
  security/                sql_guard.py, pii.py
  db/                      connections, access layer, schema discovery, postgres
  store/                   sessions, results, query history
  viz/                     chart recommender, mermaid builders
  routes/                  FastAPI routers
  tests/                   125 tests
frontend/src/
  components/              Chat, artifacts, RightPanel, ConnectionPicker, Sidebar
  lib/                     api client + SSE parser, app state, export utils
  routes/                  TanStack Start routes
tools/
  launcher.py              source for DataPilot.exe
  build-exe.bat            rebuilds the exe with PyInstaller
DataPilot.exe              one-click launcher (Windows)
start.bat / start.sh       same thing as scripts
docker-compose.yml         API + web app
```

## API

Interactive docs at <http://localhost:8000/docs>.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/chat` | Stream an agent turn (SSE) |
| `GET` | `/api/schema` | Schema of the session's database |
| `POST` | `/api/query` | Run a read-only query directly |
| `GET` | `/api/connections` | List databases and the active one |
| `POST` | `/api/connections/postgres` | Register a PostgreSQL database |
| `POST` | `/api/sessions/{id}/connection` | Point a session at a database |
| `POST` | `/api/sessions/{id}/connection/reset` | Back to the demo database |
| `GET/POST/PATCH/DELETE` | `/api/sessions` | Manage conversations |
| `POST` | `/api/dashboard/pin` | Pin a chart or diagram |
| `POST` | `/api/share` | Create a shareable link |
| `GET` | `/health` | Status, database and provider mode |

## Tech stack

**Backend** — Python 3.11+, FastAPI, Pydantic v2, sqlglot, SQLAlchemy, psycopg, pytest
**Frontend** — React 19, TanStack Start, Tailwind CSS 4, ECharts, Mermaid, Framer Motion
**Databases** — SQLite (bundled demo), PostgreSQL
**LLM** — OpenAI-compatible, Anthropic, or Google Gemini, with automatic failover
