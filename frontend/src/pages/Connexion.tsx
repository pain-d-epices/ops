import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ErreurApi } from "../api/client";
import { useConnexion } from "../api/hooks";

export function PageConnexion() {
  const [email, setEmail] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [codeTotp, setCodeTotp] = useState("");
  // Le premier appel (sans code) répond 401/totp_requis si le compte a activé la
  // double authentification ; on affiche alors le second champ sans perdre la saisie.
  const [totpRequis, setTotpRequis] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [serveurInjoignable, setServeurInjoignable] = useState(false);
  const connexion = useConnexion();

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);
    setServeurInjoignable(false);
    try {
      await connexion.mutateAsync({
        email,
        mot_de_passe: motDePasse,
        code_totp: totpRequis ? codeTotp : undefined,
      });
      // Rechargement complet : le contexte d'authentification et tous les caches
      // repartent proprement avec la nouvelle session.
      window.location.href = "/";
    } catch (exception) {
      if (exception instanceof ErreurApi) {
        if (exception.estTotpRequis) {
          setTotpRequis(true);
          setErreur(null);
        } else {
          setErreur(exception.message);
        }
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
            <img className="marque-logo" src="/logo-ops.png" alt="" /> Ops
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
              disabled={totpRequis}
            />
          </div>

          {totpRequis && (
            <div className="champ">
              <label htmlFor="code-totp">Code de vérification</label>
              <input
                id="code-totp"
                type="text"
                inputMode="numeric"
                value={codeTotp}
                onChange={(e) => setCodeTotp(e.target.value)}
                autoComplete="one-time-code"
                placeholder="123456"
                required
                autoFocus
              />
              <div className="aide">
                Ouvrez votre application d'authentification, ou saisissez l'un de vos
                codes de secours.
              </div>
            </div>
          )}

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
