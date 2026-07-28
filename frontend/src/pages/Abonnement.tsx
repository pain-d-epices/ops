import { useState, type FormEvent } from "react";

import { ErreurApi } from "../api/client";
import { useAbonnement, useActiverLicence, usePlans } from "../api/hooks";
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
  const { data: abonnement, isLoading, error } = useAbonnement();
  const { data: plans } = usePlans();

  if (isLoading) return <Chargement />;
  if (error || !abonnement) {
    return <MessageErreur>Impossible de charger les informations d'abonnement.</MessageErreur>;
  }

  return (
    <div className="pile" style={{ gap: 24 }}>
      <div>
        <h1>Abonnement</h1>
        <p className="attenue">
          Plan actif : <strong>{abonnement.plan.nom_affiche}</strong>
          {abonnement.periode_fin && (
            <> · renouvellement le {formaterDate(abonnement.periode_fin)}</>
          )}
          {abonnement.licence_active && (
            <span className="badge badge-eleve" style={{ marginLeft: 10 }}>
              licence active
            </span>
          )}
        </p>
      </div>

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

      <ActivationLicence />

      <div>
        <div className="carte-titre">
          <h2>Paliers disponibles</h2>
        </div>
        <div className="grille-plans">
          {plans?.map((plan) => (
            <CartePlan key={plan.code} plan={plan} />
          ))}
        </div>
      </div>

      <div className="message message-info">
        Les paiements sont traités par Gumroad, qui gère la facturation et la TVA. Après
        votre achat, saisissez la clé de licence reçue par courriel dans le formulaire
        ci-dessus pour activer immédiatement votre plan.
      </div>
    </div>
  );
}

function CartePlan({ plan }: { plan: Plan }) {
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
        <button disabled>Palier actuel</button>
      ) : plan.url_achat ? (
        <a
          className="bouton bouton-principal"
          href={plan.url_achat}
          target="_blank"
          rel="noopener noreferrer"
        >
          Souscrire sur Gumroad
        </a>
      ) : plan.prix_mensuel_cents === 0 ? (
        <button disabled>Palier de découverte</button>
      ) : (
        <button disabled title="Aucun produit Gumroad n'est configuré pour ce palier">
          Bientôt disponible
        </button>
      )}
    </div>
  );
}

function ActivationLicence() {
  const { organisation } = useAuth();
  const [cle, setCle] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const activer = useActiverLicence();

  // Seul un administrateur peut modifier l'abonnement de l'organisation
  if (organisation?.role !== "admin") return null;

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setMessage(null);
    setErreur(null);
    try {
      const resultat = await activer.mutateAsync({ cle_licence: cle.trim() });
      setMessage(`Plan ${resultat.plan.nom_affiche} activé.`);
      setCle("");
    } catch (exception) {
      setErreur(
        exception instanceof ErreurApi
          ? exception.message
          : "Activation impossible pour le moment.",
      );
    }
  };

  return (
    <form className="carte" onSubmit={soumettre}>
      <div className="carte-titre">
        <h2>Activer une clé de licence</h2>
      </div>

      {message && <div className="message message-succes" style={{ marginBottom: 14 }}>{message}</div>}
      {erreur && <div className="message message-erreur" style={{ marginBottom: 14 }}>{erreur}</div>}

      <div className="ligne enveloppe" style={{ gap: 10, alignItems: "flex-end" }}>
        <div className="plein champ" style={{ marginBottom: 0 }}>
          <label htmlFor="cle-licence">Clé reçue après votre achat Gumroad</label>
          <input
            id="cle-licence"
            className="mono"
            value={cle}
            onChange={(e) => setCle(e.target.value)}
            placeholder="XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX"
            required
            minLength={8}
          />
        </div>
        <button
          type="submit"
          className="bouton-principal"
          disabled={activer.isPending || cle.trim().length < 8}
        >
          {activer.isPending ? <span className="chargement" /> : "Activer"}
        </button>
      </div>

      <div className="aide" style={{ marginTop: 10 }}>
        L'activation est normalement automatique après l'achat. Ce formulaire sert de
        secours si la notification de Gumroad ne nous est pas parvenue, ou si vous avez
        acheté avant de créer votre compte.
      </div>
    </form>
  );
}
