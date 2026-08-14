import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

type Theme = "dark" | "light";

const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({
  theme: "dark",
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    const saved = window.localStorage.getItem("datapilot-theme");
    if (saved === "light" || saved === "dark") setTheme(saved);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    window.localStorage.setItem("datapilot-theme", theme);
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);

  return <ThemeCtx.Provider value={{ theme, toggle }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);

export function chartPalette(theme: Theme) {
  return theme === "dark"
    ? {
        text: "#cbd5e1",
        axis: "rgba(148,163,184,0.25)",
        split: "rgba(148,163,184,0.12)",
        tooltipBg: "#111c33",
        series: ["#6366f1", "#8b5cf6", "#14b8a6", "#38bdf8", "#f59e0b", "#f43f5e", "#a78bfa", "#22d3ee"],
      }
    : {
        text: "#334155",
        axis: "rgba(51,65,85,0.25)",
        split: "rgba(51,65,85,0.1)",
        tooltipBg: "#ffffff",
        series: ["#6366f1", "#8b5cf6", "#0d9488", "#0284c7", "#d97706", "#e11d48", "#7c3aed", "#0891b2"],
      };
}
