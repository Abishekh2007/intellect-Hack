import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";
import {
  api,
  streamChat,
  type Artifact,
  type ChartSpec,
  type DiagramSpec,
  type SessionRow,
  type ThreadMessage,
} from "@/lib/api";

const ACTIVE_KEY = "datapilot-active-session";

type AppState = {
  sessions: SessionRow[];
  sessionsLoading: boolean;
  activeSessionId: string | null;
  thread: ThreadMessage[];
  isStreaming: boolean;
  statusLabel: string | null;
  toolChip: string | null;
  mode: string;
  backendOnline: boolean | null;
  refreshSessions: () => Promise<void>;
  newChat: () => Promise<void>;
  openSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameActive: (title: string) => Promise<void>;
  send: (message: string) => Promise<void>;
  /* Aborts the in-flight turn. The AbortController already existed but was
     reachable only from `send` and `newChat`, so a long answer could not be
     interrupted — the composer just stayed disabled until it finished. */
  stop: () => void;
  pin: (
    kind: "chart" | "diagram",
    title: string,
    payload: Record<string, unknown>,
  ) => Promise<void>;
  dashboardVersion: number;
  /* Bumped when the session switches database, so schema views refetch. */
  connectionVersion: number;
  onConnectionChange: () => void;
};

const Ctx = createContext<AppState | null>(null);

let uid = 0;
const nextId = () => `m${Date.now()}-${uid++}`;

export function AppProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [thread, setThread] = useState<ThreadMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [toolChip, setToolChip] = useState<string | null>(null);
  const [mode, setMode] = useState("Checking…");
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [dashboardVersion, setDashboardVersion] = useState(0);
  const [connectionVersion, setConnectionVersion] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const titledRef = useRef<Set<string>>(new Set());

  /* health polling — also the source of truth for which engine is answering,
     so the badge is correct before the first message rather than after it. */
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setBackendOnline(true);
        setMode(h.llm_provider === "configured" ? "AI agent" : "Offline engine");
      } catch {
        if (!cancelled) {
          setBackendOnline(false);
          setMode("Offline");
        }
      }
    };
    check();
    const t = setInterval(check, 30000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await api.listSessions();
      setSessions(Array.isArray(list) ? list : []);
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  const openSession = useCallback(async (id: string) => {
    setActiveSessionId(id);
    window.localStorage.setItem(ACTIVE_KEY, id);
    try {
      const data = await api.getSession(id);
      setThread(
        (data.messages ?? []).map((m) => {
          const artifacts: Artifact[] = [];
          const p = m.payload ?? {};
          if (p.sql) artifacts.push({ kind: "sql", sql: p.sql });
          if (p.table) artifacts.push({ kind: "table", table: p.table });
          if (p.chart) artifacts.push({ kind: "chart", chart: p.chart });
          if (p.diagram) artifacts.push({ kind: "diagram", diagram: p.diagram });
          return {
            id: m.id ?? nextId(),
            role: m.role,
            content: m.content ?? "",
            artifacts,
            done: true,
          };
        }),
      );
    } catch {
      setThread([]);
    }
  }, []);

  /* restore on load */
  useEffect(() => {
    refreshSessions();
    const saved = window.localStorage.getItem(ACTIVE_KEY);
    if (saved) openSession(saved);
  }, [refreshSessions, openSession]);

  /* Clears the view but does not create anything yet — the session is created
     with the first message. Creating it up front left an "New chat" row in the
     sidebar for every click, including the ones the user never used. */
  const newChat = useCallback(async () => {
    abortRef.current?.abort();
    setThread([]);
    setIsStreaming(false);
    setActiveSessionId(null);
    window.localStorage.removeItem(ACTIVE_KEY);
  }, []);

  const deleteSession = useCallback(
    async (id: string) => {
      try {
        await api.deleteSession(id);
      } catch {
        /* still drop it locally */
      }
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === activeSessionId) {
        window.localStorage.removeItem(ACTIVE_KEY);
        setActiveSessionId(null);
        setThread([]);
        await newChat();
      }
    },
    [activeSessionId, newChat],
  );

  const renameActive = useCallback(
    async (title: string) => {
      if (!activeSessionId || !title.trim()) return;
      setSessions((prev) =>
        prev.map((s) => (s.id === activeSessionId ? { ...s, title: title.trim() } : s)),
      );
      try {
        await api.renameSession(activeSessionId, title.trim());
        await refreshSessions();
      } catch {
        toast.error("Rename failed");
      }
    },
    [activeSessionId, refreshSessions],
  );

  const send = useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text) return;

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      let sessionId = activeSessionId;
      if (!sessionId) {
        try {
          // Title it from the question straight away, so the sidebar never
          // shows a row called "New chat".
          const s = await api.createSession(text.slice(0, 40));
          sessionId = s.session_id;
          setActiveSessionId(sessionId);
          window.localStorage.setItem(ACTIVE_KEY, sessionId);
          titledRef.current.add(sessionId);
        } catch {
          sessionId = null;
        }
      }

      let isFirst = false;
      const assistantId = nextId();
      setThread((prev) => {
        // Read the thread inside the updater rather than from the closure, so
        // `send` no longer has to be rebuilt on every single message.
        isFirst = prev.length === 0;
        return [
          ...prev,
          { id: nextId(), role: "user", content: text, artifacts: [], done: true },
          { id: assistantId, role: "assistant", content: "", artifacts: [] },
        ];
      });
      setIsStreaming(true);
      setStatusLabel("working");

      const patch = (fn: (m: ThreadMessage) => ThreadMessage) =>
        setThread((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));

      try {
        await streamChat(text, sessionId, {
          signal: controller.signal,
          onEvent: (e) => {
            switch (e.type) {
              case "status":
              case "status_step":
                setStatusLabel(e.step ?? e.label ?? "thinking");
                break;
              case "token":
                patch((m) => ({ ...m, content: m.content + (e.text ?? "") }));
                break;
              case "tool_call":
                setToolChip(e.name ?? "tool");
                setTimeout(() => setToolChip(null), 2500);
                break;
              case "sql":
                if (e.sql)
                  patch((m) => ({
                    ...m,
                    artifacts: [...m.artifacts, { kind: "sql", sql: e.sql! }],
                  }));
                break;
              case "table":
                patch((m) => ({
                  ...m,
                  artifacts: [
                    ...m.artifacts,
                    {
                      kind: "table",
                      table: {
                        columns: e.columns ?? [],
                        rows: e.rows ?? [],
                        ...(e.truncated === undefined ? {} : { truncated: e.truncated }),
                      },
                    },
                  ],
                }));
                break;
              case "chart":
                if (e.chart)
                  patch((m) => ({
                    ...m,
                    artifacts: [...m.artifacts, { kind: "chart", chart: e.chart as ChartSpec }],
                  }));
                break;
              case "diagram":
                if (e.diagram)
                  patch((m) => ({
                    ...m,
                    artifacts: [
                      ...m.artifacts,
                      { kind: "diagram", diagram: e.diagram as DiagramSpec },
                    ],
                  }));
                break;
              case "error":
                patch((m) => ({
                  ...m,
                  error: e.message ?? "Something went wrong — try again.",
                  done: true,
                }));
                break;
              case "final":
                /* Functional update: reading `mode` from the closure forced it
                   into this callback's dependency list, which rebuilt `send`
                   on every badge change and invalidated the chip handlers. */
                setMode((prev) =>
                  e.mode === "offline"
                    ? "Offline engine"
                    : e.mode === "agent"
                      ? "AI agent"
                      : e.mode === "rule"
                        ? "Rule"
                        : prev,
                );
                // The final event repeats every artifact the turn produced so
                // the server can persist them. Agent mode has already streamed
                // them in, so merge rather than append.
                patch((m) => {
                  const artifacts = [...m.artifacts];
                  if (e.sql && !artifacts.some((a) => a.kind === "sql" && a.sql === e.sql))
                    artifacts.push({ kind: "sql", sql: e.sql });
                  if (e.table && !artifacts.some((a) => a.kind === "table"))
                    artifacts.push({ kind: "table", table: e.table });
                  if (e.chart && !artifacts.some((a) => a.kind === "chart"))
                    artifacts.push({ kind: "chart", chart: e.chart as ChartSpec });
                  if (e.diagram && !artifacts.some((a) => a.kind === "diagram"))
                    artifacts.push({ kind: "diagram", diagram: e.diagram as DiagramSpec });
                  return {
                    ...m,
                    content: m.content || e.answer || e.text || "",
                    artifacts,
                    done: true,
                  };
                });
                break;
              default:
                break;
            }
          },
        });
        patch((m) => ({ ...m, done: true }));
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          patch((m) => ({
            ...m,
            done: true,
            error: "Can't reach the backend — is it running on port 8000?",
          }));
        }
      } finally {
        setIsStreaming(false);
        setStatusLabel(null);
        if (sessionId && isFirst && !titledRef.current.has(sessionId)) {
          titledRef.current.add(sessionId);
          api
            .renameSession(sessionId, text.slice(0, 40))
            .then(refreshSessions)
            .catch(() => {});
        } else {
          refreshSessions();
        }
      }
    },
    [activeSessionId, refreshSessions],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setStatusLabel(null);
    setToolChip(null);
    // Keep whatever streamed in and mark the turn closed, so the partial
    // answer stays on screen instead of hanging with a spinner forever.
    setThread((prev) =>
      prev.map((m, i) =>
        i === prev.length - 1 && m.role === "assistant" && !m.done
          ? { ...m, done: true, content: m.content || "_Stopped._" }
          : m,
      ),
    );
  }, []);

  const pin = useCallback(
    async (kind: "chart" | "diagram", title: string, payload: Record<string, unknown>) => {
      if (!activeSessionId) {
        toast.error("Start a chat before pinning.");
        return;
      }
      try {
        await api.pin({ session_id: activeSessionId, kind, title, payload });
        setDashboardVersion((v) => v + 1);
        toast.success("Pinned to dashboard ✓");
      } catch {
        toast.error("Couldn't pin this item.");
      }
    },
    [activeSessionId],
  );

  const onConnectionChange = useCallback(() => setConnectionVersion((v) => v + 1), []);

  useEffect(() => () => abortRef.current?.abort(), []);

  return (
    <Ctx.Provider
      value={{
        sessions,
        sessionsLoading,
        activeSessionId,
        thread,
        isStreaming,
        statusLabel,
        toolChip,
        mode,
        backendOnline,
        refreshSessions,
        newChat,
        openSession,
        deleteSession,
        renameActive,
        send,
        stop,
        pin,
        dashboardVersion,
        connectionVersion,
        onConnectionChange,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useApp() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
