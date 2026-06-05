import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server runs on :5174 (frontend ops console owns :5173) and talks to the
// orchestrator at VITE_ORCHESTRATOR_URL (default http://localhost:8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    host: true,
  },
});
