import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api calls go to the FastAPI backend, so the frontend never reads the data files itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
