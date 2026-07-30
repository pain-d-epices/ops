import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ErreurApi } from "../api/client";
import {
  useAbonnement,
  useCreerInvestigation,
  useInvestigations,
  useOrganisation,
  useTypesRecherche,
} from "../api/hooks";
import type { ModePivot } from "../api/types";
import {
  LignePointDepartChamp,
  problemeLigne,
  SaisiePointsDepart,
  typeEffectif,
  type LignePointDepart,
} from "../composants/PointsDepart";
import {
  BadgeStatut,
  BarreProgression,
  Chargement,
  EtatVide,
  MessageErreur,
} from "../composants/ui";
import { useAuth } from "../contexts/AuthContext";
import { depuis, formaterNombre } from "../utilitaires/format";

/**
 * Durée approximative d'une recherche, calibrée sur des mesures réelles :
 * 50 sites en 25 s, 500 sites en 133 s — soit environ 0,25 s par site, plus une
 * dizaine de secondes de démarrage. Mieux vaut une estimation qui suit le réglage
 * choisi qu'une fourchette figée qui se trompe dans les deux sens.
 */
function dureeEstimee(nombreSites: number): string {
  const secondes = 10 + nombreSites * 0.25;
  if (secondes < 60) return `environ ${Math.round(secondes / 10) * 10} secondes`;
  const minutes = Math.max(1, Math.round(secondes / 60));
  return `environ ${minutes} minute${minutes > 1 ? "s" : ""}`;
}

/** Taille de la base de sites de Maigret : ce que signifie « recherche maximale ». */
const TOTALITE_DES_SITES = 3000;

/** Paliers proposés pour le nombre de sites, du plus rapide au plus complet. */
const PALIERS_SITES = [
  { valeur: 50, libelle: "50 — les plus fréquentés" },
  { valeur: 200, libelle: "200" },
  { valeur: 500, libelle: "500 — recommandé" },
  { valeur: 1000, libelle: "1000" },
  { valeur: TOTALITE_DES_SITES, libelle: "Tous les sites" },
];

export function PageAccueil() {
  return (
    <div className="grille-tableau-bord">
      <FormulaireInvestigation />
      <ListeInvestigations />
    </div>
  );
}

function FormulaireInvestigation() {
  const naviguer = useNavigate();
  const { organisation } = useAuth();
  const { data: parametresOrganisation } = useOrganisation();
  const { data: abonnement } = useAbonnement();
  const { data: typesRecherche } = useTypesRecherche();
  const creer = useCreerInvestigation();

  const [pointPrincipal, setPointPrincipal] = useState<LignePointDepart>({
    cle: 0,
    valeur: "",
    type: null,
  });
  const [pointsDepart, setPointsDepart] = useState<LignePointDepart[]>([]);
  const [variantes, setVariantes] = useState("");
  const [titre, setTitre] = useState("");
  const [profondeur, setProfondeur] = useState<number | null>(null);
  const [modePivot, setModePivot] = useState<ModePivot | null>(null);
  const [nombreSites, setNombreSites] = useState<number>(500);
  const [sitesExclus, setSitesExclus] = useState("");
  const [optionsVisibles, setOptionsVisibles] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const plan = abonnement?.plan;
  const profondeurMax = plan?.profondeur_pivot_max ?? 0;
  const pivotDisponible = profondeurMax > 0 && Boolean(plan?.fonctionnalites.includes("pivot"));
  const pivotAutoDisponible = Boolean(plan?.fonctionnalites.includes("pivot_automatique"));

  const quotaRecherches = abonnement?.quotas.find((q) => q.nom === "recherches");
  const quotaEpuise = quotaRecherches?.restant === 0;

  const typesDisponibles = typesRecherche?.types ?? [];
  const typePrincipalEffectif = typeEffectif(pointPrincipal);

  // Nombre de sites : le plan impose un plafond (0 = recherche maximale). La valeur
  // choisie est ramenée à ce plafond, et non refusée — le serveur la bornerait de
  // toute façon, autant afficher tout de suite ce qui sera réellement analysé.
  const plafondSites = typesRecherche?.max_sites_analyses || TOTALITE_DES_SITES;
  const nombreSitesEffectif = Math.min(nombreSites, plafondSites);
  const plafondAtteint = plafondSites < TOTALITE_DES_SITES;
  // Une ligne en défaut (type non couvert par le plan, ou non pris en charge) bloque
  // l'envoi : mieux vaut le dire tout de suite que faire échouer la requête.
  const problemePrincipal = problemeLigne(pointPrincipal, typesDisponibles);
  const lignesEnDefaut =
    Boolean(problemePrincipal) || pointsDepart.some((l) => problemeLigne(l, typesDisponibles));

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);

    try {
      const investigation = await creer.mutateAsync({
        pseudo: pointPrincipal.valeur.trim(),
        type_principal: typePrincipalEffectif,
        points_depart: pointsDepart
          .filter((ligne) => ligne.valeur.trim())
          .map((ligne) => ({
            valeur: ligne.valeur.trim(),
            // Le type détecté est envoyé explicitement : l'utilisateur a vu lequel
            // s'affichait, le serveur ne doit pas en retenir un autre.
            type: typeEffectif(ligne),
          })),
        variantes: variantes
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean)
          .slice(0, 5),
        titre: titre.trim() || null,
        profondeur_pivot: profondeur,
        mode_pivot: modePivot,
        top_sites: nombreSitesEffectif,
        sites_exclus: sitesExclus
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      naviguer(`/investigations/${investigation.id}`);
    } catch (exception) {
      setErreur(
        exception instanceof ErreurApi
          ? exception.message
          : "Impossible de lancer la recherche.",
      );
    }
  };

  return (
    <form className="carte" onSubmit={soumettre}>
      <div className="carte-titre">
        <h2>Nouvelle investigation</h2>
      </div>

      {erreur && (
        <div style={{ marginBottom: 16 }}>
          <MessageErreur>
            {erreur}
            {creer.error instanceof ErreurApi && creer.error.estQuotaDepasse && (
              <>
                {" "}
                <Link to="/abonnement">Voir mon abonnement</Link>
              </>
            )}
          </MessageErreur>
        </div>
      )}

      {quotaEpuise && (
        <div className="message message-alerte" style={{ marginBottom: 16 }}>
          Votre quota de recherches est épuisé pour ce mois.{" "}
          <Link to="/abonnement">Passer à un palier supérieur</Link>
        </div>
      )}

      <div className="champ">
        <label>Élément de départ</label>
        {typesRecherche ? (
          <LignePointDepartChamp
            ligne={pointPrincipal}
            types={typesDisponibles}
            onChangement={(champs) => setPointPrincipal((p) => ({ ...p, ...champs }))}
            placeholderVide="pseudonyme, adresse électronique, téléphone, compte…"
            autoFocus
          />
        ) : (
          <input disabled placeholder="Chargement…" />
        )}
        <div className="aide">
          {typePrincipalEffectif === "pseudo" ? (
            <>
              Recherche sur {formaterNombre(nombreSitesEffectif)} sites —{" "}
              {dureeEstimee(nombreSitesEffectif)}. Vous pouvez quitter la page, le
              traitement continue.
            </>
          ) : (
            <>
              La recherche est adaptée au type choisi. Si un pseudonyme en est déduit
              (adresse électronique, compte…), la recherche large sur{" "}
              {formaterNombre(nombreSitesEffectif)} sites est aussi lancée
              automatiquement.
            </>
          )}
        </div>
      </div>

      {typesRecherche && (
        <SaisiePointsDepart
          lignes={pointsDepart}
          onChangement={setPointsDepart}
          types={typesRecherche.types}
          maximum={typesRecherche.max_points_depart}
          nomPlan={plan?.nom_affiche ?? organisation?.plan_nom}
        />
      )}

      <button
        type="button"
        className="bouton-discret"
        style={{ marginBottom: 14 }}
        onClick={() => setOptionsVisibles((v) => !v)}
      >
        {optionsVisibles ? "▾" : "▸"} Options avancées
      </button>

      {optionsVisibles && (
        <>
          <div className="champ">
            <label htmlFor="titre">Titre de l'investigation (facultatif)</label>
            <input
              id="titre"
              value={titre}
              onChange={(e) => setTitre(e.target.value)}
              placeholder="ex. Dossier 2026-14"
            />
          </div>

          <div className="champ">
            <label htmlFor="variantes">Variantes du pseudonyme</label>
            <input
              id="variantes"
              value={variantes}
              onChange={(e) => setVariantes(e.target.value)}
              placeholder="jean.martin, jmartin, jean_martin"
            />
            <div className="aide">
              Séparées par des virgules (5 maximum). Elles servent de référence au
              calcul de similarité, sans déclencher de recherche supplémentaire.
            </div>
          </div>

          <div className="champ">
            <label htmlFor="profondeur">Profondeur de rebond</label>
            <select
              id="profondeur"
              value={profondeur ?? ""}
              onChange={(e) =>
                setProfondeur(e.target.value === "" ? null : Number(e.target.value))
              }
              disabled={!pivotDisponible}
            >
              <option value="">
                Valeur de l'organisation ({parametresOrganisation?.profondeur_pivot_effective ?? 0})
              </option>
              {Array.from({ length: profondeurMax + 1 }, (_, niveau) => (
                <option key={niveau} value={niveau}>
                  {niveau === 0 ? "Aucun rebond" : `${niveau} niveau${niveau > 1 ? "x" : ""}`}
                </option>
              ))}
            </select>
            <div className="aide">
              {pivotDisponible
                ? `Votre plan autorise ${profondeurMax} niveau${profondeurMax > 1 ? "x" : ""} de rebond.`
                : `Le rebond n'est pas inclus dans le plan ${organisation?.plan_nom ?? "actuel"}.`}
            </div>
          </div>

          <div className="champ">
            <label htmlFor="mode-pivot">Mode de rebond</label>
            <select
              id="mode-pivot"
              value={modePivot ?? ""}
              onChange={(e) => setModePivot((e.target.value || null) as ModePivot | null)}
              disabled={!pivotDisponible}
            >
              <option value="">
                Valeur de l'organisation (
                {parametresOrganisation?.mode_pivot_effectif === "automatique"
                  ? "automatique"
                  : "supervisé"}
                )
              </option>
              <option value="supervise">Supervisé — je valide chaque rebond</option>
              <option value="automatique" disabled={!pivotAutoDisponible}>
                Automatique{!pivotAutoDisponible ? " (plan Pro requis)" : ""}
              </option>
            </select>
          </div>

          <div className="champ">
            <label htmlFor="nombre-sites">Nombre de sites à analyser</label>
            <select
              id="nombre-sites"
              value={nombreSitesEffectif}
              onChange={(e) => setNombreSites(Number(e.target.value))}
            >
              {PALIERS_SITES.map((palier) => {
                const horsPlan = palier.valeur > plafondSites;
                return (
                  <option key={palier.valeur} value={palier.valeur} disabled={horsPlan}>
                    {palier.libelle} ({dureeEstimee(palier.valeur)})
                    {horsPlan ? ` — non inclus dans le plan ${typesRecherche?.nom_plan ?? "actuel"}` : ""}
                  </option>
                );
              })}
            </select>
            <div className="aide">
              C'est le principal levier sur la durée d'une recherche. Les sites sont
              classés par fréquentation : les premiers sont les plus susceptibles de
              donner un résultat.
            </div>
            {plafondAtteint && (
              <div className="aide aide-alerte">
                Le plan {typesRecherche?.nom_plan ?? "actuel"} analyse au maximum{" "}
                {formaterNombre(plafondSites)} sites par recherche.{" "}
                <Link to="/abonnement">Passer à un palier supérieur</Link> pour élargir
                la couverture.
              </div>
            )}
          </div>

          <div className="champ">
            <label htmlFor="exclusions">Sites à exclure</label>
            <input
              id="exclusions"
              value={sitesExclus}
              onChange={(e) => setSitesExclus(e.target.value)}
              placeholder="instructables.com, wikipedia.org"
            />
            <div className="aide">
              Noms ou domaines séparés par des virgules.
            </div>
          </div>
        </>
      )}

      <button
        type="submit"
        className="bouton-principal"
        style={{ width: "100%" }}
        disabled={creer.isPending || !pointPrincipal.valeur.trim() || quotaEpuise || lignesEnDefaut}
      >
        {creer.isPending ? <span className="chargement" /> : "Lancer la recherche"}
      </button>

      {lignesEnDefaut && (
        <div className="aide centre" style={{ marginTop: 10 }}>
          Corrigez ou retirez les éléments de départ signalés pour lancer la recherche.
        </div>
      )}

      {quotaRecherches && quotaRecherches.limite !== null && (
        <div className="aide centre" style={{ marginTop: 10 }}>
          {formaterNombre(quotaRecherches.restant ?? 0)} recherche
          {(quotaRecherches.restant ?? 0) > 1 ? "s" : ""} restante
          {(quotaRecherches.restant ?? 0) > 1 ? "s" : ""} ce mois-ci
        </div>
      )}
    </form>
  );
}

function ListeInvestigations() {
  const { data: investigations, isLoading, error } = useInvestigations();

  if (isLoading) return <Chargement />;
  if (error) return <MessageErreur>Impossible de charger les investigations.</MessageErreur>;

  if (!investigations || investigations.length === 0) {
    return (
      <div className="carte">
        <EtatVide titre="Aucune investigation pour le moment">
          Lancez votre première recherche avec le formulaire ci-contre.
        </EtatVide>
      </div>
    );
  }

  return (
    <div>
      <div className="carte-titre">
        <h2>Investigations</h2>
        <span className="petit attenue">{investigations.length} au total</span>
      </div>

      <div className="liste-investigations">
        {investigations.map((investigation) => (
          <Link
            key={investigation.id}
            to={`/investigations/${investigation.id}`}
            className="carte-investigation"
          >
            <div className="ligne-espacee">
              <div className="plein">
                <span className="pseudo-cible">{investigation.pseudo_initial}</span>
                {investigation.titre && (
                  <span className="attenue petit" style={{ marginLeft: 10 }}>
                    {investigation.titre}
                  </span>
                )}
              </div>
              <BadgeStatut statut={investigation.statut} />
            </div>

            {(investigation.statut === "en_cours" || investigation.statut === "en_attente") && (
              <div style={{ marginTop: 10 }}>
                <BarreProgression valeur={investigation.progression} />
                <div className="petit attenue" style={{ marginTop: 5 }}>
                  {investigation.etape_courante ?? "En attente de traitement…"}
                </div>
              </div>
            )}

            <div className="meta-investigation">
              <span>{investigation.nb_profils_trouves} compte(s)</span>
              <span>{investigation.nb_profils_confirmes} à confiance élevée</span>
              <span>{investigation.nb_recherches_effectuees} recherche(s)</span>
              <span>{depuis(investigation.cree_le)}</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
