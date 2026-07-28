/** Petits composants d'affichage réutilisés dans toute l'application. */

import type { ReactNode } from "react";

import type { NiveauConfiance, StatutInvestigation } from "../api/types";
import { LIBELLES_NIVEAU, LIBELLES_STATUT } from "../utilitaires/format";

export function BadgeConfiance({
  niveau,
  score,
}: {
  niveau: NiveauConfiance;
  score?: number;
}) {
  return (
    <span className={`badge badge-${niveau}`} title={LIBELLES_NIVEAU[niveau]}>
      {score !== undefined ? `${score} %` : LIBELLES_NIVEAU[niveau]}
    </span>
  );
}

export function BadgeStatut({ statut }: { statut: StatutInvestigation }) {
  const classe =
    statut === "terminee"
      ? "badge-eleve"
      : statut === "erreur" || statut === "annulee"
        ? "badge-danger"
        : statut === "en_cours"
          ? "badge-accent"
          : "badge-neutre";
  return <span className={`badge ${classe}`}>{LIBELLES_STATUT[statut]}</span>;
}

export function BarreProgression({
  valeur,
  variante,
}: {
  valeur: number;
  variante?: "quota";
}) {
  const borne = Math.max(0, Math.min(100, valeur));
  const classes = ["barre-progression"];
  if (variante === "quota") {
    classes.push("barre-quota");
    if (borne >= 100) classes.push("pleine");
    else if (borne >= 80) classes.push("alerte");
  }
  return (
    <div
      className={classes.join(" ")}
      role="progressbar"
      aria-valuenow={borne}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div style={{ width: `${borne}%` }} />
    </div>
  );
}

export function MessageErreur({ children }: { children: ReactNode }) {
  return <div className="message message-erreur">{children}</div>;
}

export function EtatVide({
  titre,
  children,
}: {
  titre: string;
  children?: ReactNode;
}) {
  return (
    <div className="vide">
      <div className="gras" style={{ marginBottom: 6, color: "var(--texte-attenue)" }}>
        {titre}
      </div>
      {children && <div className="petit">{children}</div>}
    </div>
  );
}

export function Chargement({ texte = "Chargement…" }: { texte?: string }) {
  return (
    <div className="vide">
      <span className="chargement" />
      <div className="petit" style={{ marginTop: 10 }}>
        {texte}
      </div>
    </div>
  );
}

/** Indicateur de connexion au flux temps réel. */
export function IndicateurTempsReel({ connecte }: { connecte: boolean }) {
  return (
    <span className="ligne petit attenue" style={{ gap: 6 }}>
      <span className={`pastille ${connecte ? "pastille-active" : "pastille-inactive"}`} />
      {connecte ? "Suivi en direct" : "Suivi différé"}
    </span>
  );
}

/**
 * Encart affiché lorsqu'une fonctionnalité n'est pas incluse dans le plan.
 * Il explique ce qui manque et où souscrire, plutôt que de masquer le bouton
 * sans explication.
 */
export function EncartPlanRequis({
  fonctionnalite,
  planActuel,
}: {
  fonctionnalite: string;
  planActuel: string;
}) {
  return (
    <div className="message message-alerte">
      <strong>{fonctionnalite}</strong> n'est pas inclus dans le plan {planActuel}.{" "}
      <a href="/abonnement">Voir les paliers supérieurs</a>
    </div>
  );
}
