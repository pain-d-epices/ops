/** Fonctions de formatage partagées par l'interface. */

import type { NiveauConfiance, StatutInvestigation } from "../api/types";

const FORMAT_DATE = new Intl.DateTimeFormat("fr-FR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formaterDate(valeur: string | null | undefined): string {
  if (!valeur) return "—";
  const date = new Date(valeur);
  return Number.isNaN(date.getTime()) ? "—" : FORMAT_DATE.format(date);
}

export function formaterDateCourte(valeur: string | null | undefined): string {
  if (!valeur) return "—";
  const date = new Date(valeur);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

/** Durée écoulée en français : « il y a 3 minutes ». */
export function depuis(valeur: string | null | undefined): string {
  if (!valeur) return "—";
  const date = new Date(valeur);
  if (Number.isNaN(date.getTime())) return "—";

  const secondes = Math.floor((Date.now() - date.getTime()) / 1000);
  if (secondes < 60) return "à l'instant";
  if (secondes < 3600) {
    const minutes = Math.floor(secondes / 60);
    return `il y a ${minutes} minute${minutes > 1 ? "s" : ""}`;
  }
  if (secondes < 86400) {
    const heures = Math.floor(secondes / 3600);
    return `il y a ${heures} heure${heures > 1 ? "s" : ""}`;
  }
  const jours = Math.floor(secondes / 86400);
  if (jours < 31) return `il y a ${jours} jour${jours > 1 ? "s" : ""}`;
  return formaterDateCourte(valeur);
}

export function formaterPrix(centimes: number): string {
  if (centimes === 0) return "Gratuit";
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: centimes % 100 === 0 ? 0 : 2,
  }).format(centimes / 100);
}

export function formaterNombre(valeur: number): string {
  return new Intl.NumberFormat("fr-FR").format(valeur);
}

export const LIBELLES_NIVEAU: Record<NiveauConfiance, string> = {
  eleve: "Confiance élevée",
  moyen: "Confiance moyenne",
  faible: "Confiance faible",
};

export const LIBELLES_STATUT: Record<StatutInvestigation, string> = {
  en_attente: "En attente",
  en_cours: "En cours",
  terminee: "Terminée",
  erreur: "Erreur",
  annulee: "Annulée",
};

/** Libellés lisibles des types de données extraites. */
export const LIBELLES_TYPE_DONNEE: Record<string, string> = {
  bio: "Biographie",
  nom_affiche: "Nom affiché",
  nom_reel: "Nom réel",
  email: "Adresse e-mail",
  pseudo_alt: "Autre pseudonyme",
  localisation: "Localisation",
  lien_externe: "Lien externe",
  avatar_url: "Avatar",
  avatar_phash: "Empreinte d'avatar",
  date_creation: "Date de création",
  telephone: "Téléphone",
  entreprise: "Entreprise",
  langue: "Langue",
  nb_abonnes: "Abonnés",
};

export function libelleTypeDonnee(type: string): string {
  return LIBELLES_TYPE_DONNEE[type] ?? type;
}

/** Libellés des règles de corrélation, pour l'explication du score. */
export const LIBELLES_REGLE: Record<string, string> = {
  pseudo_similarite: "Cohérence du pseudonyme",
  avatar_phash: "Avatar identique",
  liens_croises: "Lien explicite entre profils",
  coherence_temporelle: "Cohérence des dates",
  contenu_bio: "Similarité de la biographie",
  email_partage: "Adresse e-mail partagée",
  site_douteux: "Fiabilité du résultat",
};

export function libelleRegle(regle: string): string {
  return LIBELLES_REGLE[regle] ?? regle;
}

/** Libellés des fonctionnalités de plan, pour la page Abonnement. */
export const LIBELLES_FONCTIONNALITE: Record<string, string> = {
  modules: "Modules d'enrichissement par site",
  pivot: "Rebond sur les informations découvertes",
  pivot_automatique: "Rebond automatique (sans validation)",
  export_csv: "Export CSV",
  export_pdf: "Rapport PDF",
  api: "Accès API",
  retention_etendue: "Rétention étendue",
  multi_utilisateurs: "Plusieurs utilisateurs",
};

export function libelleFonctionnalite(code: string): string {
  return LIBELLES_FONCTIONNALITE[code] ?? code;
}

export function tronquer(texte: string, longueur = 60): string {
  return texte.length <= longueur ? texte : `${texte.slice(0, longueur - 1)}…`;
}
