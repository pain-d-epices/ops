import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ErreurApi } from "../api/client";
import { useInscription } from "../api/hooks";

const LONGUEUR_MINIMALE = 12;

export function PageInscription() {
  const [parametresUrl] = useSearchParams();
  // Une invitation arrive sous la forme /inscription?invitation=JETON
  const jetonInvitation = parametresUrl.get("invitation");

  const [email, setEmail] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [nomComplet, setNomComplet] = useState("");
  const [nomOrganisation, setNomOrganisation] = useState("");
  const [cguAcceptees, setCguAcceptees] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const inscription = useInscription();

  const motDePasseTropCourt = motDePasse.length > 0 && motDePasse.length < LONGUEUR_MINIMALE;

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);

    if (motDePasse.length < LONGUEUR_MINIMALE) {
      setErreur(`Le mot de passe doit contenir au moins ${LONGUEUR_MINIMALE} caractères.`);
      return;
    }

    try {
      await inscription.mutateAsync({
        email,
        mot_de_passe: motDePasse,
        nom_complet: nomComplet || undefined,
        nom_organisation: jetonInvitation ? undefined : nomOrganisation || undefined,
        jeton_invitation: jetonInvitation || undefined,
        accepter_cgu: cguAcceptees,
      });
      window.location.href = "/";
    } catch (exception) {
      setErreur(
        exception instanceof ErreurApi
          ? exception.message
          : "Inscription impossible. Vérifiez que le serveur est démarré.",
      );
    }
  };

  return (
    <div className="page-auth">
      <div className="boite-auth">
        <div className="entete-auth">
          <div className="marque">
            <span className="marque-logo">◎</span> Searcher
          </div>
          <p>
            {jetonInvitation
              ? "Rejoindre une organisation existante"
              : "Créer un compte et une organisation"}
          </p>
        </div>

        <form className="carte" onSubmit={soumettre}>
          <h2 style={{ marginBottom: 18 }}>Créer un compte</h2>

          {erreur && (
            <div className="message message-erreur" style={{ marginBottom: 16 }}>
              {erreur}
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
            <label htmlFor="nom">Nom complet (facultatif)</label>
            <input
              id="nom"
              type="text"
              value={nomComplet}
              onChange={(e) => setNomComplet(e.target.value)}
              autoComplete="name"
            />
          </div>

          {!jetonInvitation && (
            <div className="champ">
              <label htmlFor="organisation">Nom de l'organisation</label>
              <input
                id="organisation"
                type="text"
                value={nomOrganisation}
                onChange={(e) => setNomOrganisation(e.target.value)}
                placeholder="Cabinet Dupont, Rédaction…"
              />
              <div className="aide">
                Vos investigations seront strictement cloisonnées au sein de cette
                organisation.
              </div>
            </div>
          )}

          <div className="champ">
            <label htmlFor="mot-de-passe">Mot de passe</label>
            <input
              id="mot-de-passe"
              type="password"
              value={motDePasse}
              onChange={(e) => setMotDePasse(e.target.value)}
              autoComplete="new-password"
              required
            />
            <div className="aide" style={{ color: motDePasseTropCourt ? "var(--danger)" : undefined }}>
              {LONGUEUR_MINIMALE} caractères minimum. Une phrase longue protège mieux
              qu'un mot court compliqué.
            </div>
          </div>

          {/* Acceptation obligatoire : c'est la trace du consentement au cadre légal,
              exigée avant toute recherche. */}
          <div className="encart-cgu">
            <strong>Conditions d'utilisation</strong>
            <p style={{ margin: "8px 0 0" }}>
              Searcher traite des données personnelles de tiers qui n'ont pas consenti à
              leur collecte. Son utilisation n'est licite que dans un cadre légitime :
              enquête autorisée, journalisme d'investigation, sécurité défensive, ou
              vérification avec le consentement de la personne concernée.
            </p>
            <p style={{ margin: "8px 0 0" }}>
              Sont formellement exclus le harcèlement, le pistage d'une personne privée,
              la surveillance non consentie et tout usage contraire au RGPD.
            </p>
            <p style={{ margin: "8px 0 0" }}>
              <strong>Chaque recherche est journalisée</strong> avec son auteur, son
              organisation, sa cible et son horodatage. Les résultats sont des
              estimations probabilistes, jamais des certitudes : ils doivent être
              vérifiés avant toute exploitation. Vous êtes seul responsable de la
              légalité de votre usage.
            </p>
          </div>

          <label className="case-a-cocher champ">
            <input
              type="checkbox"
              checked={cguAcceptees}
              onChange={(e) => setCguAcceptees(e.target.checked)}
              required
            />
            <span>
              J'ai lu et j'accepte les conditions d'utilisation, et je m'engage à
              n'utiliser cet outil que dans un cadre légal et autorisé.
            </span>
          </label>

          <button
            type="submit"
            className="bouton-principal"
            style={{ width: "100%" }}
            disabled={inscription.isPending || !cguAcceptees}
          >
            {inscription.isPending ? <span className="chargement" /> : "Créer mon compte"}
          </button>
        </form>

        <div className="bas-auth">
          Déjà un compte ? <Link to="/connexion">Se connecter</Link>
        </div>
      </div>
    </div>
  );
}
