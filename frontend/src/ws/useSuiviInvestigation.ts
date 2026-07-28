/**
 * Suivi temps réel d'une investigation via WebSocket.
 *
 * Le backend pousse les événements publiés par les workers : progression, profils
 * trouvés, nœuds ajoutés, pivots proposés. En cas de coupure, une reconnexion
 * automatique avec recul progressif prend le relais ; et le rechargement
 * périodique de React Query assure la continuité de l'affichage entre-temps.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { cles } from "../api/hooks";
import type { EvenementInvestigation } from "../api/types";

export interface EntreeJournal {
  id: number;
  horodatage: Date;
  message: string;
  niveau: "info" | "succes" | "erreur";
}

interface EtatSuivi {
  connecte: boolean;
  progression: number;
  etape: string | null;
  journal: EntreeJournal[];
  terminee: boolean;
  erreur: string | null;
}

const DELAIS_RECONNEXION = [1000, 2000, 5000, 10000, 30000];
const TAILLE_MAX_JOURNAL = 200;

export function useSuiviInvestigation(
  investigationId: string | undefined,
  actif = true,
): EtatSuivi {
  const clientRequetes = useQueryClient();
  const socket = useRef<WebSocket | null>(null);
  const tentatives = useRef(0);
  const minuterie = useRef<number | null>(null);
  const compteurJournal = useRef(0);
  const demonte = useRef(false);

  const [etat, setEtat] = useState<EtatSuivi>({
    connecte: false,
    progression: 0,
    etape: null,
    journal: [],
    terminee: false,
    erreur: null,
  });

  const ajouterJournal = useCallback(
    (message: string, niveau: EntreeJournal["niveau"] = "info") => {
      setEtat((precedent) => ({
        ...precedent,
        journal: [
          ...precedent.journal.slice(-TAILLE_MAX_JOURNAL),
          {
            id: compteurJournal.current++,
            horodatage: new Date(),
            message,
            niveau,
          },
        ],
      }));
    },
    [],
  );

  const traiterEvenement = useCallback(
    (evenement: EvenementInvestigation) => {
      const donnees = (evenement.donnees ?? {}) as Record<string, unknown>;
      const nombre = (cle: string): number | undefined =>
        typeof donnees[cle] === "number" ? (donnees[cle] as number) : undefined;
      const texte = (cle: string): string | undefined =>
        typeof donnees[cle] === "string" ? (donnees[cle] as string) : undefined;

      switch (evenement.type) {
        case "ping":
          return;

        case "connecte":
          setEtat((p) => ({ ...p, connecte: true }));
          return;

        case "progression": {
          const progression = nombre("progression");
          setEtat((p) => ({
            ...p,
            progression: Math.max(p.progression, progression ?? p.progression),
            etape: texte("message") ?? p.etape,
          }));
          return;
        }

        case "etape": {
          const etape = texte("etape");
          if (etape) ajouterJournal(etape);
          setEtat((p) => ({
            ...p,
            etape: etape ?? p.etape,
            progression: Math.max(p.progression, nombre("progression") ?? p.progression),
          }));
          return;
        }

        case "profil_trouve": {
          ajouterJournal(
            `Compte trouvé sur ${texte("site") ?? "un site"} (niveau ${nombre("profondeur") ?? 0})`,
            "succes",
          );
          // Rafraîchit la liste et le graphe pour faire apparaître le nouveau profil
          if (investigationId) {
            clientRequetes.invalidateQueries({ queryKey: ["profils", investigationId] });
            clientRequetes.invalidateQueries({ queryKey: ["graphe", investigationId] });
          }
          return;
        }

        case "profil_mis_a_jour": {
          const erreur = texte("erreur");
          if (erreur) ajouterJournal(`Enrichissement partiel : ${erreur}`, "erreur");
          if (investigationId) {
            clientRequetes.invalidateQueries({ queryKey: ["profils", investigationId] });
            clientRequetes.invalidateQueries({ queryKey: ["profil", investigationId] });
            clientRequetes.invalidateQueries({ queryKey: ["graphe", investigationId] });
          }
          return;
        }

        case "noeud_ajoute": {
          if (investigationId) {
            clientRequetes.invalidateQueries({ queryKey: ["graphe", investigationId] });
          }
          return;
        }

        case "pivot_propose": {
          const enAttente = nombre("en_attente");
          if (enAttente) {
            ajouterJournal(
              `${enAttente} piste(s) de rebond en attente de votre validation`,
              "succes",
            );
          } else {
            ajouterJournal(`Rebond automatique : ${texte("libelle") ?? "nouvelle piste"}`);
          }
          if (investigationId) {
            clientRequetes.invalidateQueries({ queryKey: cles.pivots(investigationId) });
            clientRequetes.invalidateQueries({ queryKey: cles.investigation(investigationId) });
          }
          return;
        }

        case "recherche_terminee": {
          ajouterJournal(
            `Recherche « ${texte("pseudo") ?? ""} » terminée : ${nombre("profils_crees") ?? 0} compte(s)`,
            "succes",
          );
          setEtat((p) => ({
            ...p,
            progression: Math.max(p.progression, nombre("progression") ?? 75),
          }));
          return;
        }

        case "investigation_terminee": {
          ajouterJournal(
            `Investigation terminée : ${nombre("profils_trouves") ?? 0} compte(s), ` +
              `${nombre("profils_confirmes") ?? 0} à confiance élevée`,
            "succes",
          );
          setEtat((p) => ({ ...p, progression: 100, terminee: true, etape: "Terminée" }));
          if (investigationId) {
            clientRequetes.invalidateQueries({ queryKey: cles.investigation(investigationId) });
            clientRequetes.invalidateQueries({ queryKey: ["profils", investigationId] });
            clientRequetes.invalidateQueries({ queryKey: ["graphe", investigationId] });
          }
          return;
        }

        case "erreur": {
          const message = texte("message") ?? "Erreur inconnue";
          ajouterJournal(message, "erreur");
          setEtat((p) => ({ ...p, erreur: message, terminee: true }));
          return;
        }
      }
    },
    [ajouterJournal, clientRequetes, investigationId],
  );

  useEffect(() => {
    if (!investigationId || !actif) return;

    demonte.current = false;

    const connecter = () => {
      if (demonte.current) return;

      const protocole = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocole}//${window.location.host}/ws/investigations/${investigationId}`;

      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch {
        planifierReconnexion();
        return;
      }
      socket.current = ws;

      ws.onopen = () => {
        tentatives.current = 0;
        setEtat((p) => ({ ...p, connecte: true }));
      };

      ws.onmessage = (message) => {
        try {
          traiterEvenement(JSON.parse(message.data) as EvenementInvestigation);
        } catch {
          // Message illisible : sans gravité, on ignore plutôt que de casser l'affichage
        }
      };

      ws.onerror = () => setEtat((p) => ({ ...p, connecte: false }));

      ws.onclose = (evenement) => {
        setEtat((p) => ({ ...p, connecte: false }));
        // 4401 / 4404 : refus d'accès ou investigation inexistante — inutile d'insister
        if (evenement.code === 4401 || evenement.code === 4404) return;
        planifierReconnexion();
      };
    };

    const planifierReconnexion = () => {
      if (demonte.current) return;
      const delai =
        DELAIS_RECONNEXION[Math.min(tentatives.current, DELAIS_RECONNEXION.length - 1)];
      tentatives.current += 1;
      minuterie.current = window.setTimeout(connecter, delai);
    };

    connecter();

    return () => {
      demonte.current = true;
      if (minuterie.current) window.clearTimeout(minuterie.current);
      socket.current?.close();
      socket.current = null;
    };
  }, [investigationId, actif, traiterEvenement]);

  return etat;
}
