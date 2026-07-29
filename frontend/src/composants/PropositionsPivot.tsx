/**
 * Validation des propositions de rebond (mode supervisé).
 *
 * En mode supervisé, aucune requête n'est émise tant qu'un analyste n'a pas
 * validé : c'est ce qui distingue le rebond contrôlé d'une collecte automatique
 * en cascade.
 */

import { ErreurApi } from "../api/client";
import { useDeciderPivot, usePropositionsPivot } from "../api/hooks";
import type { PropositionPivot } from "../api/types";
import { useAuth } from "../contexts/AuthContext";
import { depuis, libelleTypeDonnee } from "../utilitaires/format";
import { Chargement, EtatVide, MessageErreur } from "./ui";

export function PropositionsPivotListe({ investigationId }: { investigationId: string }) {
  const { organisation } = useAuth();
  const { data: propositions, isLoading, error } = usePropositionsPivot(investigationId);
  const decider = useDeciderPivot(investigationId);

  if (isLoading) return <Chargement />;
  if (error) return <MessageErreur>Impossible de charger les propositions.</MessageErreur>;

  const enAttente = propositions?.filter((p) => p.statut === "en_attente") ?? [];
  const traitees = propositions?.filter((p) => p.statut !== "en_attente") ?? [];

  if (!propositions || propositions.length === 0) {
    return (
      <div className="carte">
        <EtatVide titre="Aucune piste de rebond">
          {organisation?.plan_code === "free"
            ? "Le rebond n'est pas inclus dans le plan Gratuit."
            : "Aucune information exploitable n'a encore été détectée pour rebondir."}
        </EtatVide>
      </div>
    );
  }

  return (
    <div className="pile">
      {decider.error instanceof ErreurApi && (
        <MessageErreur>{decider.error.message}</MessageErreur>
      )}

      {enAttente.length > 0 && (
        <div>
          <div className="carte-titre">
            <h3>En attente de votre validation</h3>
            <span className="badge badge-moyen">{enAttente.length}</span>
          </div>

          <div className="message message-info" style={{ marginBottom: 12 }}>
            Accepter une piste lance une nouvelle recherche et consomme un crédit de
            votre quota mensuel.
          </div>

          {enAttente.map((proposition) => (
            <div key={proposition.id} className="carte-proposition en-attente">
              <div className="plein">
                <div className="gras">{proposition.libelle}</div>
                <div className="petit attenue" style={{ marginTop: 3 }}>
                  {libelleTypeDonnee(proposition.type_pivot)} ·{" "}
                  <span className="mono">{proposition.valeur}</span> · niveau{" "}
                  {proposition.profondeur_cible} · détecté {depuis(proposition.cree_le)}
                </div>
              </div>
              <div className="ligne" style={{ gap: 8 }}>
                <button type="button"
                  className="bouton-petit bouton-succes"
                  onClick={() =>
                    decider.mutate({ propositionId: proposition.id, accepter: true })
                  }
                  disabled={decider.isPending}
                >
                  Lancer
                </button>
                <button type="button"
                  className="bouton-petit"
                  onClick={() =>
                    decider.mutate({ propositionId: proposition.id, accepter: false })
                  }
                  disabled={decider.isPending}
                >
                  Ignorer
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {traitees.length > 0 && (
        <div>
          <div className="carte-titre">
            <h3>Historique</h3>
            <span className="petit attenue">{traitees.length}</span>
          </div>
          {traitees.map((proposition) => (
            <LignePropositionTraitee key={proposition.id} proposition={proposition} />
          ))}
        </div>
      )}
    </div>
  );
}

function LignePropositionTraitee({ proposition }: { proposition: PropositionPivot }) {
  const etiquette: Record<string, { texte: string; classe: string }> = {
    acceptee: { texte: "lancée", classe: "badge-eleve" },
    automatique: { texte: "automatique", classe: "badge-accent" },
    refusee: { texte: "ignorée", classe: "badge-neutre" },
  };
  const badge = etiquette[proposition.statut] ?? {
    texte: proposition.statut,
    classe: "badge-neutre",
  };

  return (
    <div className="carte-proposition">
      <div className="plein">
        <div>{proposition.libelle}</div>
        <div className="petit attenue" style={{ marginTop: 3 }}>
          <span className="mono">{proposition.valeur}</span> · niveau{" "}
          {proposition.profondeur_cible} ·{" "}
          {proposition.decidee_le ? depuis(proposition.decidee_le) : depuis(proposition.cree_le)}
        </div>
      </div>
      <span className={`badge ${badge.classe}`}>{badge.texte}</span>
    </div>
  );
}
