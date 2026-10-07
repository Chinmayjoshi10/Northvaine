import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs on :8000 (scripts/tasks.py dev); the browser only talks to Vite.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
