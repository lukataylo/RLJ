// Calm Command theme: dark (charcoal) ⇄ light (cream), persisted to localStorage
// and applied to <html data-theme>. A "pulsego-theme" CustomEvent lets non-React
// consumers (e.g. the MapView basemap) react to changes without prop drilling.

export type Theme = "dark" | "light";

const KEY = "pulsego_theme";
const EVENT = "pulsego-theme";

export function getTheme(): Theme {
  // A ?theme= query param wins (handy for shareable links + screenshots).
  try {
    const q = new URLSearchParams(window.location.search).get("theme");
    if (q === "light" || q === "dark") return q;
  } catch {
    /* no window.location */
  }
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    /* storage unavailable */
  }
  return "dark"; // command center defaults to the charcoal base
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* ignore */
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#f6ece0" : "#0e0d0c");
  window.dispatchEvent(new CustomEvent<Theme>(EVENT, { detail: theme }));
}

/** Apply the persisted theme on boot (call before first paint to avoid a flash). */
export function initTheme(): Theme {
  const t = getTheme();
  document.documentElement.setAttribute("data-theme", t);
  return t;
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "light" ? "dark" : "light";
  applyTheme(next);
  return next;
}

/** Subscribe to theme changes; returns an unsubscribe fn. */
export function onThemeChange(cb: (theme: Theme) => void): () => void {
  const handler = (e: Event) => cb((e as CustomEvent<Theme>).detail);
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}
