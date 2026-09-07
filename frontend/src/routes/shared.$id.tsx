import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { api, type ChartSpec, type DashboardItem } from "@/lib/api";
import { ChartView, DiagramView } from "@/components/artifacts";
import { PinnedBody } from "@/components/RightPanel";
import { Logo } from "@/components/Logo";
import { ThemeProvider } from "@/lib/theme";

export const Route = createFileRoute("/shared/$id")({
  head: () => ({
    meta: [
      { title: "Shared view — DataPilot AI" },
      {
        name: "description",
        content: "A chart, diagram or dashboard shared from DataPilot AI.",
      },
      { property: "og:title", content: "Shared view — DataPilot AI" },
      {
        property: "og:description",
        content: "A chart, diagram or dashboard shared from DataPilot AI.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: SharedView,
});

function SharedView() {
  const { id } = Route.useParams();
  const [data, setData] = useState<{
    kind: string;
    title: string;
    payload: Record<string, unknown>;
  } | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .shared(id)
      .then((r) => !cancelled && setData(r))
      .catch(() => !cancelled && setError(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <ThemeProvider>
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface/80 px-4">
          <Logo />
          <span className="text-[15px] font-semibold tracking-tight">DataPilot AI</span>
          <Link to="/" className="ml-auto text-xs text-primary hover:underline">
            Back to app
          </Link>
        </header>
        <main className="scroll-thin flex-1 p-4">
          <div className="mx-auto w-full max-w-4xl space-y-4">
            {loading && <div className="h-64 animate-pulse rounded-xl bg-secondary" />}
            {error && (
              <div className="panel px-4 py-10 text-center text-sm text-muted-foreground">
                This share link is invalid or expired.
              </div>
            )}
            {data && (
              <>
                <h1 className="text-xl font-semibold tracking-tight">{data.title}</h1>
                {data.kind === "chart" && (
                  <div className="panel p-2">
                    <ChartView spec={data.payload as unknown as ChartSpec} height={380} />
                  </div>
                )}
                {data.kind === "diagram" && (
                  <div className="panel">
                    <DiagramView
                      code={String((data.payload as { mermaid?: string }).mermaid ?? "")}
                    />
                  </div>
                )}
                {data.kind === "dashboard" && (
                  <div className="grid gap-3 md:grid-cols-2">
                    {(
                      ((data.payload as { items?: DashboardItem[] }).items ?? []) as DashboardItem[]
                    ).map((item) => (
                      <div key={item.id} className="panel overflow-hidden">
                        <div className="border-b border-border px-3 py-2 text-xs font-semibold">
                          {item.title}
                        </div>
                        <PinnedBody item={item} />
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </main>
      </div>
    </ThemeProvider>
  );
}
