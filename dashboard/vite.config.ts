import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/dashboard/",
  server: {
    port: 5173,
    proxy: {
      "/dashboard-api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
      "/api/sessions": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
