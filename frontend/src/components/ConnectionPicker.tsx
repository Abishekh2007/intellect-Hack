import { useCallback, useEffect, useRef, useState } from "react";
import { Database, Loader2, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, type DbConnection } from "@/lib/api";
import { useApp } from "@/lib/app-state";

const KIND_LABEL: Record<string, string> = {
  sqlite: "SQLite",
  postgres: "PostgreSQL",
};

/** Picks which database this chat queries. Defaults to the bundled demo, and
 *  can always be reset back to it mid-demo. */
export function ConnectionPicker() {
  const { activeSessionId, onConnectionChange } = useApp();
  const [open, setOpen] = useState(false);
  const [connections, setConnections] = useState<DbConnection[]>([]);
  const [activeId, setActiveId] = useState<string>("demo");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const popoverRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.connections(activeSessionId);
      setConnections(data.connections);
      setActiveId(data.active_id);
    } catch {
      /* the offline banner already covers an unreachable backend */
    }
  }, [activeSessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!popoverRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const active = connections.find((c) => c.id === activeId);

  const select = async (id: string) => {
    if (!activeSessionId) {
      toast.error("Start a chat first — the database is chosen per conversation.");
      return;
    }
    setBusy(true);
    try {
      const { connection } = await api.useConnection(activeSessionId, id);
      setActiveId(connection.id);
      onConnectionChange();
      toast.success(`Now querying ${connection.name}`);
      setOpen(false);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!activeSessionId) return;
    setBusy(true);
    try {
      const { connection } = await api.resetConnection(activeSessionId);
      setActiveId(connection.id);
      onConnectionChange();
      toast.success("Back to the demo database");
    } finally {
      setBusy(false);
    }
  };

  const addPostgres = async () => {
    if (!url.trim()) return;
    setBusy(true);
    try {
      const { connection, table_count } = await api.addPostgres(
        name.trim() || "PostgreSQL",
        url.trim(),
      );
      toast.success(`Connected — ${table_count ?? 0} tables found`);
      setName("");
      setUrl("");
      setAdding(false);
      await refresh();
      await select(connection.id);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    setBusy(true);
    try {
      await api.removeConnection(id);
      await refresh();
      onConnectionChange();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative" ref={popoverRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Choose which database this chat queries"
        className="inline-flex max-w-[190px] items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Database size={11} className="shrink-0 text-primary" />
        <span className="truncate">{active?.name ?? "Database"}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-lg border border-border bg-popover shadow-[var(--shadow-card)]">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              Database
            </span>
            <button
              onClick={() => setOpen(false)}
              className="rounded p-1 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X size={13} />
            </button>
          </div>

          <ul className="max-h-64 overflow-auto py-1">
            {connections.map((c) => (
              <li key={c.id}>
                <div
                  className={`group flex items-center gap-2 px-3 py-2 text-sm ${
                    c.id === activeId ? "bg-primary/10" : "hover:bg-accent/60"
                  }`}
                >
                  <button
                    onClick={() => select(c.id)}
                    disabled={busy}
                    className="flex min-w-0 flex-1 flex-col items-start text-left disabled:opacity-50"
                  >
                    <span className="flex w-full items-center gap-1.5">
                      <span className="truncate font-medium">{c.name}</span>
                      {c.id === activeId && (
                        <span className="shrink-0 rounded-full bg-primary/20 px-1.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
                          Active
                        </span>
                      )}
                    </span>
                    <span className="truncate text-[11px] text-muted-foreground">
                      {KIND_LABEL[c.kind] ?? c.kind} · {c.location}
                    </span>
                  </button>
                  {!c.is_demo && (
                    <button
                      onClick={() => remove(c.id)}
                      disabled={busy}
                      title="Remove connection"
                      className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>

          <div className="border-t border-border p-2">
            {adding ? (
              <div className="space-y-2">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Name (optional)"
                  className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs outline-none focus:ring-2 focus:ring-ring"
                />
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addPostgres()}
                  placeholder="postgresql://user:password@host:5432/database"
                  className="w-full rounded-md border border-input bg-background px-2 py-1.5 font-mono text-[11px] outline-none focus:ring-2 focus:ring-ring"
                />
                <div className="flex gap-2">
                  <button
                    onClick={addPostgres}
                    disabled={busy || !url.trim()}
                    className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary px-2 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
                  >
                    {busy ? <Loader2 size={12} className="animate-spin" /> : null}
                    Connect
                  </button>
                  <button
                    onClick={() => setAdding(false)}
                    className="rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={() => setAdding(true)}
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                >
                  <Plus size={12} /> Add PostgreSQL
                </button>
                <button
                  onClick={reset}
                  disabled={busy || activeId === "demo"}
                  title="Return this chat to the demo database"
                  className="inline-flex items-center justify-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
                >
                  <RotateCcw size={12} /> Demo
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
