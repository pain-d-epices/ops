"""Règle : similarité des biographies et des localisations déclarées.

Beaucoup de personnes réutilisent la même phrase de présentation d'un site à l'autre.
La comparaison utilise `token_set_ratio`, insensible à l'ordre des mots et aux ajouts :
« Développeur Python à Lyon » et « Lyon — développeur Python, amateur de vélo »
restent proches.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from app.modeles.enums import TypeDonnee
from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    RegleCorrelation,
    ResultatRegle,
    normaliser,
)

# En deçà, la comparaison n'a pas de sens : « dev » ressemble à trop de choses.
LONGUEUR_MINIMALE_BIO = 15


class RegleContenuBio(RegleCorrelation):
    nom = "contenu_bio"
    libelle = "Similarité de la biographie"

    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        bio = self._bio_utilisable(profil)
        localisation = normaliser(profil.premiere_valeur(TypeDonnee.LOCALISATION) or "")

        if not bio and not localisation:
            return None

        seuil = float(self.config.get("seuil_similarite", 0.60))
        meilleur_ratio = 0.0
        meilleur_site = ""
        localisations_identiques: list[str] = []

        for autre in contexte.autres_profils(profil):
            if autre.verdict_manuel == "faux_positif":
                continue

            if bio:
                bio_autre = self._bio_utilisable(autre)
                if bio_autre:
                    ratio = fuzz.token_set_ratio(bio, bio_autre) / 100.0
                    if ratio > meilleur_ratio:
                        meilleur_ratio, meilleur_site = ratio, autre.site_nom

            if localisation:
                localisation_autre = normaliser(autre.premiere_valeur(TypeDonnee.LOCALISATION) or "")
                if localisation_autre and localisation_autre == localisation:
                    localisations_identiques.append(autre.site_nom)

        if meilleur_ratio >= seuil:
            score = 0.5 + 0.5 * (meilleur_ratio - seuil) / max(1e-6, 1.0 - seuil)
            return ResultatRegle(
                score=round(min(1.0, score), 3),
                explication=(
                    f"Biographie très proche de celle du profil {meilleur_site} "
                    f"({meilleur_ratio:.0%} de similarité)"
                ),
                detail={"ratio": round(meilleur_ratio, 3), "site": meilleur_site},
            )

        if localisations_identiques:
            sites = ", ".join(sorted(set(localisations_identiques)))
            return ResultatRegle(
                score=0.45,
                explication=f"Même localisation déclarée que sur {sites}",
                detail={"localisation": localisation, "sites": localisations_identiques},
            )

        return None

    @staticmethod
    def _bio_utilisable(profil: ProfilEvalue) -> str:
        bio = normaliser(profil.premiere_valeur(TypeDonnee.BIO) or "")
        return bio if len(bio) >= LONGUEUR_MINIMALE_BIO else ""
