/**
 * Hooks d'accès aux données, adossés à React Query.
 *
 * React Query gère le cache, les rechargements et les états de chargement.
 * Les investigations en cours sont rafraîchies périodiquement en complément du
 * WebSocket : si la connexion temps réel tombe, l'interface continue de se mettre
 * à jour, simplement moins vite.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { appelerApi } from "./client";
import type {
  Abonnement,
  ActivationTotp,
  DemandeInvestigation,
  EtatTotp,
  Graphe,
  Invitation,
  InvestigationDetaillee,
  InvestigationResumee,
  Membre,
  ModuleSite,
  Organisation,
  Plan,
  ProfilDetaille,
  ProfilResume,
  PropositionPivot,
  TypesRecherche,
  Utilisateur,
  VerdictManuel,
} from "./types";

/** Organisation active, injectée dans chaque requête par le contexte d'authentification. */
let organisationActive: string | null = null;

export function definirOrganisationActive(id: string | null): void {
  organisationActive = id;
}

function options() {
  return { organisationId: organisationActive };
}

export const cles = {
  moi: ["moi"] as const,
  totp: ["totp"] as const,
  organisation: () => ["organisation", organisationActive] as const,
  membres: () => ["membres", organisationActive] as const,
  invitations: () => ["invitations", organisationActive] as const,
  investigations: () => ["investigations", organisationActive] as const,
  investigation: (id: string) => ["investigation", id] as const,
  profils: (id: string, filtres?: unknown) => ["profils", id, filtres] as const,
  profil: (investigationId: string, profilId: string) =>
    ["profil", investigationId, profilId] as const,
  graphe: (id: string, scoreMinimal: number) => ["graphe", id, scoreMinimal] as const,
  pivots: (id: string) => ["pivots", id] as const,
  abonnement: () => ["abonnement", organisationActive] as const,
  plans: () => ["plans", organisationActive] as const,
  typesRecherche: () => ["types-recherche", organisationActive] as const,
  modules: ["modules"] as const,
};

// --- Authentification -------------------------------------------------------

export function useMoi(activee = true) {
  return useQuery({
    queryKey: cles.moi,
    queryFn: () => appelerApi<Utilisateur>("/auth/moi"),
    enabled: activee,
    retry: false,
    staleTime: 60_000,
  });
}

export function useConnexion() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (identifiants: {
      email: string;
      mot_de_passe: string;
      code_totp?: string;
    }) => appelerApi("/auth/connexion", { methode: "POST", corps: identifiants }),
    onSuccess: () => client.invalidateQueries(),
  });
}

export function useInscription() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (demande: {
      email: string;
      mot_de_passe: string;
      nom_complet?: string;
      nom_organisation?: string;
      jeton_invitation?: string;
      accepter_cgu: boolean;
      // Solution de l'épreuve anti-automatisation, résolue en arrière-plan par
      // le navigateur. Voir api/antiBot.ts.
      preuve_anti_robot?: string;
    }) => appelerApi("/auth/inscription", { methode: "POST", corps: demande }),
    onSuccess: () => client.invalidateQueries(),
  });
}

export function useDeconnexion() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => appelerApi<void>("/auth/deconnexion", { methode: "POST" }),
    onSuccess: () => client.clear(),
  });
}

// --- Double authentification (TOTP) ------------------------------------------

export function useEtatTotp() {
  return useQuery({
    queryKey: cles.totp,
    queryFn: () => appelerApi<EtatTotp>("/auth/2fa"),
  });
}

export function useActiverTotp() {
  return useMutation({
    mutationFn: () => appelerApi<ActivationTotp>("/auth/2fa/activer", { methode: "POST" }),
  });
}

export function useConfirmerTotp() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (demande: { code: string }) =>
      appelerApi<EtatTotp>("/auth/2fa/confirmer", { methode: "POST", corps: demande }),
    onSuccess: () => client.invalidateQueries({ queryKey: cles.totp }),
  });
}

export function useDesactiverTotp() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (demande: { mot_de_passe: string; code: string }) =>
      appelerApi<EtatTotp>("/auth/2fa/desactiver", { methode: "POST", corps: demande }),
    onSuccess: () => client.invalidateQueries({ queryKey: cles.totp }),
  });
}

// --- Organisation -----------------------------------------------------------

export function useOrganisation() {
  return useQuery({
    queryKey: cles.organisation(),
    queryFn: () => appelerApi<Organisation>("/organisation", options()),
    enabled: Boolean(organisationActive),
  });
}

export function useModifierOrganisation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (preferences: Partial<Organisation>) =>
      appelerApi<Organisation>("/organisation", {
        methode: "PATCH",
        corps: preferences,
        ...options(),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: cles.organisation() });
    },
  });
}

export function useMembres() {
  return useQuery({
    queryKey: cles.membres(),
    queryFn: () => appelerApi<Membre[]>("/organisation/membres", options()),
    enabled: Boolean(organisationActive),
  });
}

export function useInviter() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (demande: { email: string; role: string }) =>
      appelerApi<Invitation>("/organisation/invitations", {
        methode: "POST",
        corps: demande,
        ...options(),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: cles.membres() });
      client.invalidateQueries({ queryKey: cles.invitations() });
    },
  });
}

// --- Investigations ---------------------------------------------------------

export function useInvestigations() {
  return useQuery({
    queryKey: cles.investigations(),
    queryFn: () => appelerApi<InvestigationResumee[]>("/investigations", options()),
    enabled: Boolean(organisationActive),
    // Une investigation en cours progresse : on rafraîchit la liste régulièrement
    refetchInterval: (requete) => {
      const donnees = requete.state.data as InvestigationResumee[] | undefined;
      const enCours = donnees?.some(
        (i) => i.statut === "en_cours" || i.statut === "en_attente",
      );
      return enCours ? 5_000 : false;
    },
  });
}

export function useInvestigation(
  id: string | undefined,
  optionsSupplementaires?: Partial<UseQueryOptions<InvestigationDetaillee>>,
) {
  return useQuery({
    queryKey: cles.investigation(id ?? ""),
    queryFn: () =>
      appelerApi<InvestigationDetaillee>(`/investigations/${id}`, options()),
    enabled: Boolean(id),
    ...optionsSupplementaires,
  });
}

/**
 * Types de points de départ acceptés par le serveur, et ceux que le plan autorise.
 * Ne change qu'au changement de plan : le cache peut être long.
 */
export function useTypesRecherche() {
  return useQuery({
    queryKey: cles.typesRecherche(),
    queryFn: () =>
      appelerApi<TypesRecherche>("/investigations/types-recherche", options()),
    enabled: Boolean(organisationActive),
    staleTime: 5 * 60_000,
  });
}

export function useCreerInvestigation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (demande: DemandeInvestigation) =>
      appelerApi<InvestigationDetaillee>("/investigations", {
        methode: "POST",
        corps: demande,
        ...options(),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: cles.investigations() });
      client.invalidateQueries({ queryKey: cles.abonnement() });
    },
  });
}

export function useSupprimerInvestigation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      appelerApi<void>(`/investigations/${id}`, { methode: "DELETE", ...options() }),
    onSuccess: () => client.invalidateQueries({ queryKey: cles.investigations() }),
  });
}

export function useRelancerCorrelation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      appelerApi<InvestigationDetaillee>(
        `/investigations/${id}/relancer-correlation`,
        { methode: "POST", ...options() },
      ),
    onSuccess: (_, id) => {
      client.invalidateQueries({ queryKey: cles.investigation(id) });
      client.invalidateQueries({ queryKey: ["profils", id] });
      client.invalidateQueries({ queryKey: ["graphe", id] });
    },
  });
}

// --- Profils ----------------------------------------------------------------

export interface FiltresProfils {
  score_minimal?: number;
  niveau?: string;
  inclure_faux_positifs?: boolean;
  tri?: "score" | "site" | "profondeur";
}

export function useProfils(investigationId: string | undefined, filtres: FiltresProfils = {}) {
  return useQuery({
    queryKey: cles.profils(investigationId ?? "", filtres),
    queryFn: () =>
      appelerApi<ProfilResume[]>(`/investigations/${investigationId}/profils`, {
        parametres: filtres as Record<string, string | number | boolean | undefined>,
        ...options(),
      }),
    enabled: Boolean(investigationId),
  });
}

export function useProfil(investigationId: string | undefined, profilId: string | null) {
  return useQuery({
    queryKey: cles.profil(investigationId ?? "", profilId ?? ""),
    queryFn: () =>
      appelerApi<ProfilDetaille>(
        `/investigations/${investigationId}/profils/${profilId}`,
        options(),
      ),
    enabled: Boolean(investigationId && profilId),
  });
}

export function useDefinirVerdict(investigationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ profilId, verdict }: { profilId: string; verdict: VerdictManuel | null }) =>
      appelerApi<ProfilResume>(
        `/investigations/${investigationId}/profils/${profilId}/verdict`,
        { methode: "POST", corps: { verdict }, ...options() },
      ),
    onSuccess: () => {
      // Un verdict modifie le score des AUTRES profils (règles croisées) :
      // il faut donc tout recharger, pas seulement le profil concerné.
      client.invalidateQueries({ queryKey: ["profils", investigationId] });
      client.invalidateQueries({ queryKey: ["profil", investigationId] });
      client.invalidateQueries({ queryKey: ["graphe", investigationId] });
      client.invalidateQueries({ queryKey: cles.investigation(investigationId) });
    },
  });
}

export function useEnrichirProfil(investigationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (profilId: string) =>
      appelerApi<{ statut: string; module: string }>(
        `/investigations/${investigationId}/profils/${profilId}/enrichir`,
        { methode: "POST", ...options() },
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: cles.abonnement() });
    },
  });
}

// --- Graphe -----------------------------------------------------------------

export function useGraphe(investigationId: string | undefined, scoreMinimal = 0) {
  return useQuery({
    queryKey: cles.graphe(investigationId ?? "", scoreMinimal),
    queryFn: () =>
      appelerApi<Graphe>(`/investigations/${investigationId}/graphe`, {
        parametres: { score_minimal: scoreMinimal },
        ...options(),
      }),
    enabled: Boolean(investigationId),
  });
}

// --- Pivots -----------------------------------------------------------------

export function usePropositionsPivot(investigationId: string | undefined, statut?: string) {
  return useQuery({
    queryKey: [...cles.pivots(investigationId ?? ""), statut],
    queryFn: () =>
      appelerApi<PropositionPivot[]>(`/investigations/${investigationId}/pivots`, {
        parametres: { statut },
        ...options(),
      }),
    enabled: Boolean(investigationId),
  });
}

export function useDeciderPivot(investigationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ propositionId, accepter }: { propositionId: string; accepter: boolean }) =>
      appelerApi<PropositionPivot>(
        `/investigations/${investigationId}/pivots/${propositionId}/decision`,
        { methode: "POST", corps: { accepter }, ...options() },
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: cles.pivots(investigationId) });
      client.invalidateQueries({ queryKey: cles.investigation(investigationId) });
      client.invalidateQueries({ queryKey: cles.abonnement() });
    },
  });
}

// --- Abonnement -------------------------------------------------------------

export function useAbonnement() {
  return useQuery({
    queryKey: cles.abonnement(),
    queryFn: () => appelerApi<Abonnement>("/abonnement", options()),
    enabled: Boolean(organisationActive),
  });
}

export function usePlans() {
  return useQuery({
    queryKey: cles.plans(),
    queryFn: () => appelerApi<Plan[]>("/abonnement/plans", options()),
    enabled: Boolean(organisationActive),
  });
}

export function useDemarrerPaiement() {
  return useMutation({
    mutationFn: (demande: { code_plan: string }) =>
      appelerApi<{ url: string }>("/abonnement/checkout", {
        methode: "POST",
        corps: demande,
        ...options(),
      }),
  });
}

export function useOuvrirPortail() {
  return useMutation({
    mutationFn: () =>
      appelerApi<{ url: string }>("/abonnement/portail", { methode: "POST", ...options() }),
  });
}

// --- Modules ----------------------------------------------------------------

export function useModules() {
  return useQuery({
    queryKey: cles.modules,
    queryFn: async () => {
      const reponse = await fetch("/api/v1/modules", { credentials: "include" });
      const donnees = (await reponse.json()) as { modules: ModuleSite[] };
      return donnees.modules;
    },
    staleTime: Infinity, // la liste des modules ne change qu'au redéploiement
  });
}
