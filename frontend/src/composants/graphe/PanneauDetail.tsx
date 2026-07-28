/**
 * Panneau latéral : détail du nœud sélectionné.
 *
 * Pour un compte, il affiche l'explication complète du score. C'est ce qui permet
 * à un analyste de **contester** une conclusion plutôt que de la subir : chaque
 * point attribué est justifié par une règle nommée.
 */

import { ErreurApi } from "../../api/client";
import { useDefinirVerdict, useEnrichirProfil, useProfil } from "../../api/hooks";
import type { NoeudGraphe } from "../../api/types";
import { useAuth } from "../../contexts/AuthContext";
import {
  formaterDate,
  libelleRegle,
  libelleTypeDonnee,
} from "../../utilitaires/format";
import { BadgeConfiance, Chargement, EtatVide, MessageErreur } from "../ui";

interface Proprietes {
  investigationId: string;
  noeud: NoeudGraphe | null;
  profilId: string | null;
}

export function PanneauDetail({ investigationId, noeud, profilId }: Proprietes) {
  if (!noeud) {
    return (
      <div className="panneau-detail">
        <EtatVide titre="Aucun élément sélectionné">
          Cliquez sur un nœud du graphe pour afficher son détail.
        </EtatVide>
      </div>
    );
  }

  if (!profilId) {
    return <DetailInformation noeud={noeud} />;
  }

  return <DetailProfil investigationId={investigationId} profilId={profilId} />;
}

/** Nœud d'information (e-mail, pseudonyme, lien…) : pas de score, pas de verdict. */
function DetailInformation({ noeud }: { noeud: NoeudGraphe }) {
  const estLien = noeud.type === "lien" || noeud.libelle.startsWith("http");

  return (
    <div className="panneau-detail">
      <div className="carte-titre">
        <h3>{libelleTypeDonnee(noeud.type)}</h3>
      </div>

      <div className="ligne-donnee">
        <span className="type-donnee">Valeur</span>
        <span className="valeur-donnee mono">
          {estLien ? (
            <a href={noeud.libelle} target="_blank" rel="noopener noreferrer nofollow">
              {noeud.libelle}
            </a>
          ) : (
            noeud.libelle
          )}
        </span>
      </div>

      <div className="ligne-donnee">
        <span className="type-donnee">Niveau de rebond</span>
        <span className="valeur-donnee">{noeud.profondeur}</span>
      </div>

      {Object.entries(noeud.meta ?? {}).map(([cle, valeur]) => (
        <div className="ligne-donnee" key={cle}>
          <span className="type-donnee">{libelleTypeDonnee(cle)}</span>
          <span className="valeur-donnee">{String(valeur)}</span>
        </div>
      ))}

      <div className="message message-info" style={{ marginTop: 16 }}>
        Cette information relie plusieurs comptes entre eux. Les arêtes qui en partent
        indiquent d'où elle a été extraite.
      </div>
    </div>
  );
}

function DetailProfil({
  investigationId,
  profilId,
}: {
  investigationId: string;
  profilId: string;
}) {
  const { organisation } = useAuth();
  const { data: profil, isLoading, error } = useProfil(investigationId, profilId);
  const definirVerdict = useDefinirVerdict(investigationId);
  const enrichir = useEnrichirProfil(investigationId);

  if (isLoading) return <div className="panneau-detail"><Chargement /></div>;
  if (error || !profil) {
    return (
      <div className="panneau-detail">
        <MessageErreur>Impossible de charger ce profil.</MessageErreur>
      </div>
    );
  }

  const rejete = profil.verdict_manuel === "faux_positif";
  const valide = profil.verdict_manuel === "valide";

  const basculerVerdict = (verdict: "valide" | "faux_positif") => {
    const nouveau = profil.verdict_manuel === verdict ? null : verdict;
    definirVerdict.mutate({ profilId, verdict: nouveau });
  };

  return (
    <div className="panneau-detail">
      <div className="carte-titre">
        <h3 style={{ minWidth: 0 }} className="tronque">
          {profil.site_nom}
        </h3>
        <BadgeConfiance niveau={profil.niveau} score={profil.score_confiance} />
      </div>

      <div className="ligne-donnee">
        <span className="type-donnee">Pseudonyme</span>
        <span className="valeur-donnee mono">{profil.pseudo_sur_le_site}</span>
      </div>
      <div className="ligne-donnee">
        <span className="type-donnee">Adresse</span>
        <span className="valeur-donnee">
          <a href={profil.url} target="_blank" rel="noopener noreferrer nofollow">
            {profil.url}
          </a>
        </span>
      </div>
      <div className="ligne-donnee">
        <span className="type-donnee">Niveau de rebond</span>
        <span className="valeur-donnee">{profil.profondeur}</span>
      </div>
      {profil.module_utilise && (
        <div className="ligne-donnee">
          <span className="type-donnee">Enrichi par</span>
          <span className="valeur-donnee">{profil.module_utilise}</span>
        </div>
      )}

      {/* --- Verdict manuel --- */}
      <div className="separateur" />
      <div className="ligne" style={{ gap: 8 }}>
        <button
          className={`bouton-petit ${valide ? "bouton-succes" : ""}`}
          onClick={() => basculerVerdict("valide")}
          disabled={definirVerdict.isPending}
          title="Confirmer que ce compte appartient bien à la cible"
        >
          {valide ? "✓ Validé" : "Valider"}
        </button>
        <button
          className={`bouton-petit ${rejete ? "bouton-danger" : ""}`}
          onClick={() => basculerVerdict("faux_positif")}
          disabled={definirVerdict.isPending}
          title="Marquer comme faux positif"
        >
          {rejete ? "✕ Faux positif" : "Rejeter"}
        </button>
        {!profil.enrichi && (
          <button
            className="bouton-petit"
            onClick={() => enrichir.mutate(profilId)}
            disabled={enrichir.isPending}
            title="Extraire les informations disponibles sur ce profil"
          >
            Enrichir
          </button>
        )}
      </div>

      {enrichir.error instanceof ErreurApi && (
        <div className="message message-alerte" style={{ marginTop: 10 }}>
          {enrichir.error.message}
          {enrichir.error.estFonctionnaliteIndisponible && (
            <>
              {" "}
              <a href="/abonnement">Voir les paliers</a>
            </>
          )}
        </div>
      )}

      {profil.verdict_manuel && (
        <div className="aide" style={{ marginTop: 8 }}>
          Verdict enregistré le {formaterDate(profil.verdict_le ?? null)}. Il prime sur
          le score calculé et modifie celui des autres profils.
        </div>
      )}

      {/* --- Explication du score --- */}
      <div className="separateur" />
      <h4 style={{ marginBottom: 10 }}>Pourquoi ce score ?</h4>

      {profil.signaux.length === 0 ? (
        <p className="petit attenue">
          Aucun signal enregistré. Relancez la corrélation depuis l'onglet Comptes.
        </p>
      ) : (
        profil.signaux.map((signal, index) => {
          const positif = signal.contribution_points >= 0;
          return (
            <div
              key={`${signal.regle}-${index}`}
              className={`entree-signal ${positif ? "positif" : "negatif"}`}
            >
              <div className="ligne-espacee">
                <span className="gras petit">{libelleRegle(signal.regle)}</span>
                <span
                  className={`points-signal ${positif ? "points-positifs" : "points-negatifs"}`}
                >
                  {positif ? "+" : ""}
                  {signal.contribution_points.toFixed(1)}
                </span>
              </div>
              <div className="petit attenue" style={{ marginTop: 3 }}>
                {signal.explication}
              </div>
            </div>
          );
        })
      )}

      <div className="aide" style={{ marginTop: 8 }}>
        Le score est plafonné tant que peu de signaux indépendants concordent : un
        pseudonyme identique seul ne suffit jamais à conclure.
      </div>

      {/* --- Données extraites --- */}
      {profil.donnees_extraites.length > 0 && (
        <>
          <div className="separateur" />
          <h4 style={{ marginBottom: 10 }}>
            Informations extraites
            <span className="compteur-onglet">{profil.donnees_extraites.length}</span>
          </h4>
          {profil.donnees_extraites.map((donnee) => (
            <div className="ligne-donnee" key={donnee.id}>
              <span className="type-donnee">{libelleTypeDonnee(donnee.type)}</span>
              <span className="valeur-donnee">
                {donnee.type === "lien_externe" || donnee.valeur.startsWith("http") ? (
                  <a href={donnee.valeur} target="_blank" rel="noopener noreferrer nofollow">
                    {donnee.valeur}
                  </a>
                ) : donnee.type === "avatar_url" ? (
                  <img
                    src={donnee.valeur}
                    alt="Avatar du profil"
                    style={{ maxWidth: 64, borderRadius: 6 }}
                    loading="lazy"
                  />
                ) : (
                  donnee.valeur
                )}
                {donnee.pivotee && (
                  <span className="badge badge-accent" style={{ marginLeft: 8 }}>
                    rebond effectué
                  </span>
                )}
              </span>
            </div>
          ))}
        </>
      )}

      {profil.erreur_enrichissement && (
        <div className="message message-alerte" style={{ marginTop: 14 }}>
          Enrichissement incomplet : {profil.erreur_enrichissement}
        </div>
      )}

      {!profil.enrichi && organisation?.plan_code === "free" && (
        <div className="message message-info" style={{ marginTop: 14 }}>
          L'extraction d'informations depuis les profils est réservée aux plans
          payants. <a href="/abonnement">Voir les paliers</a>
        </div>
      )}
    </div>
  );
}
