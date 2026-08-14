import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useApp } from "@/lib/app-state";
import { API_BASE, relativeTime } from "@/lib/api";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { sessions, sessionsLoading, activeSessionId, newChat, openSession, deleteSession } = useApp();
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <aside className="flex h-full w-[280px] shrink-0 flex-col border-r border-border bg-surface/50">
      <div className="p-3">
        <button
          onClick={() => {
            newChat();
            onNavigate?.();
          }}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-opacity duration-150 hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Plus size={16} /> New chat
        </button>
      </div>

      <div className="scroll-thin flex-1 px-2 pb-2">
        {sessionsLoading ? (
          <div className="space-y-2 px-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-11 animate-pulse rounded-lg bg-secondary" />
            ))}
          </div>
        ) : sessions.length === 0 ? (
          <p className="px-2 py-4 text-xs text-muted-foreground">
            No conversations yet. Start a new chat.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((s) => (
              <li key={s.id}>
                <div
                  className={`group flex items-center gap-2 rounded-lg px-2.5 py-2 transition-colors duration-150 ${
                    s.id === activeSessionId ? "bg-accent" : "hover:bg-secondary"
                  }`}
                >
                  <button
                    onClick={() => {
                      openSession(s.id);
                      onNavigate?.();
                    }}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="truncate text-[13px] font-medium">{s.title || "Untitled"}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {relativeTime(s.updated_at ?? s.created_at)}
                    </div>
                  </button>
                  {confirming === s.id ? (
                    <button
                      onClick={() => {
                        deleteSession(s.id);
                        setConfirming(null);
                      }}
                      className="rounded-md bg-destructive px-2 py-1 text-[11px] font-semibold text-destructive-foreground"
                    >
                      Sure?
                    </button>
                  ) : (
                    <button
                      onClick={() => {
                        setConfirming(s.id);
                        setTimeout(() => setConfirming((c) => (c === s.id ? null : c)), 3000);
                      }}
                      aria-label="Delete session"
                      className="rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity duration-150 hover:text-destructive group-hover:opacity-100"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-border px-3 py-2.5 text-[11px] text-muted-foreground">
        <div className="font-mono">API: {API_BASE}</div>
        <div>Powered by DataPilot</div>
      </div>
    </aside>
  );
}
