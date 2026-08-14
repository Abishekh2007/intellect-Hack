import { useEffect, useState } from "react";
import { Menu, Moon, PanelRight, Sun } from "lucide-react";
import { Logo } from "@/components/Logo";
import { useApp } from "@/lib/app-state";
import { useTheme } from "@/lib/theme";

export function TopBar({
  onToggleSidebar,
  onTogglePanel,
}: {
  onToggleSidebar: () => void;
  onTogglePanel: () => void;
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
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface/80 px-3 backdrop-blur">
      <button
        onClick={onToggleSidebar}
        className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent lg:hidden"
        aria-label="Toggle sidebar"
      >
        <Menu size={18} />
      </button>

      <div className="flex items-center gap-2">
        <Logo />
        <span className="text-[15px] font-semibold tracking-tight">DataPilot AI</span>
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
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="truncate rounded-md px-2 py-1 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              title="Rename session"
            >
              {active.title}
            </button>
          ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <Pill dotClass="bg-primary" label={mode} />
        <Pill
          dotClass={backendOnline ? "bg-success" : backendOnline === false ? "bg-destructive" : "bg-muted-foreground"}
          label={backendOnline ? "Online" : backendOnline === false ? "Offline" : "…"}
        />
        <button
          onClick={toggle}
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          onClick={onTogglePanel}
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          aria-label="Toggle right panel"
        >
          <PanelRight size={16} />
        </button>
      </div>
    </header>
  );
}

function Pill({ dotClass, label }: { dotClass: string; label: string }) {
  return (
    <span className="hidden items-center gap-1.5 rounded-full border border-border bg-secondary px-2.5 py-1 text-[11px] font-medium text-muted-foreground sm:inline-flex">
      <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />
      {label}
    </span>
  );
}
