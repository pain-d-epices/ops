/**
 * Types de l'API, alignés sur les schémas Pydantic du backend.
 * Toute modification côté backend doit être répercutée ici.
 */

// --- Authentification et organisation ---------------------------------------

export type RoleMembre = "admin" | "analyste" | "lecteur";
export type ModePivot = "supervise" | "automatique";

export interface OrganisationResumee {
  id: string;
  nom: string;
  slug: string;
  role: RoleMembre;
  plan_code: string;
  plan_nom: string;
}

export interface Utilisateur {
  id: string;
  email: string;
  nom_complet: string | null;
  cgu_acceptees: boolean;
  cgu_version_acceptee: string | null;
  derniere_connexion: string | null;
  organisations: OrganisationResumee[];
}

export interface ReponseConnexion {
  utilisateur: Utilisateur;
  organisation_active: string | null;
  jeton_acces: string;
  expire_dans_secondes: number;
}

export interface Organisation {
  id: string;
  nom: string;
  slug: string;
  statut: string;
  mode_pivot: ModePivot;
  profondeur_pivot_souhaitee: number;
  retention_jours: number;
  /** Valeurs réellement appliquées après bornage par le plan actif. */
  mode_pivot_effectif: ModePivot;
  profondeur_pivot_effective: number;
  cree_le: string;
}

export interface Membre {
  utilisateur_id: string;
  email: string;
  nom_complet: string | null;
  role: RoleMembre;
  rejoint_le: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: RoleMembre;
  jeton: string;
  expire_le: string;
  acceptee: boolean;
}

// --- Investigations ---------------------------------------------------------

export type StatutInvestigation =
  | "en_attente"
  | "en_cours"
  | "terminee"
  | "erreur"
  | "annulee";

export interface InvestigationResumee {
  id: string;
  titre: string | null;
  pseudo_initial: string;
  statut: StatutInvestigation;
  progression: number;
  etape_courante: string | null;
  nb_profils_trouves: number;
  nb_profils_confirmes: number;
  nb_recherches_effectuees: number;
  cree_le: string;
  terminee_le: string | null;
  supprimer_apres: string | null;
}

/** Types de points de départ acceptés, alignés sur TypePointDepart côté backend. */
export type TypePointDepart =
  | "pseudo"
  | "compte"
  | "email"
  | "telephone"
  | "adresse"
  | "nom"
  | "domaine";

export type StatutPointDepart =
  | "en_attente"
  | "en_cours"
  | "termine"
  | "erreur"
  | "non_autorise";

export interface PointDepartEntree {
  valeur: string;
  /** Omis, le type est deviné par le serveur. */
  type?: TypePointDepart | null;
}

export interface PointDepartSortie {
  id: string;
  type: TypePointDepart;
  valeur: string;
  statut: StatutPointDepart;
  message_erreur: string | null;
  nb_comptes_trouves: number;
  detail: Record<string, unknown>;
}

/** Un type de recherche proposé au formulaire, et son accessibilité selon le plan. */
export interface TypeRecherche {
  type: TypePointDepart;
  libelle: string;
  exemple: string;
  autorise: boolean;
  motif: string | null;
}

export interface TypesRecherche {
  types: TypeRecherche[];
  /** Points de départ simultanés, pseudonyme compris ; 0 = illimité. */
  max_points_depart: number;
  /** Sites analysables par recherche large ; 0 = sans limite. */
  max_sites_analyses: number;
  /** Nom du palier actif, pour l'expliquer dans le formulaire. */
  nom_plan: string;
}

export interface InvestigationDetaillee extends InvestigationResumee {
  variantes: string[];
  options: Record<string, unknown>;
  message_erreur: string | null;
  cree_par_email: string | null;
  nb_noeuds: number;
  nb_aretes: number;
  nb_propositions_en_attente: number;
  points_depart: PointDepartSortie[];
}

export interface DemandeInvestigation {
  pseudo: string;
  /** Type de l'élément ci-dessus ; deviné côté serveur si omis. */
  type_principal?: TypePointDepart | null;
  points_depart?: PointDepartEntree[];
  variantes?: string[];
  titre?: string | null;
  profondeur_pivot?: number | null;
  mode_pivot?: ModePivot | null;
  top_sites?: number | null;
  sites_exclus?: string[];
}

// --- Profils ----------------------------------------------------------------

export type NiveauConfiance = "faible" | "moyen" | "eleve";
export type VerdictManuel = "valide" | "faux_positif";

export interface ProfilResume {
  id: string;
  site_nom: string;
  site_domaine: string;
  url: string;
  pseudo_sur_le_site: string;
  score_confiance: number;
  niveau: NiveauConfiance;
  verdict_manuel: VerdictManuel | null;
  profondeur: number;
  enrichi: boolean;
  module_utilise: string | null;
}

export interface DonneeExtraite {
  id: string;
  type: string;
  valeur: string;
  module_source: string;
  confiance_extraction: number;
  pivotee: boolean;
  meta: Record<string, unknown>;
}

/** Contribution d'une règle au score : c'est ce qui rend le score contestable. */
export interface SignalCorrelation {
  regle: string;
  score_regle: number;
  poids: number;
  contribution_points: number;
  explication: string;
  detail: Record<string, unknown>;
}

export interface ProfilDetaille extends ProfilResume {
  statut_maigret: string;
  decouvert_par_profil_id: string | null;
  erreur_enrichissement: string | null;
  verdict_le: string | null;
  enrichi_le: string | null;
  donnees_maigret: Record<string, unknown>;
  donnees_extraites: DonneeExtraite[];
  signaux: SignalCorrelation[];
}

// --- Graphe -----------------------------------------------------------------

export type TypeNoeud =
  | "pseudo"
  | "compte"
  | "email"
  | "pseudo_alt"
  | "nom"
  | "localisation"
  | "lien"
  | "avatar"
  | "telephone"
  | "entreprise";

export interface NoeudGraphe {
  id: string;
  type: TypeNoeud;
  libelle: string;
  score: number;
  profondeur: number;
  profil_id: string | null;
  meta: Record<string, unknown>;
}

export interface AreteGraphe {
  id: string;
  source: string;
  cible: string;
  type: string;
  libelle: string | null;
  poids: number;
}

export interface Graphe {
  investigation_id: string;
  noeuds: NoeudGraphe[];
  aretes: AreteGraphe[];
}

// --- Pivots -----------------------------------------------------------------

export type StatutProposition = "en_attente" | "acceptee" | "refusee" | "automatique";

export interface PropositionPivot {
  id: string;
  type_pivot: string;
  valeur: string;
  action: string;
  libelle: string;
  profondeur_cible: number;
  statut: StatutProposition;
  profil_source_id: string | null;
  cree_le: string;
  decidee_le: string | null;
}

// --- Abonnement -------------------------------------------------------------

export interface Plan {
  code: string;
  nom_affiche: string;
  description: string | null;
  prix_mensuel_cents: number;
  ordre: number;
  quota_recherches_mois: number;
  quota_enrichissements_mois: number;
  quota_utilisateurs: number;
  quota_investigations_actives: number;
  profondeur_pivot_max: number;
  /** Points de départ simultanés, pseudonyme compris ; 0 = illimité. */
  max_points_depart: number;
  fonctionnalites: string[];
  url_achat: string | null;
  est_plan_actuel: boolean;
}

export interface Quota {
  nom: string;
  consomme: number;
  limite: number | null;
  restant: number | null;
  pourcentage: number;
}

export interface Abonnement {
  plan: Plan;
  statut: string;
  periode_debut: string | null;
  periode_fin: string | null;
  renouvellement_automatique: boolean;
  licence_active: boolean;
  quotas: Quota[];
  message_limite: string | null;
  plan_superieur: Plan | null;
}

// --- Événements temps réel --------------------------------------------------

export type TypeEvenement =
  | "connecte"
  | "ping"
  | "progression"
  | "etape"
  | "profil_trouve"
  | "profil_mis_a_jour"
  | "noeud_ajoute"
  | "pivot_propose"
  | "recherche_terminee"
  | "investigation_terminee"
  | "erreur";

export interface EvenementInvestigation {
  type: TypeEvenement;
  investigation_id?: string;
  organisation_id?: string;
  donnees?: Record<string, unknown>;
  horodatage?: string;
}

// --- Modules ----------------------------------------------------------------

export interface ModuleSite {
  nom: string;
  libelle: string;
  domaines: string[];
}
