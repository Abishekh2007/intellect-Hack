import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Toaster } from "@/components/ui/sonner";
import { AppProvider } from "@/lib/app-state";
import { ThemeProvider } from "@/lib/theme";
import { TopBar } from "@/components/TopBar";
import { Sidebar } from "@/components/Sidebar";
import { Chat } from "@/components/Chat";
import { RightPanel } from "@/components/RightPanel";

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
  const [panelOpen, setPanelOpen] = useState(false);

  return (
    <ThemeProvider>
      <AppProvider>
        <div className="flex h-screen flex-col overflow-hidden bg-background">
          <TopBar
            onToggleSidebar={() => setSidebarOpen((v) => !v)}
            onTogglePanel={() => setPanelOpen((v) => !v)}
          />
          <div className="flex min-h-0 flex-1">
            <div className="hidden lg:flex">
              <Sidebar />
            </div>

            {sidebarOpen && (
              <div className="fixed inset-0 z-40 lg:hidden">
                <button
                  aria-label="Close menu"
                  className="absolute inset-0 bg-background/70 backdrop-blur-sm"
                  onClick={() => setSidebarOpen(false)}
                />
                <div className="absolute inset-y-0 left-0 z-50 bg-background">
                  <Sidebar onNavigate={() => setSidebarOpen(false)} />
                </div>
              </div>
            )}

            <Chat />

            {panelOpen && (
              <>
                <div className="hidden lg:flex">
                  <RightPanel onClose={() => setPanelOpen(false)} />
                </div>
                <div className="fixed inset-x-0 bottom-0 top-14 z-40 bg-background lg:hidden">
                  <RightPanel onClose={() => setPanelOpen(false)} />
                </div>
              </>
            )}
          </div>
        </div>
        <Toaster position="bottom-right" />
      </AppProvider>
    </ThemeProvider>
  );
}
