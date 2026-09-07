import { useMemo, useState } from "react";
import { MessageSquare, Plus, Search, Trash2 } from "lucide-react";
import { useApp } from "@/lib/app-state";
import { relativeTime } from "@/lib/api";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { sessions, sessionsLoading, activeSessionId, newChat, openSession, deleteSession } =
    useApp();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => (s.title || "Untitled").toLowerCase().includes(q));
  }, [sessions, query]);

  return (
    <aside className="flex h-full w-[280px] shrink-0 flex-col border-r border-border bg-surface">
      <div className="space-y-3 p-3">
        <button
          onClick={() => {
            newChat();
            onNavigate?.();
          }}
          className="group flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Plus size={16} className="transition-transform group-hover:rotate-90 duration-200" />
          New chat
        </button>

        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats…"
            className="w-full rounded-lg border border-border/80 bg-background/50 py-2 pl-8 pr-3 text-xs outline-none placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/30"
          />
        </div>
      </div>

      <div className="scroll-thin flex-1 px-2 pb-2">
        {sessionsLoading ? (
          <div className="space-y-2 px-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-12 animate-pulse rounded-md bg-secondary"
                style={{ animationDelay: `${i * 80}ms` }}
              />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-muted-foreground">
            {query ? "No chats match your search." : "No conversations yet. Start a new chat."}
          </p>
        ) : (
          <ul className="space-y-1">
            {filtered.map((s) => {
              const active = s.id === activeSessionId;
              return (
                <li key={s.id}>
                  <div
                    className={`group flex items-center gap-2 rounded-xl px-2 py-2 transition-all duration-150 ${
                      active ? "bg-primary/12 ring-1 ring-primary/25" : "hover:bg-accent/60"
                    }`}
                  >
                    <button
                      onClick={() => {
                        openSession(s.id);
                        onNavigate?.();
                      }}
                      className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
                    >
                      <span
                        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
                          active
                            ? "bg-primary text-primary-foreground"
                            : "bg-secondary text-muted-foreground"
                        }`}
                      >
                        <MessageSquare size={13} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-medium leading-tight">
                          {s.title || "Untitled"}
                        </div>
                        <div className="mt-0.5 text-[11px] text-muted-foreground">
                          {relativeTime(s.updated_at ?? s.created_at)}
                        </div>
                      </span>
                    </button>
                    {confirming === s.id ? (
                      <button
                        onClick={() => {
                          deleteSession(s.id);
                          setConfirming(null);
                        }}
                        className="shrink-0 rounded-md bg-destructive px-2 py-1 text-[11px] font-semibold text-destructive-foreground"
                      >
                        Delete
                      </button>
                    ) : (
                      <button
                        onClick={() => {
                          setConfirming(s.id);
                          setTimeout(() => setConfirming((c) => (c === s.id ? null : c)), 3000);
                        }}
                        aria-label="Delete session"
                        className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-0 transition-all hover:bg-destructive/15 hover:text-destructive group-hover:opacity-100"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="border-t border-border/60 px-3 py-3">
        <div className="rounded-lg bg-secondary/50 px-3 py-2 text-[11px] text-muted-foreground">
          <div className="font-medium text-foreground/80">DataPilot AI</div>
          <div className="mt-0.5">Natural language → SQL, charts & diagrams</div>
        </div>
      </div>
    </aside>
  );
}
