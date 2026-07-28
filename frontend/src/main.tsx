import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { Application } from "./App";
import { ErreurApi } from "./api/client";
import { FournisseurAuth } from "./contexts/AuthContext";
import "./styles/global.css";
import "./styles/layout.css";

const clientRequetes = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (nombreEchecs, erreur) => {
        // Inutile de réessayer une requête refusée : ni une session expirée ni un
        // droit manquant ne se résolvent en insistant.
        if (erreur instanceof ErreurApi) {
          if ([401, 403, 404, 429].includes(erreur.statut)) return false;
        }
        return nombreEchecs < 2;
      },
    },
  },
});

ReactDOM.createRoot(document.getElementById("racine")!).render(
  <React.StrictMode>
    <QueryClientProvider client={clientRequetes}>
      <BrowserRouter>
        <FournisseurAuth>
          <Application />
        </FournisseurAuth>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
