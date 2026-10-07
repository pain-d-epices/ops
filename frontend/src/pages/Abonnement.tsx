import { useState } from "react";

import { ErreurApi } from "../api/client";
import {
  useAbonnement,
  useDemarrerPaiement,
  useOuvrirPortail,
  usePlans,
} from "../api/hooks";
import type { Plan } from "../api/types";
import { BarreProgression, Chargement, MessageErreur } from "../composants/ui";
import { useAuth } from "../contexts/AuthContext";
import {
  formaterDate,
  formaterNombre,
  formaterPrix,
  libelleFonctionnalite,
} from "../utilitaires/format";

const LIBELLES_QUOTA: Record<string, string> = {
  recherches: "Recherches",
  enrichissements: "Enrichissements",
  pivots: "Rebonds",
  exports: "Exports",
};

export function PageAbonnement() {
  const { organisation } = useAuth();
  const { data: abonnement, isLoading, error } = useAbonnement();
  const { data: plans } = usePlans();
  const demarrerPaiement = useDemarrerPaiement();
  const ouvrirPortail = useOuvrirPortail();
  const [erreurPaiement, setErreurPaiement] = useState<string | null>(null);

  const estAdmin = organisation?.role === "admin";

  if (isLoading) return <Chargement />;
  if (error || !abonnement) {
    return <MessageErreur>Impossible de charger les informations d'abonnement.</MessageErreur>;
  }

  const souscrire = async (codePlan: string) => {
    setErreurPaiement(null);
    try {
      const { url } = await demarrerPaiement.mutateAsync({ code_plan: codePlan });
      // Redirection pleine page vers Stripe Checkout : le paiement se fait sur son
      // domaine, jamais dans un cadre de notre interface.
      window.location.href = url;
    } catch (exception) {
      setErreurPaiement(
        exception instanceof ErreurApi ? exception.message : "Paiement impossible pour le moment.",
      );
    }
  };

  const gererAbonnement = async () => {
    setErreurPaiement(null);
    try {
      const { url } = await ouvrirPortail.mutateAsync();
      window.location.href = url;
    } catch (exception) {
      setErreurPaiement(
        exception instanceof ErreurApi ? exception.message : "Portail indisponible pour le moment.",
      );
    }
  };

  return (
    <div className="pile" style={{ gap: 24 }}>
      <div>
        <h1>{abonnement.mode_autoheberge ? "Usage" : "Abonnement"}</h1>
        <p className="attenue">
          {abonnement.mode_autoheberge ? (
            <>Instance autohébergée : aucune limite de volume, aucun abonnement.</>
          ) : (
            <>Plan actif : <strong>{abonnement.plan.nom_affiche}</strong></>
          )}
          {!abonnement.mode_autoheberge && abonnement.periode_fin && (
            <>
              {" "}
              · {abonnement.renouvellement_automatique ? "renouvellement" : "expiration"} le{" "}
              {formaterDate(abonnement.periode_fin)}
            </>
          )}
        </p>
      </div>

      {erreurPaiement && <div className="message message-erreur">{erreurPaiement}</div>}
      {abonnement.message_limite && (
        <div className="message message-alerte">{abonnement.message_limite}</div>
      )}

      <div className="carte">
        <div className="carte-titre">
          <h2>Consommation du mois</h2>
        </div>

        {abonnement.quotas.map((quota) => (
          <div className="ligne-quota" key={quota.nom}>
            <div className="entete-quota">
              <span>{LIBELLES_QUOTA[quota.nom] ?? quota.nom}</span>
              <span className="mono attenue">
                {formaterNombre(quota.consomme)}
                {quota.limite !== null ? ` / ${formaterNombre(quota.limite)}` : " (illimité)"}
              </span>
            </div>
            <BarreProgression valeur={quota.pourcentage} variante="quota" />
          </div>
        ))}

        <div className="aide" style={{ marginTop: 14 }}>
          Les compteurs sont remis à zéro au début de chaque mois calendaire. Un rebond
          consomme un crédit de recherche.
        </div>
      </div>

      {estAdmin && abonnement.stripe_lie && (
        <div className="carte">
          <div className="carte-titre">
            <h2>Gérer mon abonnement</h2>
          </div>
          <p className="attenue" style={{ marginBottom: 14 }}>
            Moyen de paiement, factures, changement de palier ou résiliation : tout se
            passe sur le portail sécurisé de Stripe, prestataire de paiement de cette
            instance.
          </p>
          <button
            type="button"
            className="bouton-principal"
            onClick={gererAbonnement}
            disabled={ouvrirPortail.isPending}
          >
            {ouvrirPortail.isPending ? <span className="chargement" /> : "Ouvrir le portail de facturation"}
          </button>
        </div>
      )}

      {/* Un seul palier renvoyé = installation autohébergée : rien à comparer. */}
      {(plans?.length ?? 0) > 1 && (
      <div>
        <div className="carte-titre">
          <h2>Paliers disponibles</h2>
        </div>
        <div className="grille-plans">
          {plans?.map((plan) => (
            <CartePlan
              key={plan.code}
              plan={plan}
              estAdmin={estAdmin}
              enCours={demarrerPaiement.isPending}
              onSouscrire={() => souscrire(plan.code)}
            />
          ))}
        </div>
      </div>
      )}

      {(plans?.length ?? 0) > 1 && (
        <div className="message message-info">
          Les paiements sont traités par Stripe, qui gère la facturation et la TVA.
          L'abonnement s'active automatiquement dès la confirmation du paiement.
        </div>
      )}
    </div>
  );
}

function CartePlan({
  plan,
  estAdmin,
  enCours,
  onSouscrire,
}: {
  plan: Plan;
  estAdmin: boolean;
  enCours: boolean;
  onSouscrire: () => void;
}) {
  const fonctionnalitesConnues = [
    "modules",
    "pivot",
    "pivot_automatique",
    "export_csv",
    "export_pdf",
    "api",
    "multi_utilisateurs",
  ];

  return (
    <div className={`carte-plan ${plan.est_plan_actuel ? "plan-actuel" : ""}`}>
      <div className="ligne-espacee">
        <h3 style={{ margin: 0 }}>{plan.nom_affiche}</h3>
        {plan.est_plan_actuel && <span className="badge badge-accent">actuel</span>}
      </div>

      <div className="prix-plan">
        {formaterPrix(plan.prix_mensuel_cents)}
        {plan.prix_mensuel_cents > 0 && <span> / mois</span>}
      </div>

      <ul className="liste-fonctionnalites">
        <li>
          <span className="incluse">✓</span>
          {formaterNombre(plan.quota_recherches_mois)} recherches / mois
        </li>
        <li>
          <span className={plan.quota_enrichissements_mois > 0 ? "incluse" : "absente"}>
            {plan.quota_enrichissements_mois > 0 ? "✓" : "—"}
          </span>
          {plan.quota_enrichissements_mois > 0
            ? `${formaterNombre(plan.quota_enrichissements_mois)} enrichissements / mois`
            : "Pas d'enrichissement"}
        </li>
        <li>
          <span className={plan.profondeur_pivot_max > 0 ? "incluse" : "absente"}>
            {plan.profondeur_pivot_max > 0 ? "✓" : "—"}
          </span>
          {plan.profondeur_pivot_max > 0
            ? `Rebond sur ${plan.profondeur_pivot_max} niveau${plan.profondeur_pivot_max > 1 ? "x" : ""}`
            : "Pas de rebond"}
        </li>
        <li>
          <span className="incluse">✓</span>
          {plan.quota_utilisateurs} utilisateur{plan.quota_utilisateurs > 1 ? "s" : ""}
        </li>

        {fonctionnalitesConnues
          .filter((code) => !["modules", "pivot"].includes(code))
          .map((code) => {
            const incluse = plan.fonctionnalites.includes(code);
            if (!incluse) return null;
            return (
              <li key={code}>
                <span className="incluse">✓</span>
                {libelleFonctionnalite(code)}
              </li>
            );
          })}
      </ul>

      {plan.est_plan_actuel ? (
        <button type="button" disabled>Palier actuel</button>
      ) : plan.prix_mensuel_cents === 0 ? (
        <button type="button" disabled>Palier de découverte</button>
      ) : estAdmin ? (
        <button type="button" className="bouton-principal" onClick={onSouscrire} disabled={enCours}>
          {enCours ? <span className="chargement" /> : "Souscrire"}
        </button>
      ) : (
        <button type="button" disabled title="Seul un administrateur peut changer de palier">
          Souscrire
        </button>
      )}
    </div>
  );
}
