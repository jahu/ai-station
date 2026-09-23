import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    strictPort: true,
    proxy: {
      "/api": { target: "http://ai-station:8765", changeOrigin: false },
    },
  },
  test: { environment: "jsdom" },
});
