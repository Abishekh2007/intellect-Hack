import { useEffect, useState } from "react";
import { Menu, Moon, PanelRight, PanelRightClose, Sun, Wifi, WifiOff } from "lucide-react";
import { ConnectionPicker } from "@/components/ConnectionPicker";
import { Logo } from "@/components/Logo";
import { useApp } from "@/lib/app-state";
import { useTheme } from "@/lib/theme";

export function TopBar({
  onToggleSidebar,
  onTogglePanel,
  panelOpen,
}: {
  onToggleSidebar: () => void;
  onTogglePanel: () => void;
  panelOpen?: boolean;
}) {
  const { sessions, activeSessionId, renameActive, mode, backendOnline } = useApp();
  const { theme, toggle } = useTheme();
  const active = sessions.find((s) => s.id === activeSessionId);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => setDraft(active?.title ?? ""), [active?.title]);

  const commit = () => {
    setEditing(false);
    if (draft.trim() && draft.trim() !== active?.title) renameActive(draft);
  };

  return (
    <header className="relative z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-3">
      <button
        onClick={onToggleSidebar}
        className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:hidden"
        aria-label="Toggle sidebar"
      >
        <Menu size={18} />
      </button>

      <div className="flex items-center gap-2.5">
        <Logo size={28} />
        <span className="hidden text-[15px] font-semibold tracking-tight sm:block">
          DataPilot <span className="text-muted-foreground">AI</span>
        </span>
      </div>

      <div className="mx-auto hidden max-w-[40%] flex-1 justify-center md:flex">
        {active &&
          (editing ? (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit();
                if (e.key === "Escape") setEditing(false);
              }}
              className="w-full rounded-lg border border-input bg-surface/80 px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="truncate rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent/80 hover:text-foreground"
              title="Rename session"
            >
              {active.title}
            </button>
          ))}
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <ConnectionPicker />
        {/* One status, not two: when the backend is unreachable the engine
            label is meaningless, so the pill reports the problem instead. */}
        <Pill
          icon={
            backendOnline === false ? (
              <WifiOff size={11} className="text-destructive" />
            ) : backendOnline ? (
              <Wifi size={11} className="text-success" />
            ) : null
          }
          dotClass={backendOnline === null ? "bg-muted-foreground animate-pulse" : "bg-success"}
          label={
            backendOnline === false
              ? "Backend offline"
              : backendOnline === null
                ? "Connecting…"
                : mode
          }
          className="hidden sm:inline-flex"
          title={
            backendOnline === false
              ? "Can't reach the API on port 8000"
              : `Answering with: ${mode}`
          }
        />
        <button
          onClick={toggle}
          className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          onClick={onTogglePanel}
          className={`rounded-lg p-2 transition-colors ${
            panelOpen
              ? "bg-primary/15 text-primary"
              : "text-muted-foreground hover:bg-accent hover:text-foreground"
          }`}
          aria-label="Toggle right panel"
        >
          {panelOpen ? <PanelRightClose size={16} /> : <PanelRight size={16} />}
        </button>
      </div>
    </header>
  );
}

function Pill({
  dotClass,
  label,
  icon,
  className = "",
  title,
}: {
  dotClass: string;
  label: string;
  icon?: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-border bg-surface px-2 py-1 text-[11px] font-medium text-muted-foreground ${className}`}
    >
      {icon ?? <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />}
      {label}
    </span>
  );
}
