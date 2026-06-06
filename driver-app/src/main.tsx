import React from "react";
import ReactDOM from "react-dom/client";
// Sci-fi type system (offline-safe, bundled via @fontsource), matching the
// PulseGo ops console: Orbitron for display/big numbers, Rajdhani for body/labels.
import "@fontsource/orbitron/latin-500.css";
import "@fontsource/orbitron/latin-700.css";
import "@fontsource/orbitron/latin-800.css";
import "@fontsource/orbitron/latin-900.css";
import "@fontsource/rajdhani/latin-300.css";
import "@fontsource/rajdhani/latin-400.css";
import "@fontsource/rajdhani/latin-500.css";
import "@fontsource/rajdhani/latin-600.css";
import "@fontsource/rajdhani/latin-700.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "mapbox-gl/dist/mapbox-gl.css";
import "./index.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Register the offline-shell service worker (PWA). Non-fatal if unsupported.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* SW optional — app works without it */
    });
  });
}
