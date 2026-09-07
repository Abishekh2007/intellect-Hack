# DataPilot AI — backend

A ChatGPT-like agent that answers natural-language questions about your
database, generates safe read-only SQL, renders charts and ER/flow diagrams,
and explains the results — **all runnable with zero API keys**.

- **No keys required**: an offline template engine answers real data questions
  with real generated SQL when no LLM provider is configured (ideal for
  evaluation and demos). Add any of Bedrock / Gemini / OpenAI / Anthropic keys
  for fully open-ended natural-language understanding via a failover chain.
- **Safe by default**: every query passes a defense-in-depth guard (sqlglot AST
  analysis + quote-aware keyword scan + mandatory row limits). Write operations
  are impossible from the agent.
- **Deterministic visualizations**: chart type is chosen by code rules from the
  data shape, so the same question always produces the same sensible chart.
- **Anti-hallucination**: result rows stay server-side; the LLM only ever sees
  summaries and the schema, and a `verify_response` tool checks that requested
  artifacts were actually produced.

> Every command, payload and number in this document was captured from a live
> run of this code against the seeded demo database in **offline mode** (no API
> keys). If you paste the commands below you should see exactly these values.

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

Open <http://localhost:8000> (API root), <http://localhost:8000/docs>
(Swagger UI), or <http://localhost:8000/health>.

Python 3.11 is what the Dockerfile and the pinned dependency set are built and
tested against.

### Option B — Docker

```bash
cd backend
docker compose up --build
```

On first boot the demo e-commerce database is created and seeded automatically
(`ensure_seeded` runs in the FastAPI lifespan hook), and the container exposes
a `/health` HEALTHCHECK.

### 30-second smoke test

```bash
curl -s http://localhost:8000/health
```

```json
{"status":"ok","database":"ready","llm_provider":"offline_mode","app":"DataPilot AI"}
```

`llm_provider` is the single field that tells you which brain is answering:

| Value | Meaning |
|-------|---------|
| `offline_mode` | No usable provider key. Template engine answers; `final.mode` will be `"offline"`. |
| `configured` | At least one real key was found. The tool-calling loop answers; `final.mode` will be `"agent"`. |

A placeholder key (`your_key_here`, `sk-xxx`, `changeme`, `none`, …) is
deliberately treated as *absent*, so a half-filled `.env` degrades to the
offline demo instead of failing at request time.

### Run the tests

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

```
166 passed, 7 skipped in ~28s
```

Fully hermetic: no network, no API keys, a temp-seeded database per session.
The 7 skips are the PostgreSQL integration tests, which skip themselves when no
server is reachable (`no PostgreSQL server reachable for this test`). Start one
with `docker compose up -d db` to un-skip them.

---

## The demo dataset

The bundled database (`data/ecommerce.db`) is a small, **deterministic**
e-commerce store — the same rows every run, so demo answers are reproducible
and reviewable by hand.

| Table | Rows | Columns |
|-------|-----:|---------|
| `customers` | 7 | `customer_id` PK, `name`, `email`, `city`, `signup_date` |
| `products` | 7 | `product_id` PK, `name`, `category`, `price`, `stock` |
| `orders` | 15 | `order_id` PK, `customer_id` FK, `order_date`, `status` |
| `order_items` | 16 | `order_item_id` PK, `order_id` FK, `product_id` FK, `quantity`, `unit_price` |
| `inventory` | 7 | `inventory_id` PK, `product_id` FK, `warehouse`, `stock_level`, `updated_at` |

```mermaid
erDiagram
    customers ||--o{ orders : "customer_id"
    orders    ||--o{ order_items : "order_id"
    products  ||--o{ order_items : "product_id"
    products  ||--o{ inventory : "product_id"
```

Facts worth knowing before you demo it:

- **Date range**: orders span `2024-05-01` → `2024-06-18`; signups span
  `2024-01-15` → `2024-06-11`. Only two months exist, so "monthly trend"
  returns exactly 2 points.
- **Order statuses**: 12 `completed`, 2 `pending`, 1 `cancelled`.
- **Revenue depends on the filter.** Gross line-item value is **72,074**;
  revenue over `status='completed'` only is **57,578**. Every revenue template
  filters on `status='completed'` — the 14,496 difference is a pending Monitor
  order, a cancelled cable order and a pending lamp.
- **Average completed order value**: 4,798.17.
- **Warehouses**: Chennai WH (3 SKUs, 275 units), Mumbai WH (3 SKUs, 680),
  Delhi WH (1 SKU, 90).

### Known-good answers (your cheat sheet)

Revenue by product, completed orders only:

| Product | Revenue |
|---------|--------:|
| Monitor 24in | 25,998 |
| Noise Cancelling Headphones | 15,998 |
| Mechanical Keyboard | 4,998 |
| Wireless Mouse | 3,596 |
| USB-C Cable | 2,792 |
| Laptop Stand | 2,598 |
| Desk Lamp | 1,598 |

| Month | Revenue | | Category | Revenue | | City | Revenue |
|---|--:|---|---|--:|---|---|--:|
| 2024-05 | 20,336 | | Electronics | 50,590 | | Hyderabad | 25,998 |
| 2024-06 | 37,242 | | Accessories | 5,390 | | Chennai | 14,642 |
| | | | Home | 1,598 | | Bengaluru | 7,999 |
| | | | | | | Mumbai | 4,242 |
| | | | | | | Delhi | 2,499 |
| | | | | | | Ahmedabad | 2,198 |

**Demo talking point.** Ask for "top 5 products by revenue", then point at the
returned SQL: `WHERE o.status='completed'`. Monitor 24in shows 25,998 — not
38,997 — because a third Monitor sits in a *pending* order. The number the user
sees is defended by SQL they can read, not by prose.

---

## Guided demo (offline, ~5 minutes)

Every response below is verbatim from a real run. `curl` examples use POSIX
quoting; on Windows PowerShell see [PowerShell equivalents](#powershell-equivalents).

### Act 1 — prove there is no LLM in the loop

```bash
curl -s http://localhost:8000/health
# {"status":"ok","database":"ready","llm_provider":"offline_mode","app":"DataPilot AI"}
```

Say the quiet part out loud: **there is no key configured**, and the next
answers are still real SQL against real rows.

### Act 2 — a greeting costs nothing

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
```

```
event: final
data: {"type":"final","answer":"Hello! I'm DataPilot, your AI data analyst. Try asking me things like \"top 5 products by revenue\" or \"show me the ER diagram\".","sql":null,"table":null,"chart":null,"diagram":null,"mode":"rule"}
```

`"mode":"rule"` — matched by a rule table before any provider, tool or query is
touched. Greetings, thanks, "who are you" and "what can you do" never spend a
token or open the database.

### Act 3 — the headline question

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "top 5 products by revenue"}'
```

One `final` event carries everything the UI needs:

```json
{
  "type": "final",
  "mode": "offline",
  "answer": "Top 5 products by revenue.\n\nFound 5 row(s).\n- product=Monitor 24in, revenue=25998.0\n- product=Noise Cancelling Headphones, revenue=15998.0\n- product=Mechanical Keyboard, revenue=4998.0\n- product=Wireless Mouse, revenue=3596.0\n- product=USB-C Cable, revenue=2792.0",
  "sql": "SELECT p.name AS product, SUM(oi.quantity*oi.unit_price) AS revenue FROM order_items oi JOIN products p ON oi.product_id=p.product_id JOIN orders o ON oi.order_id=o.order_id WHERE o.status='completed' GROUP BY p.name ORDER BY revenue DESC LIMIT 5",
  "table": {
    "columns": ["product", "revenue"],
    "rows": [["Monitor 24in", 25998.0], ["Noise Cancelling Headphones", 15998.0],
             ["Mechanical Keyboard", 4998.0], ["Wireless Mouse", 3596.0],
             ["USB-C Cable", 2792.0]],
    "row_count": 5,
    "truncated": false
  },
  "chart": {
    "type": "bar", "x_key": "product", "y_key": "revenue",
    "columns": ["product", "revenue"],
    "rows": [["Monitor 24in", 25998.0], "…"],
    "recommended": true, "title": "Top 5 products by revenue."
  },
  "diagram": null
}
```

Three things to point at:

1. **`sql` is real and auditable** — the answer text and the chart are both
   derived from that one statement, not from the model's memory.
2. **`chart.recommended: true`** — nothing chose "bar" by vibes; the
   recommender saw one text column, one numeric column, one row per label.
3. **`table` ships with the answer** — so the grid, the chart and the prose can
   never disagree with each other.

### Act 4 — the chart type follows the data, and obeys you

```bash
curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "monthly revenue trend"}'
# -> chart.type = "line"   rows: [["2024-05",20336.0],["2024-06",37242.0]]

curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "revenue by category"}'
# -> chart.type = "bar"    rows: Electronics 50590, Accessories 5390, Home 1598

curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "sales by category as a pie chart"}'
# -> chart.type = "pie"    same rows, honoring the explicit request
```

Same data, three shapes: a time series becomes a line, a comparison becomes a
bar, and an explicit "as a pie chart" overrides the default. Chart choice lives
in `viz/recommender.py`, in code, so it is testable and never varies run to run.

### Act 5 — a diagram, not a query

```bash
curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "show me the ER diagram"}'
```

```json
{"type":"final","mode":"offline",
 "answer":"Here is the entity-relationship diagram for this database.",
 "sql":null,"table":null,"chart":null,
 "diagram":{"type":"er","mermaid":"erDiagram\n    products ||--o{ inventory : \"product_id\"\n    products ||--o{ order_items : \"product_id\"\n    orders ||--o{ order_items : \"order_id\"\n    customers ||--o{ orders : \"customer_id\"\n    customers {\n        INTEGER customer_id PK\n    }\n …"}}
```

The Mermaid is built from live foreign-key introspection, so it redraws itself
for an uploaded database too.

### Act 6 — hostile input bounces off

```bash
curl -s -X POST http://localhost:8000/api/query -H "Content-Type: application/json" \
  -d '{"sql": "DROP TABLE customers"}'
```

```json
HTTP 400
{"detail":{"type":"unsafe_statement",
           "message":"Only read-only queries (SELECT) are allowed. Write operations are blocked."}}
```

```bash
curl -s -X POST http://localhost:8000/api/query -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM products; DELETE FROM products"}'
```

```json
HTTP 400
{"detail":{"type":"multi_statement",
           "message":"Multiple statements are not allowed; send a single SELECT query."}}
```

Now the part most guards get wrong — a **false positive**:

```bash
curl -s -X POST http://localhost:8000/api/query -H "Content-Type: application/json" \
  --data-binary "{\"sql\": \"SELECT name FROM products WHERE name = 'delete'\"}"
```

```json
HTTP 200
{"sql":"SELECT name FROM products WHERE name = 'delete' LIMIT 500",
 "columns":["name"],"rows":[],"row_count":0,"truncated":false,"execution_time_ms":0.51}
```

The word `delete` inside a string literal is data, not danger: literals are
quote-masked before the keyword scan, so a naive `if "delete" in sql` guard
fails this test and this one does not. Note also the **`LIMIT 500` that was not
in the request** — the guard injects it:

```bash
curl -s -X POST http://localhost:8000/api/query -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM products"}'
# {"sql":"SELECT * FROM products LIMIT 500","row_count":7,"truncated":false, …}
```

### Act 7 — bring your own data

```bash
printf 'region,units,revenue\nNorth,120,45000\nSouth,80,31000\nEast,150,52000\nWest,60,21000\n' > sales_q1.csv

SID=$(curl -s -X POST http://localhost:8000/api/sessions \
        -H "Content-Type: application/json" -d '{"title":"Upload demo"}' | jq -r .session_id)

curl -s -X POST "http://localhost:8000/api/upload-file?session_id=$SID" -F "file=@sales_q1.csv"
```

```json
{"ok": true,
 "info": {"table_name": "sales_q1", "columns": ["region","units","revenue"],
          "row_count": 4, "source": "sales_q1.csv"},
 "connection": {"id": "1569e05ee506", "name": "Imported data (sales_q1.csv)",
                "kind": "sqlite", "is_demo": false, "location": "workbook.db"}}
```

The import lands in a **new workbook database owned by this session**, and only
this session is switched to it — the shared demo file is never written to:

```bash
curl -s "http://localhost:8000/api/connections?session_id=$SID"
# connections: [demo (is_demo:true), "Imported data (sales_q1.csv)"]   active_id: 1569e05ee506
```

Columns are typed from the data (`region` → TEXT, `units`/`revenue` → INTEGER)
and the table is immediately queryable and chartable:

```bash
curl -s -X POST "http://localhost:8000/api/query?session_id=$SID" \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT region, revenue FROM sales_q1 ORDER BY revenue DESC"}'
# East 52000, North 45000, South 31000, West 21000
```

Accepted formats: **`.csv` `.xlsx` `.xls` `.pdf` `.docx` `.json`** (25 MB cap,
100,000 rows), plus whole SQLite files via `/api/upload` (`.db` `.sqlite`
`.sqlite3`, 50 MB cap). Uploads stream and are rejected *at* the size threshold
rather than after buffering the whole body.

To return to the demo data mid-presentation:

```bash
curl -s -X POST "http://localhost:8000/api/sessions/$SID/connection/reset"
```

### Act 8 — it remembers, pins and shares

```bash
curl -s http://localhost:8000/api/sessions/$SID2
```

```json
{"session": {"id": "7413…", "title": "History demo", "created_at": "…", "updated_at": "…"},
 "messages": [
   {"role": "user", "content": "top 3 products by revenue", "payload": {}},
   {"role": "assistant", "content": "Top 3 products by revenue. …",
    "payload": {"sql": "…", "table": {"…"}, "chart": {"…"}, "diagram": null, "mode": "offline"}}]}
```

History is SQLite-backed, not `localStorage`: **the artifacts come back too**,
so a reloaded thread still renders its charts and tables, and follow-up
questions ("chart those", "why?") still resolve against the last result.

```bash
curl -s -X POST http://localhost:8000/api/dashboard/pin -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID2\",\"kind\":\"chart\",\"title\":\"Top products\",\"payload\":{\"type\":\"bar\"}}"
# {"item_id":"de9a7ad08a9d49c3800c6076d9b5aaca"}

curl -s -X POST http://localhost:8000/api/share -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID2\"}"
# {"share_id":"34234095","url":"/shared/34234095"}
```

### PowerShell equivalents

```powershell
Invoke-RestMethod http://localhost:8000/health

$body = @{ message = "top 5 products by revenue" } | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8000/api/chat `
  -ContentType "application/json" -Body $body
# SSE arrives as one text blob; the last `data:` line is the final event.
```

---

## What the offline engine actually answers

With no key configured, intent is matched by regex and answered with a template
query. This is the full, verified coverage map — useful for scripting a demo,
and honest about the edges.

| Ask (any phrasing that matches) | Result | Chart |
|---|---|---|
| `hi` · `hello` · `hey` · `thanks` · `who are you` · `what can you do` · `help` | canned reply, no DB access (`mode: "rule"`) | — |
| `show me the ER diagram` · `schema diagram` · *…relationship…* | Mermaid `erDiagram` from live introspection | — |
| `monthly revenue trend` · `revenue over time` · `revenue by month` | revenue grouped by `substr(order_date,1,7)` | line |
| `top 5 products by revenue` (any N) | revenue per product, completed orders only | bar |
| `revenue by category` · `sales by category` | revenue per `products.category` | bar (pie if asked) |
| `revenue by city` · `sales by region` | revenue per `customers.city` | bar |
| `low stock products` · `inventory levels` · `running out of stock` | products by ascending `stock`, LIMIT 10 | bar |
| `top 5 products` · `top 5 most ordered products` | order-line count per product | bar |
| `orders per month` · `monthly orders` | distinct completed orders per month | line |
| anything else | order-count / distinct-customer overview | kpi |

Notes for demoing this honestly:

- **Add "as a pie chart" / "bar chart" / "line chart"** to any of the above and
  the requested type wins over the default.
- **"top N" is clamped** to the offline row budget (200). `top 999999 products
  by revenue` answers *"Top 200 products by revenue"* rather than building SQL
  its own guard would then reject — that failure used to be reported as a
  missing API key, which blamed entirely the wrong thing.
- **Customer-level questions are not in the offline template set.** `top 3
  customers by revenue` is caught by the earlier *top-N + revenue* rule and
  answers about **products**; `revenue by customer` falls through to the KPI
  overview. Demo customer questions **with a key configured**, or stay on
  product / category / city / month / stock questions offline.
- **"Why did X drop?" is not an offline investigation** — it returns the KPI
  overview. Root-cause narration needs a provider.
- Templates assume the demo schema. Against an uploaded database that does not
  match, the engine returns a plain-language explanation ("the templates in
  offline mode assume the demo schema — add an LLM API key…") rather than an
  SQL stack trace.

**With any provider key set**, none of the above applies: the tool-calling loop
writes its own SQL for arbitrary questions, e.g. *"Which product category made
the most money last quarter and show it as a pie chart?"*

---

## The streaming contract (`POST /api/chat`)

Server-Sent Events, `text/event-stream`, `X-Accel-Buffering: no` so proxies do
not hold frames back. Each frame is `event: <type>` + `data: <json>`, and the
JSON repeats its own `type`.

| Event | Payload | Emitted when |
|-------|---------|--------------|
| `status_step` | `{step}` — `inspecting_schema` · `generating_plan` · `executing_tools` | phase transitions; drives the "thinking" UI |
| `status` | `{label}`, e.g. `"Thinking..."` | before the provider call |
| `token` | `{text}` | model prose, streamed |
| `tool_call` | `{name, arguments}` | a tool is about to run |
| `sql` | `{sql}` | `execute_query` succeeded |
| `table` | `{columns, rows, row_count, truncated}` | with the SQL above |
| `chart` | `{chart}` | `generate_chart` succeeded |
| `diagram` | `{diagram}` | `generate_flowchart` succeeded |
| `tool_result` | `{name, error}` | a tool **failed** — fed back to the model to self-correct |
| `error` | `{message}` | provider outage / unexpected failure |
| `final` | `{answer, sql, table, chart, diagram, mode}` | always last |

**Offline and rule mode emit exactly one frame** — the `final` — so a client
that only handles `final` still works completely:

```
event: final
data: {"type":"final","answer":"Top 5 products by revenue.\n\nFound 5 row(s)…",
       "sql":"SELECT p.name AS product, …","table":{…},"chart":{…},
       "diagram":null,"mode":"offline"}
```

**Agent mode** streams the whole reasoning trace. Real sequence for *"top 5
products by revenue"*:

```
status_step  {"step": "inspecting_schema"}
status       {"label": "Thinking..."}
status_step  {"step": "generating_plan"}
token        {"text": "Monitor 24in leads on revenue."}
status_step  {"step": "executing_tools"}
tool_call    {"name": "execute_query", "arguments": {"query": "SELECT p.name AS product, …"}}
sql          {"sql": "SELECT p.name AS product, …"}
table        {"columns": ["product","revenue"], "row_count": 5, …}
tool_call    {"name": "generate_chart", "arguments": {"chart_type": "bar"}}
chart        {"chart": {"type": "bar", …}}
status_step  {"step": "generating_plan"}
token        {"text": "Here are the results."}
final        {"answer": "…", "mode": "agent", "sql": "…", "table": {…}, "chart": {…}}
```

`final.mode` is the one field to assert on in a demo or a test:

| `mode` | Path taken |
|--------|-----------|
| `rule` | conversational short-circuit — no provider, no tool, no query |
| `offline` | template engine — real SQL, no provider |
| `agent` | tool-calling loop with a provider |
| `error` | no provider *and* the offline engine could not help |

Everything in `final` is what gets **persisted** to the session, so any field
missing there is lost on reload — which is why the offline and agent paths
build it through the same shape.

Reading the stream by hand:

```bash
curl -N -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" -d '{"message":"top 5 products by revenue"}' \
  | grep "^data: " | sed "s/^data: //" | jq -c "{type, mode, sql}"
```

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
│                           connection registry, postgres, file ingestion
├── security/               sql_guard (sqlglot + quote-aware keyword scan)
│                           and PII masking
├── llm/                    provider clients (Bedrock/Gemini/OpenAI/Anthropic),
│                           failover chain, rate limiter, offline engine
├── viz/                    deterministic chart recommender + mermaid builder
├── memory/                 per-session conversation memory + ContextVar scope
├── store/                  SQLite-backed sessions / messages / dashboard,
│                           server-side result store, query log
├── routes/                 /api/chat (SSE), /api/schema, /api/query,
│                           /api/sessions, /api/connections, /api/dashboard,
│                           /api/upload, /api/queries, /health
└── tests/                  hermetic tests: fake-LLM harness drives the real
                            agent loop with zero network / zero keys
```

### The agent loop

1. **Casual short-circuit** — greetings/help are answered from a rule table
   with zero LLM/tool cost (`mode: "rule"`).
2. **Connection resolution** — the database this session is pointed at is
   resolved server-side, per turn, *before* either branch below. It is never a
   tool argument, so the model cannot redirect a query at another database.
3. **Offline fallback** — with no provider configured (or all of them failing),
   the template engine classifies the intent, generates real SQL through the
   same guard, executes it, and returns an answer + chart (`mode: "offline"`).
4. **Tool loop** — with a provider, the agent streams tool calls until it has
   enough context, capped at 8 steps. Each tool result is fed back so the model
   can self-correct after a blocked query or a bad tool call. The system prompt
   is rebuilt per turn with the live schema, today's date, the dialect of the
   active connection, and the row ceiling.
5. **Bounded and safe** — row caps, hard ceilings, a 15-second query watchdog
   and a validation layer make the loop impossible to hang or corrupt data.
   Tool handlers run on a worker thread, so a slow query never blocks the event
   loop for other requests.

### Tools (LLM tool contract)

| Tool | Arguments | Purpose |
|------|-----------|---------|
| `get_schema` | `scope` — `"full"` or a table name | tables, columns, types, PK/FK, row counts |
| `execute_query` | `query` — one read-only SELECT | guarded execution; returns a **summary + `result_id`**, not the rows |
| `generate_chart` | `result_id` or `data`, `chart_type?`, `title?` | deterministic ChartSpec (bar/line/pie/scatter/area/kpi) |
| `generate_flowchart` | `diagram_type` (`er`/`process`/`decision`), `steps?`, `nodes?`, `title?` | Mermaid diagram |
| `explain_data` | `result_id` or `data`, `context?` | statistical + textual explanation of a result set |
| `verify_response` | `user_request`, `produced` | check requested artifacts (chart/explanation/SQL) exist |

Each tool's JSON schema is generated from a Pydantic model and validated at
dispatch time, so a malformed tool call returns a structured, *recoverable*
error instead of crashing the agent:

```json
{"success": false,
 "error": {"type": "invalid_arguments",
           "message": "Invalid arguments for execute_query: 1 validation error … query Field required",
           "recoverable": true}}
```

That error is handed straight back to the model as the tool result, which is
how the loop self-corrects inside its step budget.

**The rows never reach the model.** `execute_query` parks the full result
server-side in the result store and returns its shape plus a `result_id`; the
model passes that id to `generate_chart` / `explain_data`. A 500-row result
therefore costs the same context as a 5-row one, and the model cannot
paraphrase — or invent — a value it was never shown.

---

## Configuration

Copy `.env.example` to `.env`. **Everything is optional** — with an empty file
you get the full offline demo.

| Variable | Default | Meaning |
|----------|---------|---------|
| `DB_PATH` | `data/ecommerce.db` | SQLite database, resolved relative to `backend/` (created + seeded if absent) |
| `MAX_QUERY_ROWS` | 500 | default `LIMIT` injected when a query names none |
| `HARD_ROW_CEILING` | 1000 | absolute ceiling the guard enforces |
| `LLM_PROVIDER` | `bedrock` | preferred provider; the rest follow as failover |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-2.0-flash` | enables Gemini |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | — / `gpt-4o-mini` | enables OpenAI |
| `OPENAI_BASE_URL` | — | OpenAI-compatible endpoints (DeepSeek, Groq, Together, …) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / `claude-opus-5` | enables Anthropic |
| `BEDROCK_API_KEY` | — | Amazon Bedrock bearer token (alias: `AWS_BEARER_TOKEN_BEDROCK`) |
| `BEDROCK_MODEL` | `qwen.qwen3-next-80b-a3b` | any Converse-capable Bedrock model id |
| `BEDROCK_REGION` | `us-east-1` | Bedrock runtime region |
| `LLM_RPM` | 10 | per-user request rate limit (sliding window) |
| `SESSION_TTL_SECONDS` | 86400 | session persistence window |
| `MAX_HISTORY_TURNS` | 6 | conversation turns kept for context |
| `CORS_ORIGINS` | localhost 3000/5173 | allowed browser origins |

Providers are tried in `LLM_PROVIDER` order, then bedrock → gemini → openai →
anthropic. If every configured provider fails, the request **falls back to the
offline engine** rather than erroring — a demo survives an outage.

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | app name + links to `/docs` and `/health` |
| GET | `/health` | status, DB ready, provider mode |
| POST | `/api/chat` | SSE chat stream `{message, session_id?}` |
| GET | `/api/schema` | `{tables:[…]}` for the session's database (`?session_id=`) |
| POST | `/api/query` | run a guarded SQL query `{sql}` (`?session_id=`) |
| GET | `/api/table-preview/{table}` | first 50 rows; table name validated against the live schema |
| GET | `/api/sessions` | list sessions |
| POST | `/api/sessions` | create a session `{title}` |
| GET | `/api/sessions/{id}` | session + messages **with their artifacts** |
| PATCH | `/api/sessions/{id}` | rename `{title}` |
| DELETE | `/api/sessions/{id}` | delete a session |
| GET | `/api/connections` | registered databases + `active_id` for the session |
| POST | `/api/connections/postgres` | register PostgreSQL `{name, url}` (verified before saving) |
| DELETE | `/api/connections/{id}` | remove a connection |
| POST | `/api/sessions/{id}/connection` | point a session at a connection `{connection_id}` |
| POST | `/api/sessions/{id}/connection/reset` | back to the seeded demo database |
| GET | `/api/sessions/{id}/schema` | schema of the session's active connection |
| POST | `/api/upload` | upload a SQLite file → new connection (50 MB) |
| POST | `/api/upload-file` | ingest CSV/XLSX/XLS/PDF/DOCX/JSON → queryable table (25 MB) |
| GET | `/api/queries` | recent executed SQL (query log) |
| POST | `/api/queries/{id}/favorite` | toggle favorite |
| POST | `/api/dashboard/pin` | pin an artifact `{session_id, kind, title, payload}` |
| GET | `/api/dashboard/{session_id}` | read a dashboard |
| DELETE | `/api/dashboard/item/{item_id}` | remove a pinned item |
| POST | `/api/share` | create a share link `{session_id, item_id?}` |
| GET | `/api/shared/{share_id}` | read a shared artifact |

Full interactive docs at `/docs`.

### PostgreSQL

```bash
curl -s -X POST http://localhost:8000/api/connections/postgres \
  -H "Content-Type: application/json" \
  -d '{"name":"Prod replica","url":"postgresql://user:pass@host:5432/db"}'
```

The URL is normalized and the connection is **proved reachable before it is
saved**, so a typo fails at registration rather than mid-demo. The guard, row
caps and read-only posture apply identically, and SQL is generated in the
connection's dialect. If the optional Postgres extras are not installed the
endpoint returns `501` with an install message instead of a traceback.
