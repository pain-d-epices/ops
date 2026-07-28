import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ErreurApi } from "../api/client";
import {
  useAbonnement,
  useCreerInvestigation,
  useInvestigations,
  useOrganisation,
} from "../api/hooks";
import type { ModePivot } from "../api/types";
import {
  BadgeStatut,
  BarreProgression,
  Chargement,
  EtatVide,
  MessageErreur,
} from "../composants/ui";
import { useAuth } from "../contexts/AuthContext";
import { depuis, formaterNombre } from "../utilitaires/format";

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
  const creer = useCreerInvestigation();

  const [pseudo, setPseudo] = useState("");
  const [variantes, setVariantes] = useState("");
  const [titre, setTitre] = useState("");
  const [profondeur, setProfondeur] = useState<number | null>(null);
  const [modePivot, setModePivot] = useState<ModePivot | null>(null);
  const [sitesExclus, setSitesExclus] = useState("");
  const [optionsVisibles, setOptionsVisibles] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const plan = abonnement?.plan;
  const profondeurMax = plan?.profondeur_pivot_max ?? 0;
  const pivotDisponible = profondeurMax > 0 && Boolean(plan?.fonctionnalites.includes("pivot"));
  const pivotAutoDisponible = Boolean(plan?.fonctionnalites.includes("pivot_automatique"));

  const quotaRecherches = abonnement?.quotas.find((q) => q.nom === "recherches");
  const quotaEpuise = quotaRecherches?.restant === 0;

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);

    try {
      const investigation = await creer.mutateAsync({
        pseudo: pseudo.trim(),
        variantes: variantes
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean)
          .slice(0, 5),
        titre: titre.trim() || null,
        profondeur_pivot: profondeur,
        mode_pivot: modePivot,
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
        <label htmlFor="pseudo">Pseudonyme à rechercher</label>
        <input
          id="pseudo"
          value={pseudo}
          onChange={(e) => setPseudo(e.target.value)}
          placeholder="ex. jeanmartin"
          className="mono"
          required
          minLength={2}
          autoFocus
        />
        <div className="aide">
          La recherche porte sur plusieurs centaines de sites. Comptez 2 à 10 minutes.
        </div>
      </div>

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
        disabled={creer.isPending || !pseudo.trim() || quotaEpuise}
      >
        {creer.isPending ? <span className="chargement" /> : "Lancer la recherche"}
      </button>

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
