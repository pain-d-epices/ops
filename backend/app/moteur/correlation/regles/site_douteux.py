"""Règle : pénalités sur les résultats structurellement peu fiables.

Deux sources de faux positifs bien identifiées :

  1. La recherche approximative de Maigret (`is_similar`) : le compte n'a pas été
     trouvé à une URL exacte mais via un moteur de recherche interne au site. Sur un
     pseudonyme courant, cela remonte des dizaines d'inconnus.
  2. Les sites qui répondent « ce compte existe » quel que soit le pseudonyme testé.
     Leur liste est maintenue dans config.yaml, pas dans le code.
"""

from __future__ import annotations

from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    RegleCorrelation,
    ResultatRegle,
)


class RegleSiteDouteux(RegleCorrelation):
    nom = "site_douteux"
    libelle = "Fiabilité du résultat"

    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        domaines_douteux = {d.lower() for d in self.config.get("domaines", [])}
        motifs: list[str] = []
        score = 0.0

        if profil.site_domaine.lower() in domaines_douteux:
            motifs.append("site connu pour signaler des comptes inexistants")
            score -= 0.7

        if profil.est_similaire:
            motifs.append("compte trouvé par recherche approximative et non par adresse exacte")
            score -= 0.5

        if not motifs:
            return None

        return ResultatRegle(
            score=max(-1.0, score),
            explication="Résultat à vérifier : " + " ; ".join(motifs),
            detail={"motifs": motifs},
        )
