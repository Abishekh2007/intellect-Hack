import { useEffect, useRef, useState } from "react";
import {
  BarChart3,
  Check,
  Copy,
  Loader2,
  Mic,
  MicOff,
  SendHorizonal,
  Square,
  TrendingUp,
  Boxes,
  Workflow,
} from "lucide-react";
import { toast } from "sonner";
import { useApp } from "@/lib/app-state";
import { ChartCard, DiagramCard, MarkdownText, SqlCard, TableCard } from "@/components/artifacts";
import { Logo } from "@/components/Logo";
import { useSpeechRecognition } from "@/hooks/use-speech";

const CHIPS = [
  { label: "Top 5 products by revenue", icon: BarChart3 },
  { label: "Monthly revenue trend", icon: TrendingUp },
  { label: "Low stock products", icon: Boxes },
  { label: "Show me the ER diagram", icon: Workflow },
];

/* The backend emits machine-readable step names. Showing "inspecting_schema"
   to a user leaked an implementation detail into the interface. */
const STATUS_TEXT: Record<string, string> = {
  inspecting_schema: "Reading the schema",
  generating_plan: "Planning the query",
  executing_tools: "Running tools",
  working: "Working",
  thinking: "Thinking",
};

const TOOL_TEXT: Record<string, string> = {
  get_schema: "reading the schema",
  execute_query: "running SQL",
  generate_chart: "building a chart",
  generate_flowchart: "drawing a diagram",
  explain_data: "analysing the result",
  verify_response: "checking the answer",
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          toast.error("Clipboard unavailable.");
        }
      }}
      title="Copy this answer"
      aria-label="Copy this answer"
      className="rounded-md p-1 text-muted-foreground opacity-0 transition-all hover:bg-secondary hover:text-foreground focus-visible:opacity-100 group-hover/msg:opacity-100"
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
    </button>
  );
}

export function Chat() {
  const { thread, isStreaming, statusLabel, toolChip, send, stop, pin, backendOnline } = useApp();
  const { isListening, transcript, startListening, stopListening, hasSupport, resetTranscript } =
    useSpeechRecognition();
  const [typedValue, setTypedValue] = useState("");
  const displayValue = typedValue + (isListening && transcript ? " " + transcript : "");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickRef = useRef(true);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!isListening && transcript) {
      setTypedValue((prev) => (prev + " " + transcript).trim());
      resetTranscript();
    }
  }, [isListening, transcript, resetTranscript]);

  useEffect(() => {
    if (stickRef.current && scrollRef.current)
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [thread, statusLabel]);

  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 150)}px`;
  }, [displayValue]);

  const submit = () => {
    const text = displayValue.trim();
    if (!text || isStreaming) return;
    stickRef.current = true;
    send(text);
    setTypedValue("");
    resetTranscript();
    if (isListening) stopListening();
  };

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col">
      {backendOnline === false && (
        <div className="border-b border-border bg-destructive/10 px-4 py-2 text-xs text-destructive">
          Can't reach the backend. Is it running on port 8000?
        </div>
      )}

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="scroll-thin flex-1"
      >
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
          {thread.length === 0 ? (
            <div className="flex min-h-[52vh] flex-col items-center justify-center gap-4 px-4 text-center">
              <Logo size={40} />
              <div className="space-y-2">
                <h1 className="font-display text-2xl font-semibold tracking-tight">
                  Ask anything about your database
                </h1>
                <p className="mx-auto max-w-md text-sm leading-relaxed text-muted-foreground">
                  DataPilot writes read-only SQL, returns tables, charts and diagrams — and
                  remembers the conversation.
                </p>
              </div>
              <div className="mt-2 grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
                {CHIPS.map(({ label, icon: Icon }) => (
                  <button
                    key={label}
                    onClick={() => send(label)}
                    className="group flex items-center gap-2.5 rounded-lg border border-border bg-surface px-3 py-2.5 text-left text-[13px] text-muted-foreground transition-all hover:-translate-y-px hover:border-primary/40 hover:text-foreground hover:shadow-[var(--shadow-card)] focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Icon size={14} className="shrink-0 text-primary" />
                    <span className="min-w-0 truncate">{label}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              {thread.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="flex justify-end">
                    <div className="max-w-[75%] rounded-lg bg-secondary px-3.5 py-2 text-[15px] text-secondary-foreground">
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <div key={m.id} className="group/msg flex justify-start">
                    <div className="w-full max-w-[92%] space-y-3">
                      <div className="relative px-1 py-1 text-[15px] text-foreground">
                        {m.content ? (
                          <>
                            <MarkdownText>{m.content}</MarkdownText>
                            {m.done && (
                              <div className="mt-1 flex items-center gap-1">
                                <CopyButton text={m.content} />
                              </div>
                            )}
                          </>
                        ) : m.done ? (
                          <span className="text-sm text-muted-foreground">No answer returned.</span>
                        ) : (
                          <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                            <span className="flex gap-1">
                              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-current" />
                              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-current" />
                              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-current" />
                            </span>
                            Generating…
                          </span>
                        )}
                      </div>
                      {m.artifacts.map((a, i) => {
                        if (a.kind === "sql") return <SqlCard key={i} sql={a.sql} />;
                        if (a.kind === "table") return <TableCard key={i} result={a.table} />;
                        if (a.kind === "chart")
                          return (
                            <ChartCard
                              key={i}
                              spec={a.chart}
                              onPin={() =>
                                pin(
                                  "chart",
                                  a.chart.title || a.chart.columns?.[0] || "Chart",
                                  a.chart as unknown as Record<string, unknown>,
                                )
                              }
                            />
                          );
                        return (
                          <DiagramCard
                            key={i}
                            diagram={a.diagram}
                            onPin={() =>
                              pin(
                                "diagram",
                                a.diagram.type === "er"
                                  ? "ER Diagram"
                                  : a.diagram.type || "Diagram",
                                a.diagram as unknown as Record<string, unknown>,
                              )
                            }
                          />
                        );
                      })}
                      {m.error && (
                        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {m.error}
                        </div>
                      )}
                    </div>
                  </div>
                ),
              )}
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-border/60 bg-background px-4 py-3">
        <div className="mx-auto w-full max-w-3xl space-y-2">
          {(statusLabel || toolChip) && (
            <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              <Loader2 size={12} className="shrink-0 animate-spin text-primary" />
              <span>{STATUS_TEXT[statusLabel ?? ""] ?? "Working"}</span>
              {toolChip && (
                <span className="truncate rounded-full bg-secondary px-2 py-0.5 text-[10.5px] text-info">
                  {TOOL_TEXT[toolChip] ?? toolChip}
                </span>
              )}
              <button
                onClick={stop}
                className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Square size={9} className="fill-current" /> Stop
              </button>
            </div>
          )}
          <div className="flex items-end gap-2 rounded-xl border border-input bg-surface px-3 py-2 transition-colors focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/25">
            <textarea
              ref={taRef}
              rows={1}
              value={displayValue}
              onChange={(e) => {
                if (isListening) stopListening();
                setTypedValue(e.target.value);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder="Ask about your data, e.g. Top 5 products by revenue"
              aria-label="Message"
              className="max-h-[150px] flex-1 resize-none bg-transparent py-1.5 text-[15px] outline-none placeholder:text-muted-foreground"
            />
            {hasSupport && (
              <button
                onClick={isListening ? stopListening : startListening}
                title={isListening ? "Stop listening" : "Start voice input"}
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors ${
                  isListening
                    ? "bg-destructive text-destructive-foreground"
                    : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                }`}
              >
                {isListening ? <MicOff size={16} /> : <Mic size={16} />}
              </button>
            )}
            {/* While a turn is streaming this becomes the stop control, so
                the primary button is never a dead spinner. */}
            {isStreaming ? (
              <button
                onClick={stop}
                title="Stop generating"
                aria-label="Stop generating"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-destructive text-destructive-foreground transition-opacity hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Square size={12} className="fill-current" />
              </button>
            ) : (
              <button
                onClick={submit}
                disabled={!displayValue.trim()}
                title={backendOnline === false ? "Backend appears offline" : "Send"}
                aria-label="Send message"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
              >
                <SendHorizonal size={16} />
              </button>
            )}
          </div>
          <p className="px-1 pt-1.5 text-[10.5px] text-muted-foreground/70">
            Read-only SQL · Enter to send, Shift + Enter for a new line ·{" "}
            <kbd className="rounded border border-border px-1 py-px font-sans">Ctrl</kbd>
            <kbd className="rounded border border-border px-1 py-px font-sans">K</kbd> for commands
          </p>
        </div>
      </div>
    </section>
  );
}
