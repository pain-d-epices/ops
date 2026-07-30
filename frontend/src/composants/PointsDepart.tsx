/**
 * Saisie des éléments de départ d'une investigation.
 *
 * L'analyste colle ce qu'il a — une adresse électronique, un numéro, l'adresse d'un
 * compte, une adresse postale — sans avoir à choisir un type : celui-ci est deviné à
 * la frappe, et reste modifiable si la détection se trompe.
 */

import { Link } from "react-router-dom";

import type { TypePointDepart, TypeRecherche } from "../api/types";

/** Entrée en cours de saisie ; `type` à null signifie « détection automatique ». */
export interface LignePointDepart {
  cle: number;
  valeur: string;
  type: TypePointDepart | null;
}

/**
 * Devine le type d'une saisie. Reproduit `detecter_type` du backend : la détection
 * doit donner le même résultat des deux côtés, sinon l'interface annoncerait un type
 * et le serveur en traiterait un autre.
 */
export function detecterType(valeur: string): TypePointDepart {
  const texte = valeur.trim();
  if (!texte) return "pseudo";

  if (texte.startsWith("http://") || texte.startsWith("https://")) return "compte";
  if (texte.includes("/") && texte.split("/")[0].includes(".")) return "compte";

  if (texte.includes("@") && texte.split("@").pop()!.includes(".") && !texte.includes(" ")) {
    return "email";
  }

  const chiffres = texte.replace(/[ ./-]/g, "").replace(/^\+/, "");
  if (/^\d+$/.test(chiffres) && chiffres.length >= 6 && chiffres.length <= 15) {
    return "telephone";
  }

  const mots = texte.split(/\s+/);
  if (mots.length >= 3 && mots.some((mot) => /^\d+$/.test(mot))) return "adresse";
  if (mots.length >= 2 && !/\d/.test(texte)) return "nom";

  return "pseudo";
}

/** Type effectivement retenu pour une ligne : celui choisi, sinon celui détecté. */
export function typeEffectif(ligne: LignePointDepart): TypePointDepart {
  return ligne.type ?? detecterType(ligne.valeur);
}

/**
 * Problème bloquant sur une ligne, ou null si elle est exploitable.
 * Une ligne vide n'est pas un problème : elle sera simplement ignorée à l'envoi.
 */
export function problemeLigne(
  ligne: LignePointDepart,
  types: TypeRecherche[],
): string | null {
  if (!ligne.valeur.trim()) return null;

  const type = typeEffectif(ligne);
  const connu = types.find((t) => t.type === type);
  if (!connu) {
    return "Ce type de recherche n'est pas encore pris en charge. Choisissez un autre type.";
  }
  if (!connu.autorise) {
    return connu.motif ?? `« ${connu.libelle} » n'est pas incluse dans votre plan.`;
  }
  return null;
}

interface ProprietesLigne {
  ligne: LignePointDepart;
  types: TypeRecherche[];
  onChangement: (champs: Partial<LignePointDepart>) => void;
  /** Absent = champ obligatoire, sans bouton de suppression (l'élément principal). */
  onSupprimer?: () => void;
  placeholderVide: string;
  autoFocus?: boolean;
}

/**
 * Une ligne de saisie : sélecteur de type + valeur, avec le message d'erreur
 * éventuel en dessous. Partagée entre l'élément principal (obligatoire, non
 * supprimable) et les éléments complémentaires de `SaisiePointsDepart`.
 */
export function LignePointDepartChamp({
  ligne,
  types,
  onChangement,
  onSupprimer,
  placeholderVide,
  autoFocus,
}: ProprietesLigne) {
  const type = typeEffectif(ligne);
  const connu = types.find((t) => t.type === type);
  const probleme = problemeLigne(ligne, types);

  return (
    <div className="ligne-point-depart">
      <div className="ligne" style={{ gap: 8 }}>
        <select
          value={ligne.type ?? ""}
          onChange={(e) =>
            onChangement({ type: (e.target.value || null) as TypePointDepart | null })
          }
          style={{ flex: "0 0 190px" }}
          aria-label="Type de l'élément"
        >
          <option value="">
            Détection auto{ligne.valeur.trim() && connu ? ` — ${connu.libelle}` : ""}
          </option>
          {types.map((t) => (
            <option key={t.type} value={t.type}>
              {t.libelle}
              {t.autorise ? "" : " (non inclus)"}
            </option>
          ))}
        </select>

        <input
          className="plein mono"
          value={ligne.valeur}
          onChange={(e) => onChangement({ valeur: e.target.value })}
          placeholder={
            // Sur une ligne encore vide, la détection renvoie « pseudonyme » :
            // en afficher l'exemple induirait en erreur.
            ligne.valeur.trim() || ligne.type ? connu?.exemple || "valeur à rechercher" : placeholderVide
          }
          aria-label="Valeur de l'élément"
          required={!onSupprimer}
          autoFocus={autoFocus}
        />

        {onSupprimer && (
          <button
            type="button"
            className="bouton-petit"
            onClick={onSupprimer}
            title="Retirer cet élément"
            aria-label="Retirer cet élément"
          >
            ✕
          </button>
        )}
      </div>

      {probleme && (
        <div className="aide aide-alerte">
          {probleme} {connu && !connu.autorise && <Link to="/abonnement">Voir les paliers</Link>}
        </div>
      )}
    </div>
  );
}

interface Proprietes {
  lignes: LignePointDepart[];
  onChangement: (lignes: LignePointDepart[]) => void;
  types: TypeRecherche[];
  /** Points de départ acceptés par le plan, élément principal compris ; 0 = illimité. */
  maximum: number;
  nomPlan?: string;
}

export function SaisiePointsDepart({
  lignes,
  onChangement,
  types,
  maximum,
  nomPlan,
}: Proprietes) {
  // L'élément principal occupe déjà une place dans le décompte du plan.
  // 20 est la borne acceptée par l'API, y compris pour les plans sans limite.
  const placesRestantes = maximum === 0 ? 20 : Math.max(0, maximum - 1);
  const peutAjouter = lignes.length < placesRestantes;

  // Le type de l'élément principal se choisit ailleurs (voir le champ dédié dans
  // le formulaire) : pas la peine de le reproposer ici.
  const typesProposables = types.filter((t) => t.type !== "pseudo");

  const modifier = (cle: number, champs: Partial<LignePointDepart>) =>
    onChangement(lignes.map((l) => (l.cle === cle ? { ...l, ...champs } : l)));

  const supprimer = (cle: number) => onChangement(lignes.filter((l) => l.cle !== cle));

  const ajouter = () =>
    onChangement([
      ...lignes,
      { cle: Date.now() + lignes.length, valeur: "", type: null },
    ]);

  if (placesRestantes === 0) {
    return (
      <div className="champ">
        <label>Autres éléments de départ</label>
        <div className="aide">
          Le plan {nomPlan ?? "actuel"} part d'un seul élément par investigation.{" "}
          <Link to="/abonnement">Passer à un palier supérieur</Link> pour en combiner
          plusieurs.
        </div>
      </div>
    );
  }

  return (
    <div className="champ">
      <label>Autres éléments de départ (facultatif)</label>

      {lignes.length === 0 && (
        <div className="aide" style={{ marginBottom: 8 }}>
          Chaque élément supplémentaire lance sa propre recherche, et les résultats se
          corroborent dès le premier tour.
        </div>
      )}

      {lignes.map((ligne) => (
        <LignePointDepartChamp
          key={ligne.cle}
          ligne={ligne}
          types={typesProposables}
          onChangement={(champs) => modifier(ligne.cle, champs)}
          onSupprimer={() => supprimer(ligne.cle)}
          placeholderVide="adresse électronique, téléphone, compte…"
        />
      ))}

      {peutAjouter ? (
        <button type="button" className="bouton-discret" onClick={ajouter}>
          + Ajouter un élément de départ
        </button>
      ) : (
        <div className="aide">
          Maximum atteint : le plan {nomPlan ?? "actuel"} accepte {maximum} éléments de
          départ par investigation, élément principal compris.{" "}
          <Link to="/abonnement">Voir les paliers</Link>
        </div>
      )}
    </div>
  );
}
