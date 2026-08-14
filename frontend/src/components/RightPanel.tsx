import { useCallback, useEffect, useRef, useState } from "react";
import { Database, LayoutDashboard, Loader2, RefreshCw, Share2, Table2, X } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type ChartSpec,
  type DashboardItem,
  type QueryResult,
  type Schema,
} from "@/lib/api";
import { ChartView, DiagramView, IconButton, MarkdownText, TableCard } from "@/components/artifacts";
import { useApp } from "@/lib/app-state";

type Tab = "schema" | "database" | "dashboard";

export function RightPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("schema");
  const [schema, setSchema] = useState<Schema | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const { activeSessionId, send } = useApp();

  const loadSchema = useCallback(async () => {
    setSchemaLoading(true);
    try {
      setSchema(await api.schema());
    } catch {
      setSchema({ tables: [] });
    } finally {
      setSchemaLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSchema();
  }, [loadSchema]);

  return (
    <aside className="flex h-full w-full flex-col border-l border-border bg-surface/50 lg:w-[360px] lg:shrink-0">
      <div className="flex items-center gap-1 border-b border-border px-2 py-2">
        {(
          [
            ["schema", "Schema", <Table2 key="a" size={13} />],
            ["database", "Database", <Database key="b" size={13} />],
            ["dashboard", "Dashboard", <LayoutDashboard key="c" size={13} />],
          ] as [Tab, string, React.ReactNode][]
        ).map(([id, label, icon]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors duration-150 ${
              tab === id ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-secondary"
            }`}
          >
            {icon}
            {label}
          </button>
        ))}
        <button
          onClick={onClose}
          aria-label="Close panel"
          className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary"
        >
          <X size={14} />
        </button>
      </div>

      <div className="scroll-thin flex-1 space-y-3 p-3">
        {tab === "schema" && (
          <SchemaTab
            schema={schema}
            loading={schemaLoading}
            onRefresh={loadSchema}
            onEr={() => send("show me the ER diagram")}
          />
        )}
        {tab === "database" && <DatabaseTab onSchemaChanged={loadSchema} />}
        {tab === "dashboard" && <DashboardTab sessionId={activeSessionId} />}
      </div>
    </aside>
  );
}

function SchemaTab({
  schema,
  loading,
  onRefresh,
  onEr,
}: {
  schema: Schema | null;
  loading: boolean;
  onRefresh: () => void;
  onEr: () => void;
}) {
  if (loading)
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-secondary" />
        ))}
      </div>
    );

  const tables = schema?.tables ?? [];

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <IconButton onClick={onEr} tone="accent">
          ER diagram
        </IconButton>
        <IconButton onClick={onRefresh}>
          <RefreshCw size={12} /> Refresh
        </IconButton>
      </div>
      {tables.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No schema available. Upload a database from the Database tab.
        </p>
      ) : (
        tables.map((t) => (
          <div key={t.name} className="panel p-3">
            <div className="font-mono text-[13px] font-bold">{t.name}</div>
            <div className="mt-2 space-y-1">
              {t.columns.map((c) => (
                <div key={c.name} className="flex items-center gap-2 text-[12px]">
                  <span className="font-mono">{c.name}</span>
                  <span className="text-muted-foreground">{c.type}</span>
                  {c.pk && (
                    <span className="rounded bg-primary/20 px-1.5 text-[10px] font-semibold text-primary">
                      PK
                    </span>
                  )}
                </div>
              ))}
            </div>
            {(t.foreign_keys ?? []).length > 0 && (
              <div className="mt-2 space-y-0.5 border-t border-border pt-2">
                {t.foreign_keys!.map((fk) => (
                  <div key={fk.column} className="font-mono text-[11px] text-muted-foreground">
                    {t.name}.{fk.column} → {fk.references_table}.{fk.references_column}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

function DatabaseTab({ onSchemaChanged }: { onSchemaChanged: () => void }) {
  const dbRef = useRef<HTMLInputElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [dbNote, setDbNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [fileNote, setFileNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [sql, setSql] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const uploadDb = async () => {
    const f = dbRef.current?.files?.[0];
    if (!f) return;
    try {
      const r = await api.uploadDatabase(f);
      setDbNote({ ok: true, text: `Database active — ${r.tables?.length ?? 0} tables` });
      onSchemaChanged();
    } catch (e) {
      setDbNote({ ok: false, text: (e as Error).message });
    }
  };

  const importFile = async () => {
    const f = fileRef.current?.files?.[0];
    if (!f) return;
    try {
      const r = await api.uploadDataFile(f);
      setFileNote({ ok: true, text: r.info ?? "Imported" });
      onSchemaChanged();
    } catch (e) {
      setFileNote({ ok: false, text: (e as Error).message });
    }
  };

  const run = async () => {
    if (!sql.trim()) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await api.query(sql));
    } catch (e) {
      setResult(null);
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <Section title="Upload database">
        <input
          ref={dbRef}
          type="file"
          accept=".db,.sqlite,.sqlite3"
          className="w-full text-[11px] text-muted-foreground file:mr-2 file:rounded-md file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-[11px] file:text-secondary-foreground"
        />
        <IconButton onClick={uploadDb} tone="accent">
          Upload
        </IconButton>
        {dbNote && <Note ok={dbNote.ok}>{dbNote.text}</Note>}
      </Section>

      <Section title="Import data file">
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.xlsx,.pdf,.docx,.json"
          className="w-full text-[11px] text-muted-foreground file:mr-2 file:rounded-md file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-[11px] file:text-secondary-foreground"
        />
        <IconButton onClick={importFile} tone="accent">
          Import
        </IconButton>
        {fileNote && <Note ok={fileNote.ok}>{fileNote.text}</Note>}
      </Section>

      <Section title="Run SQL">
        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          rows={4}
          placeholder="SELECT * FROM products LIMIT 10;"
          className="w-full resize-y rounded-md border border-input bg-code-bg p-2 font-mono text-[12px] outline-none focus:ring-2 focus:ring-ring"
        />
        <IconButton onClick={run} disabled={running} tone="accent">
          {running ? <Loader2 size={12} className="animate-spin" /> : null} Run
        </IconButton>
        {error && <Note ok={false}>{error}</Note>}
        {result && <TableCard result={result} />}
      </Section>
    </div>
  );
}

function DashboardTab({ sessionId }: { sessionId: string | null }) {
  const { dashboardVersion } = useApp();
  const [items, setItems] = useState<DashboardItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!sessionId) {
      setItems([]);
      return;
    }
    setLoading(true);
    api
      .dashboard(sessionId)
      .then((r) => !cancelled && setItems(r.items ?? []))
      .catch(() => !cancelled && setItems([]))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [sessionId, dashboardVersion]);

  const remove = async (id: string) => {
    try {
      await api.removeItem(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
      toast.success("Removed");
    } catch {
      toast.error("Couldn't remove item");
    }
  };

  const share = async () => {
    if (!sessionId) return;
    try {
      const r = await api.share(sessionId);
      await navigator.clipboard.writeText(`${window.location.origin}/shared/${r.share_id}`);
      toast.success("Share link copied ✓");
    } catch {
      toast.error("Couldn't create share link");
    }
  };

  if (loading)
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-lg bg-secondary" />
        ))}
      </div>
    );

  return (
    <div className="space-y-3">
      <IconButton onClick={share} tone="accent">
        <Share2 size={12} /> Share dashboard
      </IconButton>
      {items.length === 0 ? (
        <div className="panel px-4 py-8 text-center text-xs text-muted-foreground">
          Nothing pinned yet. Pin a chart or diagram from the chat.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3">
          {items.map((item) => (
            <div key={item.id} className="panel overflow-hidden">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                <span className="truncate text-xs font-semibold">{item.title}</span>
                <button
                  onClick={() => remove(item.id)}
                  aria-label="Remove"
                  className="ml-auto rounded p-1 text-muted-foreground hover:text-destructive"
                >
                  <X size={13} />
                </button>
              </div>
              <PinnedBody item={item} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function PinnedBody({ item }: { item: DashboardItem }) {
  if (item.kind === "chart")
    return <ChartView spec={item.payload as unknown as ChartSpec} height={220} />;
  if (item.kind === "diagram")
    return <DiagramView code={String((item.payload as { mermaid?: string }).mermaid ?? "")} />;
  const text =
    (item.payload as { explanation?: string; text?: string }).explanation ??
    (item.payload as { text?: string }).text ??
    "";
  return <div className="px-3 py-2">{text ? <MarkdownText>{text}</MarkdownText> : null}</div>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel space-y-2 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      {children}
    </div>
  );
}

function Note({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <div
      className={`rounded-md px-2 py-1.5 text-[11px] ${
        ok ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive"
      }`}
    >
      {children}
    </div>
  );
}
