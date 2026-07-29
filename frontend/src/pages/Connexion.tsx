import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ErreurApi } from "../api/client";
import { useConnexion } from "../api/hooks";

export function PageConnexion() {
  const [email, setEmail] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [serveurInjoignable, setServeurInjoignable] = useState(false);
  const connexion = useConnexion();

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);
    setServeurInjoignable(false);
    try {
      await connexion.mutateAsync({ email, mot_de_passe: motDePasse });
      // Rechargement complet : le contexte d'authentification et tous les caches
      // repartent proprement avec la nouvelle session.
      window.location.href = "/";
    } catch (exception) {
      if (exception instanceof ErreurApi) {
        setErreur(exception.message);
        setServeurInjoignable(exception.estServeurInjoignable);
      } else {
        setErreur("Connexion impossible.");
      }
    }
  };

  return (
    <div className="page-auth">
      <div className="boite-auth">
        <div className="entete-auth">
          <div className="marque">
            <span className="marque-logo">◎</span> Searcher
          </div>
          <p>Recherche et corrélation de pseudonymes</p>
        </div>

        <form className="carte" onSubmit={soumettre}>
          <h2 style={{ marginBottom: 18 }}>Connexion</h2>

          {erreur && (
            <div className="message message-erreur" style={{ marginBottom: 16 }}>
              {erreur}
              {/* Cas fréquent en développement local : l'API n'est pas lancée.
                  On donne la marche à suivre plutôt qu'un code d'erreur. */}
              {serveurInjoignable && (
                <div className="petit" style={{ marginTop: 8, opacity: 0.85 }}>
                  Le service de recherche doit être démarré en parallèle de cette
                  interface. Voir <code>REPRISE.md</code> à la racine du projet pour les
                  commandes à lancer.
                </div>
              )}
            </div>
          )}

          <div className="champ">
            <label htmlFor="email">Adresse électronique</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              autoFocus
            />
          </div>

          <div className="champ">
            <label htmlFor="mot-de-passe">Mot de passe</label>
            <input
              id="mot-de-passe"
              type="password"
              value={motDePasse}
              onChange={(e) => setMotDePasse(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          <button
            type="submit"
            className="bouton-principal"
            style={{ width: "100%" }}
            disabled={connexion.isPending}
          >
            {connexion.isPending ? <span className="chargement" /> : "Se connecter"}
          </button>
        </form>

        <div className="bas-auth">
          Pas encore de compte ? <Link to="/inscription">Créer un compte</Link>
        </div>
      </div>
    </div>
  );
}
