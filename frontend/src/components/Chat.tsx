import { useEffect, useRef, useState } from "react";
import { Loader2, SendHorizonal, Sparkles, Mic, MicOff } from "lucide-react";
import { useApp } from "@/lib/app-state";
import { ChartCard, DiagramCard, MarkdownText, SqlCard, TableCard } from "@/components/artifacts";
import { Logo } from "@/components/Logo";
import { useSpeechRecognition } from "@/hooks/use-speech";
const CHIPS = [
  "Top 5 products by revenue",
  "Monthly revenue trend",
  "Low stock products",
  "Show me the ER diagram",
];

export function Chat() {
  const { thread, isStreaming, statusLabel, toolChip, send, pin, backendOnline } = useApp();
  const { isListening, transcript, startListening, stopListening, hasSupport, resetTranscript } = useSpeechRecognition();
  const [typedValue, setTypedValue] = useState("");
  const value = (typedValue + (isListening && transcript ? " " + transcript : "")).trim();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickRef = useRef(true);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!isListening && transcript) {
      setTypedValue(prev => (prev + " " + transcript).trim());
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
  }, [value]);

  const submit = () => {
    if (!value.trim() || isStreaming) return;
    stickRef.current = true;
    send(value);
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
            <div className="hero-grid flex min-h-[50vh] flex-col items-center justify-center gap-4 rounded-2xl text-center">
              <Logo size={48} />
              <h1 className="text-2xl font-semibold tracking-tight">
                Ask anything about your database
              </h1>
              <p className="max-w-md text-sm text-muted-foreground">
                DataPilot writes read-only SQL, returns tables, charts and diagrams — and remembers
                the conversation.
              </p>
            </div>
          ) : (
            <div className="space-y-5">
              {thread.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="flex justify-end">
                    <div className="max-w-[70%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-[15px] text-primary-foreground shadow-[var(--shadow-card)]">
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <div key={m.id} className="flex justify-start">
                    <div className="w-full max-w-[85%] space-y-3">
                      <div className="panel px-4 py-3">
                        {m.content ? (
                          <MarkdownText>{m.content}</MarkdownText>
                        ) : m.done ? (
                          <span className="text-sm text-muted-foreground">No answer returned.</span>
                        ) : (
                          <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader2 size={14} className="animate-spin" /> Generating…
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
                                a.diagram.type === "er" ? "ER Diagram" : a.diagram.type || "Diagram",
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

      <div className="shrink-0 border-t border-border bg-surface/60 px-4 py-3 backdrop-blur">
        <div className="mx-auto w-full max-w-3xl space-y-2">
          {toolChip && (
            <div className="text-[11px] text-info">using tool: {toolChip}</div>
          )}
          {statusLabel && (
            <div className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
              <Loader2 size={12} className="animate-spin" /> Thinking… {statusLabel}
            </div>
          )}
          {thread.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {CHIPS.map((c) => (
                <button
                  key={c}
                  onClick={() => send(c)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary px-3 py-1.5 text-xs text-secondary-foreground transition-colors duration-150 hover:bg-accent"
                >
                  <Sparkles size={12} className="text-primary" />
                  {c}
                </button>
              ))}
            </div>
          )}
          <div className="panel flex items-end gap-2 px-3 py-2">
            <textarea
              ref={taRef}
              rows={1}
              value={value}
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
              className="max-h-[150px] flex-1 resize-none bg-transparent py-1.5 text-[15px] outline-none placeholder:text-muted-foreground"
            />
            {hasSupport && (
              <button
                onClick={isListening ? stopListening : startListening}
                title={isListening ? "Stop listening" : "Start voice input"}
                className={`flex h-9 w-9 items-center justify-center rounded-lg transition-colors duration-150 ${
                  isListening
                    ? "bg-destructive text-destructive-foreground animate-pulse"
                    : "bg-secondary text-secondary-foreground hover:bg-accent"
                }`}
              >
                {isListening ? <MicOff size={16} /> : <Mic size={16} />}
              </button>
            )}
            <button
              onClick={submit}
              disabled={isStreaming || !value.trim()}
              title={backendOnline === false ? "Backend appears offline" : "Send"}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity duration-150 hover:opacity-90 disabled:opacity-40"
            >
              {isStreaming ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <SendHorizonal size={16} />
              )}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
