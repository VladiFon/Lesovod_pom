import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend (FastAPI, Этап 1/2) слушает :8000 — на деве проксируем /api
// туда же, чтобы фронтенд обращался к относительным путям и в проде
// (за Caddy/nginx, см. Этап 8), и в разработке не упирался в CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
