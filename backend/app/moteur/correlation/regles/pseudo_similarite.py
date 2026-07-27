"""Règle : cohérence entre le pseudonyme trouvé et le pseudonyme recherché."""

from __future__ import annotations

from rapidfuzz import fuzz

from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    RegleCorrelation,
    ResultatRegle,
    normaliser_pseudo,
    separer_suffixe_numerique,
)


class ReglePseudoSimilarite(RegleCorrelation):
    nom = "pseudo_similarite"
    libelle = "Cohérence du pseudonyme"

    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        references = contexte.pseudos_reference_normalises
        if not references:
            return None

        candidat = normaliser_pseudo(profil.pseudo_sur_le_site)
        if not candidat:
            return None

        seuil = float(self.config.get("seuil_similarite", 0.72))
        tolerance_suffixe = bool(self.config.get("tolerance_suffixe_numerique", True))

        meilleur_score = -1.0
        meilleure_explication = ""
        meilleur_detail: dict[str, object] = {}

        for reference in references:
            score, explication, detail = self._comparer(candidat, reference, seuil, tolerance_suffixe)
            if score > meilleur_score:
                meilleur_score, meilleure_explication, meilleur_detail = score, explication, detail

        return ResultatRegle(
            score=meilleur_score,
            explication=meilleure_explication,
            detail=meilleur_detail,
        )

    def _comparer(
        self, candidat: str, reference: str, seuil: float, tolerance_suffixe: bool
    ) -> tuple[float, str, dict[str, object]]:
        if candidat == reference:
            return 1.0, f"Pseudonyme identique à « {reference} »", {"type": "exact"}

        if tolerance_suffixe:
            base_candidat, suffixe_candidat = separer_suffixe_numerique(candidat)
            base_reference, suffixe_reference = separer_suffixe_numerique(reference)
            if base_candidat == base_reference and (suffixe_candidat or suffixe_reference):
                # « john » et « john92 » : variante extrêmement courante, mais pas une
                # certitude — un homonyme peut lui aussi ajouter des chiffres.
                return (
                    0.85,
                    f"Même racine que « {reference} », avec un suffixe numérique",
                    {"type": "suffixe_numerique", "base": base_candidat},
                )

        ratio = fuzz.ratio(candidat, reference) / 100.0
        if ratio >= seuil:
            # Remise à l'échelle : juste au-dessus du seuil ne doit pas valoir autant
            # qu'une quasi-correspondance.
            score = 0.4 + 0.4 * (ratio - seuil) / max(1e-6, 1.0 - seuil)
            return (
                round(score, 3),
                f"Pseudonyme proche de « {reference} » (similarité {ratio:.0%})",
                {"type": "approximatif", "ratio": round(ratio, 3)},
            )

        # Pseudonyme trop éloigné : indice de faux positif, pas simple absence de preuve.
        return (
            -0.4,
            f"Pseudonyme éloigné de « {reference} » (similarité {ratio:.0%})",
            {"type": "eloigne", "ratio": round(ratio, 3)},
        )
