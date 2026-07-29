import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useDeconnexion } from "../api/hooks";
import { useAuth } from "../contexts/AuthContext";

export function MiseEnPage({ children }: { children: ReactNode }) {
  const { utilisateur, organisation, changerOrganisation } = useAuth();
  const deconnexion = useDeconnexion();
  const naviguer = useNavigate();

  const seDeconnecter = async () => {
    await deconnexion.mutateAsync().catch(() => undefined);
    naviguer("/connexion", { replace: true });
    window.location.reload();
  };

  const organisations = utilisateur?.organisations ?? [];

  return (
    <div className="application">
      <header className="entete">
        <div className="ligne" style={{ gap: 26 }}>
          <NavLink to="/" className="marque">
            <span className="marque-logo">◎</span> Searcher
          </NavLink>
          <nav className="navigation">
            <NavLink to="/" end className={({ isActive }) => (isActive ? "actif" : "")}>
              Investigations
            </NavLink>
            <NavLink to="/abonnement" className={({ isActive }) => (isActive ? "actif" : "")}>
              Abonnement
            </NavLink>
            <NavLink to="/organisation" className={({ isActive }) => (isActive ? "actif" : "")}>
              Organisation
            </NavLink>
          </nav>
        </div>

        <div className="zone-compte">
          {organisation && (
            <span className="badge badge-accent" title="Plan actif de l'organisation">
              {organisation.plan_nom}
            </span>
          )}

          {/* N'afficher le sélecteur que s'il y a un choix à faire */}
          {organisations.length > 1 && (
            <select
              className="selecteur-organisation"
              value={organisation?.id ?? ""}
              onChange={(evenement) => changerOrganisation(evenement.target.value)}
              aria-label="Organisation active"
            >
              {organisations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.nom}
                </option>
              ))}
            </select>
          )}

          <span className="petit attenue tronque" style={{ maxWidth: 190 }}>
            {utilisateur?.email}
          </span>
          <button type="button" className="bouton-discret" onClick={seDeconnecter}>
            Déconnexion
          </button>
        </div>
      </header>

      {/* Rappel permanent du cadre d'usage : l'outil traite des données
          personnelles de tiers, et chaque recherche est tracée. */}
      <div className="bandeau-legal">
        Usage réservé aux investigations autorisées et légales. Chaque recherche est
        journalisée avec son auteur et sa cible.
      </div>

      <main className="contenu">{children}</main>
    </div>
  );
}
