import { Navigate, Route, Routes } from "react-router-dom";

import { MiseEnPage } from "./composants/MiseEnPage";
import { useAuth } from "./contexts/AuthContext";
import { PageAbonnement } from "./pages/Abonnement";
import { PageAccueil } from "./pages/Accueil";
import { PageCompte } from "./pages/Compte";
import { PageConnexion } from "./pages/Connexion";
import { PageInscription } from "./pages/Inscription";
import { PageInvestigation } from "./pages/Investigation";
import { PageOrganisation } from "./pages/Organisation";

export function Application() {
  const { authentifie, chargement } = useAuth();

  if (chargement) {
    return (
      <div className="page-auth">
        <div className="centre">
          <span className="chargement" />
          <p className="attenue" style={{ marginTop: 14 }}>
            Chargement…
          </p>
        </div>
      </div>
    );
  }

  if (!authentifie) {
    return (
      <Routes>
        <Route path="/connexion" element={<PageConnexion />} />
        <Route path="/inscription" element={<PageInscription />} />
        {/* Toute autre adresse renvoie vers la connexion : aucune page de
            l'application n'est accessible sans authentification. */}
        <Route path="*" element={<Navigate to="/connexion" replace />} />
      </Routes>
    );
  }

  return (
    <MiseEnPage>
      <Routes>
        <Route path="/" element={<PageAccueil />} />
        <Route path="/investigations/:investigationId" element={<PageInvestigation />} />
        <Route path="/abonnement" element={<PageAbonnement />} />
        <Route path="/organisation" element={<PageOrganisation />} />
        <Route path="/compte" element={<PageCompte />} />
        <Route path="/connexion" element={<Navigate to="/" replace />} />
        <Route path="/inscription" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </MiseEnPage>
  );
}
