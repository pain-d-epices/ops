/** Vue tableau des comptes trouvés : alternative au graphe, triable et filtrable. */

import { useState } from "react";

import { useProfils, useRelancerCorrelation, type FiltresProfils } from "../api/hooks";
import { BadgeConfiance, Chargement, EtatVide, MessageErreur } from "./ui";

interface Proprietes {
  investigationId: string;
  profilSelectionne: string | null;
  onSelectionner: (profilId: string) => void;
}

export function TableauProfils({
  investigationId,
  profilSelectionne,
  onSelectionner,
}: Proprietes) {
  const [filtres, setFiltres] = useState<FiltresProfils>({
    score_minimal: 0,
    tri: "score",
    inclure_faux_positifs: false,
  });

  const { data: profils, isLoading, error } = useProfils(investigationId, filtres);
  const relancer = useRelancerCorrelation();

  const changerTri = (colonne: FiltresProfils["tri"]) =>
    setFiltres((precedent) => ({ ...precedent, tri: colonne }));

  return (
    <div>
      <div className="carte-titre enveloppe">
        <div className="ligne enveloppe" style={{ gap: 14 }}>
          <div className="ligne" style={{ gap: 8 }}>
            <label htmlFor="score-min" style={{ margin: 0, whiteSpace: "nowrap" }}>
              Score minimal
            </label>
            <input
              id="score-min"
              type="number"
              min={0}
              max={100}
              step={5}
              value={filtres.score_minimal ?? 0}
              onChange={(e) =>
                setFiltres((p) => ({ ...p, score_minimal: Number(e.target.value) }))
              }
              style={{ width: 80 }}
            />
          </div>

          <div className="ligne" style={{ gap: 8 }}>
            <label htmlFor="niveau" style={{ margin: 0, whiteSpace: "nowrap" }}>
              Niveau
            </label>
            <select
              id="niveau"
              value={filtres.niveau ?? ""}
              onChange={(e) =>
                setFiltres((p) => ({ ...p, niveau: e.target.value || undefined }))
              }
              style={{ width: 150 }}
            >
              <option value="">Tous</option>
              <option value="eleve">Confiance élevée</option>
              <option value="moyen">Confiance moyenne</option>
              <option value="faible">Confiance faible</option>
            </select>
          </div>

          <label className="case-a-cocher" style={{ margin: 0 }}>
            <input
              type="checkbox"
              checked={filtres.inclure_faux_positifs ?? false}
              onChange={(e) =>
                setFiltres((p) => ({ ...p, inclure_faux_positifs: e.target.checked }))
              }
            />
            <span>Afficher les faux positifs</span>
          </label>
        </div>

        <button type="button"
          className="bouton-petit"
          onClick={() => relancer.mutate(investigationId)}
          disabled={relancer.isPending}
          title="Recalcule les scores sans relancer de recherche réseau"
        >
          {relancer.isPending ? <span className="chargement" /> : "Recalculer les scores"}
        </button>
      </div>

      {isLoading && <Chargement />}
      {error && <MessageErreur>Impossible de charger les comptes.</MessageErreur>}

      {profils && profils.length === 0 && (
        <div className="carte">
          <EtatVide titre="Aucun compte ne correspond aux filtres">
            Abaissez le score minimal pour élargir la sélection.
          </EtatVide>
        </div>
      )}

      {profils && profils.length > 0 && (
        <div className="carte" style={{ padding: 0, overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th className="triable" onClick={() => changerTri("site")}>
                  Site {filtres.tri === "site" && "▾"}
                </th>
                <th>Pseudonyme</th>
                <th className="triable" onClick={() => changerTri("score")}>
                  Score {filtres.tri === "score" && "▾"}
                </th>
                <th className="triable" onClick={() => changerTri("profondeur")}>
                  Rebond {filtres.tri === "profondeur" && "▾"}
                </th>
                <th>Enrichi</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {profils.map((profil) => (
                <tr
                  key={profil.id}
                  className={profil.id === profilSelectionne ? "selectionnee" : ""}
                  onClick={() => onSelectionner(profil.id)}
                  style={{
                    cursor: "pointer",
                    opacity: profil.verdict_manuel === "faux_positif" ? 0.5 : 1,
                  }}
                >
                  <td className="gras">{profil.site_nom}</td>
                  <td className="mono">{profil.pseudo_sur_le_site}</td>
                  <td>
                    <BadgeConfiance niveau={profil.niveau} score={profil.score_confiance} />
                  </td>
                  <td className="attenue">
                    {profil.profondeur === 0 ? "direct" : `niveau ${profil.profondeur}`}
                  </td>
                  <td className="attenue petit">
                    {profil.enrichi ? (profil.module_utilise ?? "oui") : "—"}
                  </td>
                  <td>
                    {profil.verdict_manuel === "valide" && (
                      <span className="badge badge-eleve">validé</span>
                    )}
                    {profil.verdict_manuel === "faux_positif" && (
                      <span className="badge badge-danger">faux positif</span>
                    )}
                    {!profil.verdict_manuel && <span className="faible">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="aide" style={{ marginTop: 10 }}>
        Cliquez sur une ligne pour afficher le détail du compte et l'explication de son
        score. Un verdict manuel modifie le score des autres comptes : les règles de
        corrélation les comparent entre eux.
      </div>
    </div>
  );
}
