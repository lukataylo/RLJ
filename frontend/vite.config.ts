import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server runs on :5173 and talks to the orchestrator at :8000 (REST + WS).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
});
