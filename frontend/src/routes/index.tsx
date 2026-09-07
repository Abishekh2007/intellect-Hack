import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Toaster } from "@/components/ui/sonner";
import { AppProvider } from "@/lib/app-state";
import { ThemeProvider } from "@/lib/theme";
import { TopBar } from "@/components/TopBar";
import { Sidebar } from "@/components/Sidebar";
import { Chat } from "@/components/Chat";
import { RightPanel } from "@/components/RightPanel";
import { CommandPalette } from "@/components/CommandPalette";

type PanelTab = "schema" | "database" | "dashboard" | "history";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "DataPilot AI — Chat with your database" },
      {
        name: "description",
        content:
          "Ask natural-language questions about your database. DataPilot AI writes read-only SQL and returns tables, charts and ER diagrams.",
      },
      { property: "og:title", content: "DataPilot AI — Chat with your database" },
      {
        property: "og:description",
        content: "Natural-language SQL, instant charts, ER diagrams and a pinnable dashboard.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

function Index() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [panelTab, setPanelTab] = useState<PanelTab>("schema");

  // Cmd/Ctrl+\ toggles the panel from anywhere, including mid-sentence in the
  // composer — the palette advertises the shortcut, so it has to work.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "\\" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setPanelOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const openTab = (tab: PanelTab) => {
    setPanelTab(tab);
    setPanelOpen(true);
  };

  return (
    <ThemeProvider>
      <AppProvider>
        <div className="relative flex h-screen flex-col overflow-hidden">
          <TopBar
            onToggleSidebar={() => setSidebarOpen((v) => !v)}
            onTogglePanel={() => setPanelOpen((v) => !v)}
            panelOpen={panelOpen}
          />
          <div className="flex min-h-0 flex-1">
            <div className="hidden lg:flex">
              <Sidebar />
            </div>

            {sidebarOpen && (
              <div className="fixed inset-0 z-40 lg:hidden">
                <button
                  aria-label="Close menu"
                  className="absolute inset-0 bg-background/80"
                  onClick={() => setSidebarOpen(false)}
                />
                <div className="absolute inset-y-0 left-0 z-50 shadow-2xl">
                  <Sidebar onNavigate={() => setSidebarOpen(false)} />
                </div>
              </div>
            )}

            <Chat />

            {panelOpen && (
              <>
                <div className="hidden lg:flex">
                  <RightPanel
                    onClose={() => setPanelOpen(false)}
                    tab={panelTab}
                    onTabChange={setPanelTab}
                  />
                </div>
                <div className="fixed inset-x-0 bottom-0 top-14 z-40 bg-background lg:hidden">
                  <RightPanel
                    onClose={() => setPanelOpen(false)}
                    tab={panelTab}
                    onTabChange={setPanelTab}
                  />
                </div>
              </>
            )}
          </div>
        </div>
        <CommandPalette onTogglePanel={() => setPanelOpen((v) => !v)} onOpenTab={openTab} />
        <Toaster position="bottom-right" richColors closeButton />
      </AppProvider>
    </ThemeProvider>
  );
}
