import { lazy, Suspense, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ErreurApi, telechargerExport } from "../api/client";
import {
  useGraphe,
  useInvestigation,
  useSupprimerInvestigation,
} from "../api/hooks";
import { PanneauDetail } from "../composants/graphe/PanneauDetail";
import { PropositionsPivotListe } from "../composants/PropositionsPivot";
import { TableauProfils } from "../composants/TableauProfils";
import {
  BadgeStatut,
  BarreProgression,
  Chargement,
  IndicateurTempsReel,
  MessageErreur,
} from "../composants/ui";
import { useAuth } from "../contexts/AuthContext";
import { formaterDate } from "../utilitaires/format";
import { useSuiviInvestigation } from "../ws/useSuiviInvestigation";

// Cytoscape pèse ~570 ko : le charger à la demande évite de l'imposer aux pages
// de connexion, d'accueil et d'abonnement, qui n'en ont pas besoin.
const GrapheInvestigation = lazy(() =>
  import("../composants/graphe/GrapheInvestigation").then((module) => ({
    default: module.GrapheInvestigation,
  })),
);

type Onglet = "graphe" | "comptes" | "rebonds" | "journal";

export function PageInvestigation() {
  const { investigationId } = useParams<{ investigationId: string }>();
  const naviguer = useNavigate();
  const { organisation } = useAuth();

  const [onglet, setOnglet] = useState<Onglet>("graphe");
  const [noeudSelectionne, setNoeudSelectionne] = useState<string | null>(null);
  const [profilSelectionne, setProfilSelectionne] = useState<string | null>(null);
  const [scoreMinimal, setScoreMinimal] = useState(0);
  const [typesMasques, setTypesMasques] = useState<Set<string>>(new Set());
  const [erreurExport, setErreurExport] = useState<string | null>(null);

  const { data: investigation, isLoading, error } = useInvestigation(investigationId, {
    // Complément au WebSocket : si le temps réel tombe, l'affichage continue
    // d'avancer, simplement moins vite.
    refetchInterval: (requete) => {
      const statut = requete.state.data?.statut;
      return statut === "en_cours" || statut === "en_attente" ? 5_000 : false;
    },
  });

  const enCours =
    investigation?.statut === "en_cours" || investigation?.statut === "en_attente";
  const suivi = useSuiviInvestigation(investigationId, Boolean(enCours));

  const { data: graphe } = useGraphe(investigationId, scoreMinimal);
  const supprimer = useSupprimerInvestigation();

  const noeudCourant = useMemo(
    () => graphe?.noeuds.find((n) => n.id === noeudSelectionne) ?? null,
    [graphe, noeudSelectionne],
  );

  // La sélection dans le tableau doit se refléter dans le graphe, et inversement
  const selectionnerDepuisTableau = (profilId: string) => {
    setProfilSelectionne(profilId);
    const noeud = graphe?.noeuds.find((n) => n.profil_id === profilId);
    setNoeudSelectionne(noeud?.id ?? null);
  };

  const basculerType = (type: string) =>
    setTypesMasques((precedent) => {
      const copie = new Set(precedent);
      if (copie.has(type)) copie.delete(type);
      else copie.add(type);
      return copie;
    });

  const exporter = async (format: "json" | "csv") => {
    setErreurExport(null);
    try {
      await telechargerExport(investigationId!, format, organisation?.id ?? null);
    } catch (exception) {
      setErreurExport(
        exception instanceof ErreurApi ? exception.message : "Export impossible.",
      );
    }
  };

  const supprimerInvestigation = async () => {
    const confirme = window.confirm(
      "Supprimer définitivement cette investigation ?\n\n" +
        "Tous les comptes, informations extraites et éléments du graphe seront effacés. " +
        "Cette action est irréversible.",
    );
    if (!confirme) return;
    await supprimer.mutateAsync(investigationId!);
    naviguer("/");
  };

  if (isLoading) return <Chargement texte="Chargement de l'investigation…" />;
  if (error || !investigation) {
    return (
      <MessageErreur>
        Investigation introuvable. <Link to="/">Retour à la liste</Link>
      </MessageErreur>
    );
  }

  const progression = Math.max(investigation.progression, suivi.progression);

  return (
    <div>
      <div className="entete-investigation">
        <div>
          <div className="ligne" style={{ gap: 12, marginBottom: 4 }}>
            <h1 style={{ margin: 0 }} className="pseudo-cible">
              {investigation.pseudo_initial}
            </h1>
            <BadgeStatut statut={investigation.statut} />
            {enCours && <IndicateurTempsReel connecte={suivi.connecte} />}
          </div>
          <div className="petit attenue">
            {investigation.titre && <>{investigation.titre} · </>}
            Créée le {formaterDate(investigation.cree_le)}
            {investigation.cree_par_email && <> par {investigation.cree_par_email}</>}
            {investigation.supprimer_apres && (
              <> · purge automatique le {formaterDate(investigation.supprimer_apres)}</>
            )}
          </div>
        </div>

        <div className="ligne" style={{ gap: 8 }}>
          <button className="bouton-petit" onClick={() => exporter("json")}>
            Export JSON
          </button>
          <button className="bouton-petit" onClick={() => exporter("csv")}>
            Export CSV
          </button>
          <button
            className="bouton-petit bouton-danger"
            onClick={supprimerInvestigation}
            disabled={supprimer.isPending}
          >
            Supprimer
          </button>
        </div>
      </div>

      {erreurExport && (
        <div style={{ marginBottom: 14 }}>
          <MessageErreur>
            {erreurExport} <Link to="/abonnement">Voir les paliers</Link>
          </MessageErreur>
        </div>
      )}

      {investigation.message_erreur && (
        <div style={{ marginBottom: 14 }}>
          <MessageErreur>{investigation.message_erreur}</MessageErreur>
        </div>
      )}

      {enCours && (
        <div className="carte" style={{ marginBottom: 18 }}>
          <div className="ligne-espacee" style={{ marginBottom: 8 }}>
            <span className="gras">
              {suivi.etape ?? investigation.etape_courante ?? "Traitement en cours…"}
            </span>
            <span className="mono petit">{progression} %</span>
          </div>
          <BarreProgression valeur={progression} />
          <div className="petit attenue" style={{ marginTop: 8 }}>
            Une recherche complète prend généralement 2 à 10 minutes. Vous pouvez
            quitter cette page : le traitement continue côté serveur.
          </div>
        </div>
      )}

      <div className="ligne enveloppe" style={{ gap: 20, marginBottom: 18 }}>
        <Statistique valeur={investigation.nb_profils_trouves} libelle="comptes trouvés" />
        <Statistique
          valeur={investigation.nb_profils_confirmes}
          libelle="à confiance élevée"
        />
        <Statistique
          valeur={investigation.nb_recherches_effectuees}
          libelle="recherches effectuées"
        />
        <Statistique valeur={investigation.nb_noeuds} libelle="éléments dans le graphe" />
      </div>

      <div className="onglets">
        <button
          className={onglet === "graphe" ? "actif" : ""}
          onClick={() => setOnglet("graphe")}
        >
          Graphe
        </button>
        <button
          className={onglet === "comptes" ? "actif" : ""}
          onClick={() => setOnglet("comptes")}
        >
          Comptes
          <span className="compteur-onglet">{investigation.nb_profils_trouves}</span>
        </button>
        <button
          className={onglet === "rebonds" ? "actif" : ""}
          onClick={() => setOnglet("rebonds")}
        >
          Rebonds
          {investigation.nb_propositions_en_attente > 0 && (
            <span className="compteur-onglet" style={{ background: "var(--confiance-moyenne)", color: "#0f1216" }}>
              {investigation.nb_propositions_en_attente}
            </span>
          )}
        </button>
        <button
          className={onglet === "journal" ? "actif" : ""}
          onClick={() => setOnglet("journal")}
        >
          Journal
        </button>
      </div>

      {onglet === "graphe" && (
        <div className="zone-graphe">
          <Suspense
            fallback={
              <div className="conteneur-graphe">
                <Chargement texte="Chargement du graphe…" />
              </div>
            }
          >
            <GrapheInvestigation
              graphe={graphe}
              noeudSelectionne={noeudSelectionne}
              onSelectionner={(noeudId, profilId) => {
                setNoeudSelectionne(noeudId);
                setProfilSelectionne(profilId);
              }}
              scoreMinimal={scoreMinimal}
              onScoreMinimalChange={setScoreMinimal}
              typesMasques={typesMasques}
              onBasculerType={basculerType}
            />
          </Suspense>
          <PanneauDetail
            investigationId={investigationId!}
            noeud={noeudCourant}
            profilId={profilSelectionne}
          />
        </div>
      )}

      {onglet === "comptes" && (
        <div className="zone-graphe">
          <TableauProfils
            investigationId={investigationId!}
            profilSelectionne={profilSelectionne}
            onSelectionner={selectionnerDepuisTableau}
          />
          <PanneauDetail
            investigationId={investigationId!}
            noeud={
              noeudCourant ??
              (profilSelectionne
                ? { id: "", type: "compte", libelle: "", score: 0, profondeur: 0, profil_id: profilSelectionne, meta: {} }
                : null)
            }
            profilId={profilSelectionne}
          />
        </div>
      )}

      {onglet === "rebonds" && <PropositionsPivotListe investigationId={investigationId!} />}

      {onglet === "journal" && (
        <div className="carte">
          <div className="carte-titre">
            <h3>Journal d'exécution</h3>
            {enCours && <IndicateurTempsReel connecte={suivi.connecte} />}
          </div>
          {suivi.journal.length === 0 ? (
            <p className="attenue petit">
              {enCours
                ? "En attente des premiers événements…"
                : "Le journal en direct n'est disponible que pendant l'exécution. " +
                  "Les résultats restent consultables dans les autres onglets."}
            </p>
          ) : (
            <div className="journal">
              {suivi.journal.map((entree) => (
                <div key={entree.id} className={`journal-ligne journal-${entree.niveau}`}>
                  <span className="journal-heure">
                    {entree.horodatage.toLocaleTimeString("fr-FR")}
                  </span>
                  <span>{entree.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Statistique({ valeur, libelle }: { valeur: number; libelle: string }) {
  return (
    <div>
      <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.2 }}>{valeur}</div>
      <div className="petit attenue">{libelle}</div>
    </div>
  );
}
