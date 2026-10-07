/**
 * Contexte d'authentification et d'organisation active.
 *
 * L'identité de l'utilisateur provient toujours du serveur (`/auth/moi`) : aucun
 * jeton n'est conservé côté navigateur, seul le cookie httpOnly fait foi. Le
 * localStorage ne mémorise que l'organisation choisie, qui n'est pas une donnée
 * sensible et reste revérifiée par le backend à chaque requête.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { definirOrganisationActive, useMoi } from "../api/hooks";
import type { OrganisationResumee, Utilisateur } from "../api/types";

// Clé de stockage local. Renommée avec le produit (Ops → Ops) : les
// navigateurs qui portent encore l'ancienne clé repartiront simplement sur
// l'organisation par défaut, sans erreur.
const CLE_ORGANISATION = "ops.organisation";

interface ValeurAuth {
  utilisateur: Utilisateur | null;
  organisation: OrganisationResumee | null;
  organisationId: string | null;
  chargement: boolean;
  authentifie: boolean;
  changerOrganisation: (id: string) => void;
  rafraichir: () => void;
}

const ContexteAuth = createContext<ValeurAuth | null>(null);

export function FournisseurAuth({ children }: { children: ReactNode }) {
  const [organisationId, setOrganisationId] = useState<string | null>(() =>
    localStorage.getItem(CLE_ORGANISATION),
  );

  // Injecté dans le client API avant tout appel dépendant de l'organisation
  definirOrganisationActive(organisationId);

  const { data: utilisateur, isLoading, refetch } = useMoi();

  // Si l'organisation mémorisée n'existe plus (départ de l'équipe, compte
  // supprimé), on bascule silencieusement sur la première disponible.
  useEffect(() => {
    if (!utilisateur) return;
    const organisations = utilisateur.organisations;
    if (organisations.length === 0) return;

    const valide = organisations.some((o) => o.id === organisationId);
    if (!valide) {
      const premiere = organisations[0].id;
      setOrganisationId(premiere);
      localStorage.setItem(CLE_ORGANISATION, premiere);
      definirOrganisationActive(premiere);
    }
  }, [utilisateur, organisationId]);

  const changerOrganisation = useCallback((id: string) => {
    setOrganisationId(id);
    localStorage.setItem(CLE_ORGANISATION, id);
    definirOrganisationActive(id);
    // Rechargement complet : le cache des requêtes contient les données de
    // l'organisation précédente, qui ne doivent jamais apparaître ici.
    window.location.reload();
  }, []);

  const valeur = useMemo<ValeurAuth>(() => {
    const organisation =
      utilisateur?.organisations.find((o) => o.id === organisationId) ??
      utilisateur?.organisations[0] ??
      null;

    return {
      utilisateur: utilisateur ?? null,
      organisation,
      organisationId: organisation?.id ?? null,
      chargement: isLoading,
      authentifie: Boolean(utilisateur),
      changerOrganisation,
      rafraichir: () => void refetch(),
    };
  }, [utilisateur, organisationId, isLoading, changerOrganisation, refetch]);

  return <ContexteAuth.Provider value={valeur}>{children}</ContexteAuth.Provider>;
}

export function useAuth(): ValeurAuth {
  const valeur = useContext(ContexteAuth);
  if (!valeur) {
    throw new Error("useAuth doit être utilisé à l'intérieur de FournisseurAuth");
  }
  return valeur;
}

/** Raccourci : le plan actif inclut-il cette fonctionnalité ? */
export function useFonctionnalite(): {
  planCode: string;
  estGratuit: boolean;
} {
  const { organisation } = useAuth();
  const planCode = organisation?.plan_code ?? "free";
  return { planCode, estGratuit: planCode === "free" };
}
