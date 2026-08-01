import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Le frontend et l'API tournent sur des ports différents en développement.
// Le proxy les fait apparaître sur la même origine, ce qui évite les problèmes
// de CORS et permet aux cookies httpOnly d'authentification de circuler.
export default defineConfig({
  plugins: [react()],
  // Dépendances pré-compilées au démarrage plutôt que découvertes en cours de
  // route : sans cette liste, Vite les trouve pendant le premier chargement et
  // recharge la page une fois la compilation faite, ce qui la fait paraître lente.
  optimizeDeps: {
    include: [
      "react",
      "react-dom",
      "react-dom/client",
      "react-router-dom",
      "@tanstack/react-query",
      "cytoscape",
      "cytoscape-fcose",
    ],
  },
  server: {
    port: 5183,
    // Traduit ces fichiers dès le démarrage, sans attendre la première visite.
    warmup: {
      clientFiles: [
        "./index.html",
        "./src/main.tsx",
        "./src/App.tsx",
        "./src/pages/Accueil.tsx",
      ],
    },
    proxy: {
      "/api": {
        target: "http://localhost:8010",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8010",
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
