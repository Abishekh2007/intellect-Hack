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

/* A muted categorical set. Ordered so the first colour — the one a single-series
   bar or line chart uses — is the same restrained accent as the rest of the UI,
   and the remainder stay distinguishable without shouting. */
export function chartPalette(theme: Theme) {
  return theme === "dark"
    ? {
        text: "#a1a1aa",
        axis: "rgba(161,161,170,0.18)",
        split: "rgba(161,161,170,0.08)",
        tooltipBg: "#27272a",
        // Exported images need a plain hex: canvas cannot fill with oklch().
        exportBg: "#212326",
        series: ["#6b93d6", "#7fae9b", "#c2a267", "#b58a8a", "#8f8ab5", "#6fa3a3", "#a89a7c", "#8aa0b8"],
      }
    : {
        text: "#52525b",
        axis: "rgba(82,82,91,0.2)",
        split: "rgba(82,82,91,0.09)",
        tooltipBg: "#ffffff",
        exportBg: "#ffffff",
        series: ["#41689f", "#4f806c", "#8a6d33", "#9c5f5f", "#63608c", "#417070", "#7a6b44", "#5b7085"],
      };
}
