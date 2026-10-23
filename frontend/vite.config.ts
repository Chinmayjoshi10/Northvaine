import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The API runs on :8000 (scripts/tasks.py dev); the browser only talks to Vite.
// VITE_BASE is the sub-path of a static host, for example /Northvaine/ on Pages.
export default defineConfig(({ mode }) => ({
  base: loadEnv(mode, ".", "VITE_").VITE_BASE || "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
}));
