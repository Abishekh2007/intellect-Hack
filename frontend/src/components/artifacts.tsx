import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import Markdown from "react-markdown";
import {
  Check,
  ChevronDown,
  Copy,
  Loader2,
  Pin,
  Play,
  Table2,
  Terminal,
  Workflow,
  BarChart3,
  Download,
} from "lucide-react";
import { api, type ChartSpec, type DiagramSpec, type QueryResult } from "@/lib/api";
import { chartPalette, useTheme } from "@/lib/theme";
import { exportCsv, exportImage, exportPdf } from "@/lib/export-utils";

function CardShell({
  icon,
  title,
  actions,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="panel overflow-hidden">
      <div className="flex items-center gap-2 border-b border-border bg-surface/60 px-3 py-2">
        <span className="text-muted-foreground">{icon}</span>
        <span className="text-xs font-semibold tracking-wide uppercase text-muted-foreground">
          {title}
        </span>
        <div className="ml-auto flex items-center gap-1">{actions}</div>
      </div>
      {children}
    </div>
  );
}

export function IconButton({
  children,
  onClick,
  title,
  disabled,
  tone = "default",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  title?: string;
  disabled?: boolean;
  tone?: "default" | "accent";
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs font-medium transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 ${
        tone === "accent"
          ? "bg-primary text-primary-foreground hover:opacity-90"
          : "bg-secondary text-secondary-foreground hover:bg-accent"
      }`}
    >
      {children}
    </button>
  );
}

/* ---------------- SQL ---------------- */

export function SqlCard({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Clipboard unavailable");
    }
  };

  const run = async () => {
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
    <CardShell
      icon={<Terminal size={14} />}
      title="SQL"
      actions={
        <>
          <IconButton onClick={copy} title="Copy SQL">
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? "Copied!" : "Copy"}
          </IconButton>
          <IconButton onClick={run} title="Run SQL" disabled={running} tone="accent">
            {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            Run
          </IconButton>
          <IconButton onClick={() => setOpen((o) => !o)} title="Collapse">
            <ChevronDown size={12} className={open ? "" : "-rotate-90"} />
          </IconButton>
        </>
      }
    >
      {open && (
        <pre className="scroll-thin max-h-72 overflow-x-auto bg-code-bg px-3 py-3 font-mono text-[12.5px] leading-relaxed text-info">
          {sql}
        </pre>
      )}
      {error && (
        <div className="border-t border-border bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}
      {result && (
        <div className="border-t border-border p-2">
          <TableCard result={result} embedded />
        </div>
      )}
    </CardShell>
  );
}

/* ---------------- Table ---------------- */

export function TableCard({ result, embedded }: { result: QueryResult; embedded?: boolean }) {
  const rows = result.rows ?? [];
  const columns = result.columns ?? [];
  const body = (
    <>
      {result.truncated && (
        <div className="border-b border-border bg-warning/10 px-3 py-1.5 text-xs text-warning">
          Showing first {rows.length} of more — result was truncated by the server.
        </div>
      )}
      {rows.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground">No rows returned</div>
      ) : (
        <div className="scroll-thin max-h-80 overflow-auto">
          <table className="w-full border-collapse text-[12.5px]">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr>
                {columns.map((c) => (
                  <th
                    key={c}
                    className="border-b border-border px-3 py-2 text-left font-mono text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={i % 2 ? "bg-secondary/40" : ""}>
                  {r.map((cell, j) => (
                    <td
                      key={j}
                      className={`border-b border-border/60 px-3 py-1.5 font-mono ${
                        typeof cell === "number" ? "text-right tabular-nums" : ""
                      }`}
                    >
                      {cell === null || cell === undefined ? "—" : String(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );

  if (embedded) return <div className="overflow-hidden rounded-md border border-border">{body}</div>;

  return (
    <CardShell
      icon={<Table2 size={14} />}
      title="Results"
      actions={
        <>
          <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground mr-1">
            {result.row_count ?? rows.length} rows
          </span>
          <IconButton onClick={() => exportCsv(result.columns ?? [], result.rows ?? [], "table.csv")} title="Export CSV">
            <Download size={12} /> CSV
          </IconButton>
        </>
      }
    >
      {body}
    </CardShell>
  );
}

/* ---------------- Chart ---------------- */

function buildOption(spec: ChartSpec, theme: "dark" | "light") {
  const p = chartPalette(theme);
  const c0 = p.series[0] ?? "#6366f1";
  const c1 = p.series[1] ?? "#8b5cf6";
  const cols = spec.columns ?? [];
  const xi = Math.max(0, cols.indexOf(spec.x_key));
  const yi = cols.indexOf(spec.y_key) === -1 ? Math.min(1, cols.length - 1) : cols.indexOf(spec.y_key);
  const rows = spec.rows ?? [];
  const cats = rows.map((r) => String(r[xi]));
  const vals = rows.map((r) => Number(r[yi]));
  const title = spec.title || `${spec.x_key} vs ${spec.y_key}`;

  const base = {
    color: p.series,
    title: {
      text: title,
      left: 8,
      top: 4,
      textStyle: { color: p.text, fontSize: 13, fontWeight: 600 },
    },
    tooltip: {
      trigger: spec.type === "pie" || spec.type === "scatter" ? "item" : "axis",
      backgroundColor: p.tooltipBg,
      borderColor: p.split,
      textStyle: { color: p.text },
    },
    grid: { left: 48, right: 24, top: 46, bottom: 48 },
  };

  const axisCommon = {
    axisLine: { lineStyle: { color: p.axis } },
    axisLabel: { color: p.text, fontSize: 11 },
    splitLine: { lineStyle: { color: p.split } },
  };

  const gradient = (from: string, to: string, opacityTo = 0) =>
    new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: from },
      { offset: 1, color: opacityTo ? to : to },
    ]);

  if (spec.type === "pie") {
    return {
      ...base,
      grid: undefined,
      tooltip: { ...base.tooltip, trigger: "item" },
      legend: { bottom: 0, textStyle: { color: p.text, fontSize: 11 } },
      series: [
        {
          type: "pie",
          radius: ["38%", "66%"],
          center: ["50%", "48%"],
          data: rows.map((r) => ({ name: String(r[xi]), value: Number(r[yi]) })),
          label: { color: p.text, formatter: "{b}: {d}%", fontSize: 11 },
        },
      ],
    };
  }

  if (spec.type === "scatter") {
    return {
      ...base,
      xAxis: { type: "value", ...axisCommon },
      yAxis: { type: "value", ...axisCommon },
      series: [
        {
          type: "scatter",
          symbolSize: 12,
          itemStyle: { color: c0, opacity: 0.7 },
          data: rows.map((r) => [Number(r[xi]), Number(r[yi])]),
        },
      ],
    };
  }

  if (spec.type === "line" || spec.type === "area") {
    const strong = spec.type === "area";
    return {
      ...base,
      xAxis: { type: "category", data: cats, ...axisCommon },
      yAxis: { type: "value", ...axisCommon },
      series: [
        {
          type: "line",
          smooth: true,
          data: vals,
          symbolSize: 6,
          lineStyle: { width: 2.5, color: c0 },
          itemStyle: { color: c0 },
          areaStyle: {
            opacity: strong ? 0.35 : 0.18,
            color: gradient(c0, "rgba(99,102,241,0)"),
          },
        },
      ],
    };
  }

  return {
    ...base,
    xAxis: { type: "category", data: cats, ...axisCommon },
    yAxis: { type: "value", ...axisCommon },
    series: [
      {
        type: "bar",
        data: vals,
        barMaxWidth: 44,
        label:
          vals.length <= 8
            ? { show: true, position: "top", color: p.text, fontSize: 11 }
            : { show: false },
        itemStyle: {
          borderRadius: [6, 6, 0, 0],
          color: gradient(c0, c1),
        },
      },
    ],
  };
}

export function ChartView({ spec, height = 320 }: { spec: ChartSpec; height?: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const { theme } = useTheme();
  const rows = spec?.rows ?? [];

  useEffect(() => {
    if (spec?.type === "kpi" || rows.length === 0 || !ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(buildOption(spec, theme) as echarts.EChartsCoreOption);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [spec, theme, rows.length]);

  if (!spec || rows.length === 0) {
    return <div className="px-3 py-8 text-center text-xs text-muted-foreground">No data to chart</div>;
  }

  if (spec.type === "kpi") {
    const label = spec.y_key || spec.x_key || spec.columns?.[0] || "Value";
    const value = spec.rows[0]?.[spec.rows[0].length - 1];
    return (
      <div className="flex flex-col items-center justify-center gap-1 px-4 py-10">
        <div className="text-xs uppercase tracking-widest text-muted-foreground">{label}</div>
        <div className="brand-gradient bg-clip-text text-5xl font-bold tabular-nums text-transparent">
          {typeof value === "number" ? value.toLocaleString() : String(value ?? "—")}
        </div>
        {spec.title && <div className="text-xs text-muted-foreground">{spec.title}</div>}
      </div>
    );
  }

  return <div ref={ref} style={{ height }} className="w-full" />;
}

export function ChartCard({
  spec,
  onPin,
  height,
}: {
  spec: ChartSpec;
  onPin?: () => void;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  return (
    <div ref={containerRef}>
      <CardShell
        icon={<BarChart3 size={14} />}
        title="Chart"
        actions={
          <>
            <IconButton onClick={() => exportImage(containerRef.current!, "chart.png")} title="Export PNG">
              <Download size={12} /> PNG
            </IconButton>
            <IconButton onClick={() => exportPdf(containerRef.current!, "chart.pdf")} title="Export PDF">
              <Download size={12} /> PDF
            </IconButton>
            {onPin && (
              <IconButton onClick={onPin} title="Pin to dashboard">
                <Pin size={12} /> Pin
              </IconButton>
            )}
          </>
        }
      >
        <ChartView spec={spec} {...(height ? { height } : {})} />
      </CardShell>
    </div>
  );
}

/* ---------------- Diagram ---------------- */

let mermaidReady: Promise<typeof import("mermaid").default> | null = null;
let mermaidTheme = "";

async function getMermaid(theme: "dark" | "light") {
  if (!mermaidReady) mermaidReady = import("mermaid").then((m) => m.default);
  const mermaid = await mermaidReady;
  if (mermaidTheme !== theme) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      theme: theme === "dark" ? "dark" : "default",
      themeVariables: { primaryColor: "#6366f1", fontFamily: "Inter, sans-serif" },
    });
    mermaidTheme = theme;
  }
  return mermaid;
}

export function DiagramView({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { theme } = useTheme();
  const id = useMemo(() => `mmd-${Math.random().toString(36).slice(2)}`, []);

  useEffect(() => {
    let cancelled = false;
    setSvg(null);
    setError(null);
    (async () => {
      try {
        const mermaid = await getMermaid(theme);
        const { svg } = await mermaid.render(id, code);
        if (!cancelled) setSvg(svg);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, theme, id]);

  if (error)
    return <div className="px-3 py-4 text-xs text-destructive">Could not render diagram: {error}</div>;
  if (!svg)
    return (
      <div className="flex items-center justify-center gap-2 px-3 py-8 text-xs text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> Rendering diagram…
      </div>
    );
  return (
    <div
      className="scroll-thin overflow-auto p-3 [&_svg]:mx-auto [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

export function DiagramCard({ diagram, onPin }: { diagram: DiagramSpec; onPin?: () => void }) {
  return (
    <CardShell
      icon={<Workflow size={14} />}
      title="Diagram"
      actions={
        onPin ? (
          <IconButton onClick={onPin} title="Pin to dashboard">
            <Pin size={12} /> Pin
          </IconButton>
        ) : null
      }
    >
      <DiagramView code={diagram.mermaid} />
    </CardShell>
  );
}

export function MarkdownText({ children }: { children: string }) {
  return (
    <div className="prose-sm max-w-none space-y-2 text-[15px] leading-relaxed [&_a]:text-primary [&_code]:rounded [&_code]:bg-code-bg [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12.5px] [&_li]:ml-4 [&_li]:list-disc [&_strong]:font-semibold">
      <Markdown>{children}</Markdown>
    </div>
  );
}
