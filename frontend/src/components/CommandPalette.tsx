import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Boxes,
  Database,
  MessageSquare,
  Moon,
  PanelRight,
  Plus,
  Sun,
  Table2,
  TrendingUp,
  Workflow,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import { useApp } from "@/lib/app-state";
import { useTheme } from "@/lib/theme";
import { relativeTime } from "@/lib/api";

/* Suggested questions live here as well as in the empty state, so they stay
   reachable once a conversation has started and the empty state is gone. */
const ASK_ACTIONS: { label: string; prompt: string; icon: typeof BarChart3 }[] = [
  { label: "Top 5 products by revenue", prompt: "Top 5 products by revenue", icon: BarChart3 },
  { label: "Monthly revenue trend", prompt: "Monthly revenue trend", icon: TrendingUp },
  { label: "Low stock products", prompt: "Low stock products", icon: Boxes },
  { label: "Show the ER diagram", prompt: "Show me the ER diagram", icon: Workflow },
];

export function CommandPalette({
  onTogglePanel,
  onOpenTab,
}: {
  onTogglePanel: () => void;
  onOpenTab: (tab: "schema" | "database" | "dashboard" | "history") => void;
}) {
  const [open, setOpen] = useState(false);
  const { sessions, openSession, newChat, send, isStreaming } = useApp();
  const { theme, toggle } = useTheme();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Cmd/Ctrl+K anywhere, and "/" when the user is not already typing.
      const typing =
        e.target instanceof HTMLElement &&
        (e.target.tagName === "INPUT" ||
          e.target.tagName === "TEXTAREA" ||
          e.target.isContentEditable);
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "/" && !typing && !open) {
        e.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  /* Close first, then act. Running the action while the dialog is still
     mounted lets Radix restore focus to the trigger afterwards and steal it
     back from whatever the action focused. */
  const run = (fn: () => void) => {
    setOpen(false);
    requestAnimationFrame(fn);
  };

  const focusComposer = () =>
    document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')?.focus();

  const recent = useMemo(() => sessions.slice(0, 8), [sessions]);

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Search chats, ask a question, or run a command…" />
      <CommandList>
        <CommandEmpty>No matches.</CommandEmpty>

        <CommandGroup heading="Actions">
          <CommandItem
            onSelect={() =>
              run(() => {
                newChat();
                focusComposer();
              })
            }
          >
            <Plus size={14} className="mr-2 text-primary" />
            New chat
            <CommandShortcut>⌘⇧O</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => run(focusComposer)}>
            <MessageSquare size={14} className="mr-2 text-primary" />
            Focus the message box
          </CommandItem>
          <CommandItem onSelect={() => run(onTogglePanel)}>
            <PanelRight size={14} className="mr-2 text-primary" />
            Toggle the side panel
            <CommandShortcut>⌘\</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => run(toggle)}>
            {theme === "dark" ? (
              <Sun size={14} className="mr-2 text-primary" />
            ) : (
              <Moon size={14} className="mr-2 text-primary" />
            )}
            Switch to {theme === "dark" ? "light" : "dark"} theme
          </CommandItem>
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Go to">
          <CommandItem onSelect={() => run(() => onOpenTab("schema"))}>
            <Table2 size={14} className="mr-2 text-muted-foreground" />
            Schema
          </CommandItem>
          <CommandItem onSelect={() => run(() => onOpenTab("database"))}>
            <Database size={14} className="mr-2 text-muted-foreground" />
            Data — upload, import, run SQL
          </CommandItem>
          <CommandItem onSelect={() => run(() => onOpenTab("dashboard"))}>
            <BarChart3 size={14} className="mr-2 text-muted-foreground" />
            Pinned dashboard
          </CommandItem>
          <CommandItem onSelect={() => run(() => onOpenTab("history"))}>
            <Workflow size={14} className="mr-2 text-muted-foreground" />
            Query history
          </CommandItem>
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Ask">
          {ASK_ACTIONS.map(({ label, prompt, icon: Icon }) => (
            <CommandItem
              key={prompt}
              disabled={isStreaming}
              onSelect={() => run(() => send(prompt))}
            >
              <Icon size={14} className="mr-2 text-muted-foreground" />
              {label}
            </CommandItem>
          ))}
        </CommandGroup>

        {recent.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Recent chats">
              {recent.map((s) => (
                <CommandItem
                  key={s.id}
                  /* cmdk matches on `value`, so the title has to be it —
                     otherwise every row would match on its id instead. */
                  value={`${s.title || "Untitled"} ${s.id}`}
                  onSelect={() => run(() => openSession(s.id))}
                >
                  <MessageSquare size={14} className="mr-2 text-muted-foreground" />
                  <span className="truncate">{s.title || "Untitled"}</span>
                  <CommandShortcut>{relativeTime(s.updated_at ?? s.created_at)}</CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
