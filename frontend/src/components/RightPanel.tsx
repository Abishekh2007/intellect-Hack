import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  Database,
  History,
  LayoutDashboard,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Share2,
  Table2,
  Upload,
  Workflow,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api, type ChartSpec, type DashboardItem, type QueryResult, type Schema } from "@/lib/api";
import {
  ChartView,
  DiagramView,
  IconButton,
  MarkdownText,
  TableCard,
} from "@/components/artifacts";
import { useApp } from "@/lib/app-state";
import { QueryHistory } from "./QueryHistory";
import { motion, AnimatePresence } from "framer-motion";

type Tab = "schema" | "database" | "dashboard" | "history";

export function RightPanel({
  onClose,
  tab,
  onTabChange,
}: {
  onClose: () => void;
  /* The active tab is owned by the page so the command palette can jump
     straight to one. Uncontrolled use still works for any other caller. */
  tab?: Tab;
  onTabChange?: (tab: Tab) => void;
}) {
  const [internalTab, setInternalTab] = useState<Tab>("schema");
  const activeTab = tab ?? internalTab;
  const setTab = (next: Tab) => (onTabChange ? onTabChange(next) : setInternalTab(next));
  const [schema, setSchema] = useState<Schema | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const { activeSessionId, send, connectionVersion } = useApp();

  const loadSchema = useCallback(async () => {
    setSchemaLoading(true);
    try {
      // Scoped to the session so the panel shows whichever database this
      // chat is pointed at, not always the demo one.
      setSchema(await api.schema(activeSessionId));
    } catch {
      setSchema({ tables: [] });
    } finally {
      setSchemaLoading(false);
    }
  }, [activeSessionId]);

  useEffect(() => {
    loadSchema();
  }, [loadSchema, connectionVersion]);

  return (
    <aside className="flex h-full w-full flex-col border-l border-border bg-surface lg:w-[380px] lg:shrink-0">
      <div className="flex items-center gap-0.5 border-b border-border px-1.5 py-2">
        {(
          [
            ["schema", "Schema", <Table2 key="a" size={13} />],
            ["database", "Data", <Database key="b" size={13} />],
            // "Pinned" says what the tab holds and fits the panel; "Dashboard"
            // truncated to "Dashb…" at this width.
            ["dashboard", "Pinned", <LayoutDashboard key="c" size={13} />],
            ["history", "History", <History key="d" size={13} />],
          ] as [Tab, string, React.ReactNode][]
        ).map(([id, label, icon]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            title={label}
            className={`inline-flex min-w-0 flex-1 items-center justify-center gap-1 rounded-md px-1.5 py-1.5 text-xs font-medium transition-colors duration-150 ${
              activeTab === id
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-secondary"
            }`}
          >
            <span className="shrink-0">{icon}</span>
            <span className="truncate">{label}</span>
          </button>
        ))}
        <button
          onClick={onClose}
          aria-label="Close panel"
          className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-secondary"
        >
          <X size={14} />
        </button>
      </div>

      <div className="scroll-thin flex-1 space-y-3 p-3">
        {activeTab === "schema" && (
          <SchemaTab
            schema={schema}
            loading={schemaLoading}
            onRefresh={loadSchema}
            onEr={() => send("show me the ER diagram")}
            activeSessionId={activeSessionId}
          />
        )}
        {activeTab === "database" && <DatabaseTab onSchemaChanged={loadSchema} />}
        {activeTab === "dashboard" && <DashboardTab sessionId={activeSessionId} />}
        {activeTab === "history" && <QueryHistory />}
      </div>
    </aside>
  );
}

function SchemaTab({
  schema,
  loading,
  onRefresh,
  onEr,
  activeSessionId,
}: {
  schema: Schema | null;
  loading: boolean;
  onRefresh: () => void;
  onEr: () => void;
  activeSessionId: string | null;
}) {
  /* Every hook runs on every render, before any conditional return.
     The loading branch used to sit above these useState calls, so the render
     after the schema arrived ran three more hooks than the one before it and
     React threw "Rendered more hooks than during the previous render" —
     taking the whole panel down the first time the schema loaded. */
  const [previewTable, setPreviewTable] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<QueryResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [query, setQuery] = useState("");

  const tables = schema?.tables ?? [];
  const filtered = query.trim()
    ? tables.filter((t) => {
        const q = query.trim().toLowerCase();
        return (
          t.name.toLowerCase().includes(q) ||
          t.columns.some((c) => c.name.toLowerCase().includes(q))
        );
      })
    : tables;

  const handlePreview = async (tableName: string) => {
    setPreviewTable(tableName);
    setPreviewData(null);
    setPreviewLoading(true);
    try {
      setPreviewData(await api.tablePreview(tableName, activeSessionId));
    } catch (e) {
      toast.error((e as Error).message || "Couldn't preview table");
      setPreviewTable(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const closePreview = () => {
    setPreviewTable(null);
    setPreviewData(null);
  };

  if (loading)
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

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <IconButton onClick={onEr} tone="accent" title="Draw the ER diagram">
          <Workflow size={12} /> ER diagram
        </IconButton>
        <IconButton onClick={onRefresh} title="Reload the schema">
          <RefreshCw size={12} /> Refresh
        </IconButton>
      </div>

      {tables.length > 3 && (
        <div className="relative">
          <Search
            size={13}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter tables and columns…"
            aria-label="Filter tables and columns"
            className="w-full rounded-md border border-input bg-background/60 py-1.5 pl-8 pr-3 text-xs outline-none transition-colors placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/30"
          />
        </div>
      )}

      {tables.length === 0 ? (
        <div className="panel px-4 py-8 text-center">
          <Database size={20} className="mx-auto mb-2 text-muted-foreground opacity-40" />
          <p className="text-xs text-muted-foreground">
            No schema available. Upload a database from the Data tab.
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <p className="px-1 py-6 text-center text-xs text-muted-foreground">
          Nothing matches “{query}”.
        </p>
      ) : (
        filtered.map((t) => (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18 }}
            key={t.name}
            className="panel overflow-hidden transition-colors hover:border-primary/30"
          >
            <div className="flex items-center gap-2 border-b border-border/70 px-3 py-2">
              <Table2 size={12} className="shrink-0 text-primary" />
              <span className="truncate font-mono text-[13px] font-semibold">{t.name}</span>
              <span className="shrink-0 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {t.columns.length}
              </span>
              <div className="ml-auto shrink-0">
                <IconButton onClick={() => handlePreview(t.name)} title={`Preview ${t.name}`}>
                  Preview
                </IconButton>
              </div>
            </div>
            <div className="space-y-0.5 px-3 py-2">
              {t.columns.map((c) => (
                <div key={c.name} className="flex items-baseline gap-2 text-[12px]">
                  <span className="truncate font-mono">{c.name}</span>
                  <span className="ml-auto shrink-0 font-mono text-[10.5px] uppercase text-muted-foreground">
                    {c.type}
                  </span>
                  {c.pk && (
                    <span className="shrink-0 rounded bg-primary/20 px-1.5 text-[10px] font-semibold text-primary">
                      PK
                    </span>
                  )}
                </div>
              ))}
            </div>
            {(t.foreign_keys ?? []).length > 0 && (
              <div className="space-y-0.5 border-t border-border/70 bg-secondary/30 px-3 py-2">
                {t.foreign_keys!.map((fk) => (
                  <div key={fk.column} className="font-mono text-[11px] text-muted-foreground">
                    {fk.column} → {fk.references_table}.{fk.references_column}
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        ))
      )}

      <AnimatePresence>
        {previewTable && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            role="dialog"
            aria-modal="true"
            aria-label={`Preview of ${previewTable}`}
            /* Escape and a backdrop click both close it. Previously the only
               way out was the button, which is a trap on a touch device. */
            onKeyDown={(e) => e.key === "Escape" && closePreview()}
            onClick={closePreview}
            tabIndex={-1}
            className="fixed inset-0 z-50 flex items-center justify-center bg-background/85 p-4 backdrop-blur-sm"
          >
            <motion.div
              initial={{ scale: 0.97, y: 8 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.97, y: 8 }}
              transition={{ duration: 0.15 }}
              onClick={(e) => e.stopPropagation()}
              className="flex max-h-[80vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
            >
              <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <Table2 size={14} className="text-primary" />
                <h3 className="truncate font-mono text-sm font-semibold">{previewTable}</h3>
                <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">
                  first 50 rows
                </span>
                <button
                  onClick={closePreview}
                  aria-label="Close preview"
                  className="ml-auto rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  <X size={15} />
                </button>
              </div>
              <div className="scroll-thin flex-1 overflow-auto p-4">
                {previewLoading ? (
                  <div className="flex items-center justify-center gap-2 p-10 text-xs text-muted-foreground">
                    <Loader2 size={15} className="animate-spin" /> Loading rows…
                  </div>
                ) : previewData ? (
                  <TableCard result={previewData} />
                ) : null}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function DatabaseTab({ onSchemaChanged }: { onSchemaChanged: () => void }) {
  const { activeSessionId, onConnectionChange } = useApp();
  const dbRef = useRef<HTMLInputElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [dbNote, setDbNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [fileNote, setFileNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [dbBusy, setDbBusy] = useState(false);
  const [fileBusy, setFileBusy] = useState(false);
  const [sql, setSql] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const uploadDb = async () => {
    const f = dbRef.current?.files?.[0];
    if (!f) {
      setDbNote({ ok: false, text: "Choose a .db file first." });
      return;
    }
    setDbBusy(true);
    setDbNote(null);
    try {
      const r = await api.uploadDatabase(f, activeSessionId);
      setDbNote({
        ok: true,
        text: `${r.connection?.name ?? "Database"} connected — ${r.tables?.length ?? 0} tables`,
      });
      onConnectionChange();
      onSchemaChanged();
    } catch (e) {
      setDbNote({ ok: false, text: (e as Error).message });
    } finally {
      setDbBusy(false);
    }
  };

  const importFile = async () => {
    const f = fileRef.current?.files?.[0];
    if (!f) {
      setFileNote({ ok: false, text: "Choose a file to import first." });
      return;
    }
    setFileBusy(true);
    setFileNote(null);
    try {
      const r = await api.uploadDataFile(f, activeSessionId);
      // `info` is an object from the server. Rendering it directly threw
      // "Objects are not valid as a React child" and blanked the whole panel.
      const info = r.info;
      setFileNote({
        ok: true,
        text: info
          ? `Imported ${info.row_count.toLocaleString()} rows into “${info.table_name}” (${info.columns.length} columns).`
          : "Imported.",
      });
      onConnectionChange();
      onSchemaChanged();
    } catch (e) {
      setFileNote({ ok: false, text: (e as Error).message });
    } finally {
      setFileBusy(false);
    }
  };

  const run = async () => {
    if (!sql.trim()) return;
    setRunning(true);
    setError(null);
    try {
      // Scoped to the session, so this runs against whichever database the
      // chat is pointed at. Without the id it always hit the demo database,
      // and a query against an uploaded table failed with "no such table".
      setResult(await api.query(sql, activeSessionId));
    } catch (e) {
      setResult(null);
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-3">
      <Section
        title="Upload database"
        hint="A SQLite file. It is added alongside the demo, never replacing it."
      >
        <input
          ref={dbRef}
          type="file"
          accept=".db,.sqlite,.sqlite3"
          aria-label="SQLite database file"
          className={FILE_INPUT}
        />
        <IconButton onClick={uploadDb} tone="accent" disabled={dbBusy}>
          {dbBusy ? <Loader2 size={12} className="animate-spin" /> : <Database size={12} />}
          {dbBusy ? "Uploading…" : "Upload"}
        </IconButton>
        {dbNote && <Note ok={dbNote.ok}>{dbNote.text}</Note>}
      </Section>

      <Section
        title="Import data file"
        hint="CSV, Excel, JSON, PDF or Word — converted into a queryable table."
      >
        <input
          ref={fileRef}
          type="file"
          /* .xls was missing here but accepted by the server, so a perfectly
             valid file could not be selected in the picker. */
          accept=".csv,.xlsx,.xls,.pdf,.docx,.json"
          aria-label="Data file to import"
          className={FILE_INPUT}
        />
        <IconButton onClick={importFile} tone="accent" disabled={fileBusy}>
          {fileBusy ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
          {fileBusy ? "Importing…" : "Import"}
        </IconButton>
        {fileNote && <Note ok={fileNote.ok}>{fileNote.text}</Note>}
      </Section>

      <Section title="Run SQL" hint="Read-only. SELECT statements only.">
        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={(e) => {
            // Ctrl/Cmd+Enter runs, the convention in every SQL console.
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              run();
            }
          }}
          rows={4}
          spellCheck={false}
          placeholder="SELECT * FROM products LIMIT 10;"
          aria-label="SQL query"
          className="w-full resize-y rounded-md border border-input bg-code-bg p-2 font-mono text-[12px] leading-relaxed outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30"
        />
        <div className="flex items-center gap-2">
          <IconButton onClick={run} disabled={running || !sql.trim()} tone="accent">
            {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            {running ? "Running…" : "Run"}
          </IconButton>
          <span className="text-[10.5px] text-muted-foreground">⌘/Ctrl + ↵</span>
        </div>
        {error && <Note ok={false}>{error}</Note>}
        {result && <TableCard result={result} />}
      </Section>
    </div>
  );
}

const FILE_INPUT =
  "w-full cursor-pointer rounded-md border border-dashed border-border bg-background/40 p-2 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 file:mr-2 file:cursor-pointer file:rounded-md file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-[11px] file:font-medium file:text-secondary-foreground";

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

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="panel space-y-2 p-3">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </div>
        {hint && <p className="mt-0.5 text-[11px] text-muted-foreground/80">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

function Note({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <div
      role="status"
      className={`flex items-start gap-1.5 rounded-md px-2 py-1.5 text-[11px] ${
        ok ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive"
      }`}
    >
      {ok ? (
        <Check size={12} className="mt-px shrink-0" />
      ) : (
        <AlertCircle size={12} className="mt-px shrink-0" />
      )}
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}
