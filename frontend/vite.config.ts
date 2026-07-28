import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Le frontend et l'API tournent sur des ports différents en développement.
// Le proxy les fait apparaître sur la même origine, ce qui évite les problèmes
// de CORS et permet aux cookies httpOnly d'authentification de circuler.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          // Cytoscape pèse lourd : le séparer évite de le recharger à chaque
          // modification du code applicatif.
          graphe: ["cytoscape", "cytoscape-fcose"],
        },
      },
    },
  },
});
