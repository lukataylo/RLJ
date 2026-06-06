// Dark/light theme switch for the command center (Calm Command). Two small
// segmented buttons (sun / moon); the active mode is the Pulse-Red pill.

import { useEffect, useState } from "react";
import { applyTheme, getTheme, type Theme } from "../lib/theme";

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => getTheme());

  // Keep in sync if the theme is changed elsewhere.
  useEffect(() => {
    setTheme(getTheme());
  }, []);

  const set = (t: Theme) => {
    applyTheme(t);
    setTheme(t);
  };

  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      <button
        type="button"
        className={theme === "light" ? "on" : ""}
        data-testid="theme-light"
        aria-pressed={theme === "light"}
        aria-label="Light mode"
        title="Light mode"
        onClick={() => set("light")}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="4" />
          <path
            d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"
            strokeLinecap="round"
          />
        </svg>
      </button>
      <button
        type="button"
        className={theme === "dark" ? "on" : ""}
        data-testid="theme-dark"
        aria-pressed={theme === "dark"}
        aria-label="Dark mode"
        title="Dark mode"
        onClick={() => set("dark")}
      >
        <svg viewBox="0 0 24 24" fill="currentColor">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
        </svg>
      </button>
    </div>
  );
}
