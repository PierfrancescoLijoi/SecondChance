import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev server proxies /api to the Compose API, so the browser never needs CORS locally.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", rewrite: (path) => path.replace(/^\/api/, "") } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
