import { useCallback, useEffect, useRef, useState } from "react";
import { Star, Play, Terminal, RefreshCw, Copy, Check, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { IconButton } from "./artifacts";
import { useApp } from "@/lib/app-state";
import { api, relativeTime, type QueryHistoryItem } from "@/lib/api";

/* Only poll while the tab is actually visible. The old five-second interval
   ran for the life of the page — in a background tab, on a closed panel,
   forever — which is a request every five seconds for a list nobody is
   reading. */
const POLL_MS = 8000;

export function QueryHistory() {
  const [queries, setQueries] = useState<QueryHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const { send, isStreaming } = useApp();
  const mounted = useRef(true);

  const fetchQueries = useCallback(async () => {
    try {
      const rows = await api.listQueries();
      if (!mounted.current) return;
      setQueries(Array.isArray(rows) ? rows : []);
      setError(null);
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    fetchQueries();

    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer === null) timer = setInterval(fetchQueries, POLL_MS);
    };
    const stop = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => (document.hidden ? stop() : (fetchQueries(), start()));

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      mounted.current = false;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [fetchQueries]);

  const toggleFavorite = async (id: string) => {
    // Optimistic: the star should respond to the click, not to the round trip.
    const previous = queries;
    setQueries((prev) =>
      prev.map((q) => (q.id === id ? { ...q, is_favorite: !q.is_favorite } : q)),
    );
    try {
      const { is_favorite } = await api.toggleQueryFavorite(id);
      setQueries((prev) => prev.map((q) => (q.id === id ? { ...q, is_favorite } : q)));
    } catch {
      setQueries(previous);
      toast.error("Couldn't update that query.");
    }
  };

  const copy = async (item: QueryHistoryItem) => {
    try {
      await navigator.clipboard.writeText(item.sql);
      setCopiedId(item.id);
      setTimeout(() => setCopiedId((c) => (c === item.id ? null : c)), 1500);
    } catch {
      toast.error("Clipboard unavailable.");
    }
  };

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-20 animate-pulse rounded-lg bg-secondary"
            style={{ animationDelay: `${i * 80}ms` }}
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel space-y-2 px-4 py-6 text-center">
        <p className="text-xs text-destructive">Couldn't load the query log.</p>
        <IconButton onClick={fetchQueries}>
          <RefreshCw size={12} /> Retry
        </IconButton>
      </div>
    );
  }

  if (queries.length === 0) {
    return (
      <div className="panel flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
        <Terminal size={22} className="text-muted-foreground opacity-30" />
        <p className="text-xs text-muted-foreground">No queries run yet.</p>
        <p className="max-w-[14rem] text-[11px] text-muted-foreground/70">
          Every SQL statement the agent runs is logged here. Star the ones worth keeping.
        </p>
      </div>
    );
  }

  /* Favourites first, then most recent. The previous comparator returned 0 for
     equal favourite flags, leaving the server's ordering to break the tie. */
  const sorted = [...queries].sort((a, b) => {
    if (a.is_favorite !== b.is_favorite) return a.is_favorite ? -1 : 1;
    return (b.created_at ?? "").localeCompare(a.created_at ?? "");
  });
  const starred = sorted.filter((q) => q.is_favorite).length;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 px-0.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Query log
        </span>
        <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {queries.length}
          {starred > 0 && ` · ${starred} ★`}
        </span>
        <button
          onClick={fetchQueries}
          aria-label="Refresh query log"
          className="ml-auto rounded p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <RefreshCw size={12} />
        </button>
      </div>

      {sorted.map((q) => (
        <div
          key={q.id}
          className={`group rounded-lg border bg-surface p-2.5 transition-colors ${
            q.is_favorite
              ? "border-warning/40 hover:border-warning/60"
              : "border-border hover:border-primary/30"
          }`}
        >
          <pre className="scroll-thin max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-info">
            {q.sql}
          </pre>
          <div className="mt-2 flex items-center gap-1">
            <span className="text-[10px] text-muted-foreground">{relativeTime(q.created_at)}</span>
            <div className="ml-auto flex items-center gap-1">
              <button
                onClick={() => toggleFavorite(q.id)}
                title={q.is_favorite ? "Remove star" : "Star this query"}
                aria-pressed={q.is_favorite}
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-warning"
              >
                <Star size={12} className={q.is_favorite ? "fill-warning text-warning" : ""} />
              </button>
              <button
                onClick={() => copy(q)}
                title="Copy SQL"
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                {copiedId === q.id ? <Check size={12} /> : <Copy size={12} />}
              </button>
              <button
                onClick={() => send(`Run this query and explain the result:\n\n${q.sql}`)}
                disabled={isStreaming}
                title={isStreaming ? "Wait for the current answer" : "Run this query again"}
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-40"
              >
                {isStreaming ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
