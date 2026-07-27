"""Règle : cohérence des dates de création de comptes.

Signal faible mais utile pour écarter les homonymies flagrantes : un compte ouvert
quinze ans avant tous les autres appartient probablement à quelqu'un d'autre.
Le poids de cette règle est volontairement bas dans config.yaml.
"""

from __future__ import annotations

import statistics
from datetime import datetime

from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    RegleCorrelation,
    ResultatRegle,
)


class RegleCoherenceTemporelle(RegleCorrelation):
    nom = "coherence_temporelle"
    libelle = "Cohérence des dates de création"

    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        date_profil = profil.date_creation()
        if date_profil is None:
            return None

        autres_dates: list[datetime] = []
        for autre in contexte.autres_profils(profil):
            if autre.verdict_manuel == "faux_positif":
                continue
            date_autre = autre.date_creation()
            if date_autre is not None:
                autres_dates.append(date_autre)

        # Comparer une date à elle seule n'a aucun sens : il faut au moins deux autres
        # comptes datés pour que la médiane soit un repère un tant soit peu solide.
        if len(autres_dates) < 2:
            return None

        mediane = statistics.median(
            [date.timestamp() for date in sorted(autres_dates)]
        )
        ecart_jours = abs(date_profil.timestamp() - mediane) / 86400
        ecart_max = float(self.config.get("ecart_max_jours", 1095))

        if ecart_jours <= ecart_max:
            score = 1.0 - (ecart_jours / ecart_max) * 0.5   # de 1.0 (identique) à 0.5 (limite)
            return ResultatRegle(
                score=round(score, 3),
                explication=(
                    f"Date de création cohérente avec les autres comptes "
                    f"(écart de {int(ecart_jours)} jours)"
                ),
                detail={"ecart_jours": int(ecart_jours)},
            )

        return ResultatRegle(
            score=-0.3,
            explication=(
                f"Date de création très éloignée des autres comptes "
                f"(écart de {int(ecart_jours)} jours)"
            ),
            detail={"ecart_jours": int(ecart_jours)},
        )
