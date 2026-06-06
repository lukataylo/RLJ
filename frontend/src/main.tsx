import React from "react";
import ReactDOM from "react-dom/client";
// Mission-control type system (offline-safe, bundled via @fontsource):
//   JetBrains Mono — all labels / data / numbers (terminal aesthetic)
//   Inter          — clean sans for entity headings
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import "@fontsource/jetbrains-mono/700.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
// Poppins — display face for headings/numerals across the brand: the public
// surfaces (landing + login) and the Calm Command app shell.
import "@fontsource/poppins/500.css";
import "@fontsource/poppins/600.css";
import "@fontsource/poppins/700.css";
import "@fontsource/poppins/800.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "mapbox-gl/dist/mapbox-gl.css";
import "./index.css";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import { initTheme } from "./lib/theme";

// Apply the persisted dark/light theme before first paint (no flash).
initTheme();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        {/* Command center — dev runs auth-off so /app is always reachable; a
            present token is validated via /auth/me on load (see App.tsx). */}
        <Route path="/app/*" element={<App />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
