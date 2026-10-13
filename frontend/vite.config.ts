import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api and /health are proxied to the backend running on the host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174, // 5173 is used by another local app; docker serves the built UI on 5173
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
