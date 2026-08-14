import { useEffect, useState } from "react";
import { Star, Play, Terminal } from "lucide-react";
import { IconButton } from "./artifacts";
import { useApp } from "@/lib/app-state";
import { api } from "@/lib/api";

interface QueryItem {
  id: string;
  sql: string;
  is_favorite: boolean;
  created_at: string;
}

export function QueryHistory() {
  const [queries, setQueries] = useState<QueryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const { send } = useApp();

  const fetchQueries = async () => {
    try {
      const res = await fetch(`${api.baseUrl}/queries`);
      if (res.ok) {
        const data = await res.json();
        setQueries(data);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueries();
    
    // Simple polling to keep it updated when new queries are run
    const interval = setInterval(fetchQueries, 5000);
    return () => clearInterval(interval);
  }, []);

  const toggleFavorite = async (id: string) => {
    try {
      const res = await fetch(`${api.baseUrl}/queries/${id}/favorite`, { method: "POST" });
      if (res.ok) {
        const { is_favorite } = await res.json();
        setQueries((prev) =>
          prev.map((q) => (q.id === id ? { ...q, is_favorite } : q))
        );
      }
    } catch (e) {
      console.error(e);
    }
  };

  if (loading) {
    return <div className="p-4 text-center text-xs text-muted-foreground">Loading history...</div>;
  }

  if (queries.length === 0) {
    return (
      <div className="flex h-[200px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <Terminal size={24} className="opacity-20" />
        <p className="text-xs">No queries run yet.</p>
      </div>
    );
  }

  // Sort favorites to the top
  const sorted = [...queries].sort((a, b) => {
    if (a.is_favorite === b.is_favorite) return 0;
    return a.is_favorite ? -1 : 1;
  });

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Query Log
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto p-2 space-y-2">
        {sorted.map((q) => (
          <div
            key={q.id}
            className="group relative flex flex-col gap-2 rounded-lg border border-border bg-surface p-3 transition-colors hover:bg-accent/30"
          >
            <div className="flex items-start justify-between">
              <pre className="scroll-thin max-h-32 overflow-x-auto text-[11px] leading-relaxed text-info font-mono whitespace-pre-wrap flex-1 mr-2">
                {q.sql}
              </pre>
              <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                <IconButton
                  title="Run again"
                  onClick={() => send(`Run this query again:\n\n${q.sql}`)}
                >
                  <Play size={12} />
                </IconButton>
                <IconButton
                  title={q.is_favorite ? "Unstar" : "Star"}
                  onClick={() => toggleFavorite(q.id)}
                >
                  <Star size={12} className={q.is_favorite ? "fill-warning text-warning" : ""} />
                </IconButton>
              </div>
            </div>
            
            {/* Show star persistently if it is a favorite */}
            {q.is_favorite && (
               <div className="absolute top-2 right-2 group-hover:hidden">
                 <Star size={12} className="fill-warning text-warning" />
               </div>
            )}
            
            <div className="text-[10px] text-muted-foreground">
              {new Date(q.created_at).toLocaleString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
