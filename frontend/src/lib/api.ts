/* Thin fetch wrappers around the DataPilot AI backend + SSE parser. */

export const API_BASE = "/api";
const HEALTH_URL = "/health";

export type ChartSpec = {
  type: "bar" | "line" | "pie" | "scatter" | "area" | "kpi";
  columns: string[];
  x_key: string;
  y_key: string;
  rows: (string | number | null)[][];
  recommended?: boolean;
  title?: string;
};

export type DiagramSpec = { type: string; mermaid: string };

export type QueryResult = {
  sql?: string;
  columns: string[];
  rows: (string | number | null)[][];
  row_count?: number;
  truncated?: boolean;
  execution_time_ms?: number;
};

export type SchemaColumn = { name: string; type: string; nullable?: boolean; pk?: boolean };
export type SchemaTable = {
  name: string;
  columns: SchemaColumn[];
  primary_keys?: string[];
  foreign_keys?: { column: string; references_table: string; references_column: string }[];
};
export type Schema = { tables: SchemaTable[] };

export type SessionRow = { id: string; title: string; created_at?: string; updated_at?: string };

export type DashboardItem = {
  id: string;
  session_id: string;
  kind: "chart" | "diagram" | "insight" | string;
  title: string;
  payload: Record<string, unknown>;
  created_at?: string;
};

export type Artifact =
  | { kind: "sql"; sql: string }
  | { kind: "table"; table: QueryResult }
  | { kind: "chart"; chart: ChartSpec }
  | { kind: "diagram"; diagram: DiagramSpec };

export type ThreadMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  artifacts: Artifact[];
  done?: boolean;
  error?: string;
};

async function json<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const err = new Error(
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object"
          ? `${(detail as { type?: string }).type ?? "Error"}: ${(detail as { message?: string }).message ?? ""}`
          : `Request failed (${res.status})`,
    ) as Error & { detail?: unknown; status?: number };
    err.detail = detail;
    err.status = res.status;
    throw err;
  }
  return body as T;
}

export const api = {
  health: () => json<{ status: string }>(HEALTH_URL),
  schema: () => json<Schema>(`${API_BASE}/schema`),
  query: (sql: string) =>
    json<QueryResult>(`${API_BASE}/query`, { method: "POST", body: JSON.stringify({ sql }) }),
  listSessions: () => json<SessionRow[]>(`${API_BASE}/sessions`),
  createSession: (title = "New chat") =>
    json<{ session_id: string; title: string }>(`${API_BASE}/sessions`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  getSession: (id: string) =>
    json<{
      session: SessionRow;
      messages: {
        id: string;
        role: "user" | "assistant";
        content: string;
        payload?: {
          sql?: string;
          table?: QueryResult;
          chart?: ChartSpec;
          diagram?: DiagramSpec;
          mode?: string;
        };
      }[];
    }>(`${API_BASE}/sessions/${id}`),
  renameSession: (id: string, title: string) =>
    json<{ ok: boolean }>(`${API_BASE}/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteSession: (id: string) =>
    json<{ ok: boolean }>(`${API_BASE}/sessions/${id}`, { method: "DELETE" }),
  pin: (body: {
    session_id: string;
    kind: string;
    title: string;
    payload: Record<string, unknown>;
  }) =>
    json<{ item_id: string }>(`${API_BASE}/dashboard/pin`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  dashboard: (sessionId: string) =>
    json<{ items: DashboardItem[] }>(`${API_BASE}/dashboard/${sessionId}`),
  removeItem: (itemId: string) =>
    json<{ ok: boolean }>(`${API_BASE}/dashboard/item/${itemId}`, { method: "DELETE" }),
  share: (sessionId: string, itemId?: string) =>
    json<{ share_id: string; url?: string }>(`${API_BASE}/share`, {
      method: "POST",
      body: JSON.stringify(itemId ? { session_id: sessionId, item_id: itemId } : { session_id: sessionId }),
    }),
  shared: (shareId: string) =>
    json<{ kind: string; title: string; payload: Record<string, unknown> }>(
      `${API_BASE}/shared/${shareId}`,
    ),
  uploadDatabase: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new Error(String(body?.detail ?? "Upload failed"));
    return body as { ok: boolean; database?: string; tables?: string[] };
  },
  uploadDataFile: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/upload-file`, { method: "POST", body: fd });
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new Error(String(body?.detail ?? "Import failed"));
    return body as { ok: boolean; info?: string };
  },
};

/* ---------- SSE ---------- */

export type SseEvent = {
  type: string;
  answer?: string;
  text?: string;
  label?: string;
  name?: string;
  sql?: string;
  columns?: string[];
  rows?: (string | number | null)[][];
  truncated?: boolean;
  chart?: ChartSpec;
  diagram?: DiagramSpec;
  mode?: string;
  message?: string;
};

export async function streamChat(
  message: string,
  sessionId: string | null,
  handlers: { onEvent: (e: SseEvent) => void; signal?: AbortSignal },
) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal: handlers.signal ?? null,
  });
  if (!res.ok || !res.body) throw new Error(`Chat failed (${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of block.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const raw = trimmed.slice(5).trim();
        if (!raw || raw === "[DONE]") continue;
        try {
          handlers.onEvent(JSON.parse(raw) as SseEvent);
        } catch {
          /* ignore malformed block */
        }
      }
    }
  }
}

export function relativeTime(iso?: string) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(t).toLocaleDateString();
}
