"""Agrégation des règles en un score de confiance explicable.

Deux principes gouvernent le calcul :

1. **Une règle qui ne peut pas se prononcer est exclue du calcul**, au lieu de
   contribuer un zéro. Sans cela, un compte non enrichi (palier gratuit, ou site sans
   module dédié) serait mécaniquement condamné à un score très bas alors qu'aucun
   élément ne joue contre lui.

2. **Un seul signal ne suffit jamais à atteindre la confiance maximale.** Un pseudonyme
   identique est un indice, pas une preuve : sur un pseudonyme courant, des dizaines de
   personnes sans lien entre elles le partagent. Le score est donc plafonné selon le
   nombre de signaux positifs indépendants qui corroborent l'appartenance.

3. **Un compte sur site à caractère sexuel n'est jamais présenté comme probable sans
   corroboration indépendante.** C'est la donnée la plus lourde de conséquences qu'une
   investigation puisse produire sur une personne : l'annoncer sur la seule foi d'un
   pseudonyme identique est une imputation diffamatoire, et au RGPD un traitement de
   données de l'article 9 fondé sur un faux positif.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import config_metier
from app.modeles.enums import NiveauConfiance
from app.moteur.correlation.base import ContexteCorrelation, ProfilEvalue
from app.moteur.correlation.registre import charger_regles
from app.moteur.sites_sensibles import est_site_sensible

journal = logging.getLogger(__name__)

# Plafond du score selon le nombre de signaux positifs indépendants.
# Au-delà de trois signaux concordants, aucun plafonnement.
# 65 pour un signal unique : volontairement sous le seuil de « confiance élevée » (70),
# pour qu'un profil reposant sur le seul pseudonyme ne soit jamais présenté comme sûr.
PLAFONDS_PAR_NOMBRE_DE_SIGNAUX = {0: 20, 1: 65, 2: 85}
PLAFOND_MAXIMAL = 100

# Un signal n'est « positif » qu'au-dessus de ce score : une règle qui se prononce
# faiblement en faveur du profil ne constitue pas une corroboration.
SEUIL_SIGNAL_POSITIF = 0.5

# Nombre de signaux positifs indépendants exigés avant qu'un compte sur site à
# caractère sexuel puisse dépasser la confiance « faible ». Un pseudonyme identique
# seul n'y suffit donc jamais : il faut un avatar commun, une adresse partagée ou un
# lien explicite — quelque chose que l'homonymie ne produit pas.
SIGNAUX_MINIMAUX_SITE_SENSIBLE = 2


@dataclass
class ContributionRegle:
    regle: str
    libelle: str
    score_regle: float
    poids: float
    contribution_points: float
    explication: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultatScoring:
    profil_id: str
    score: int                       # 0..100
    niveau: NiveauConfiance
    contributions: list[ContributionRegle] = field(default_factory=list)
    plafond_applique: int | None = None
    nb_signaux_positifs: int = 0

    @property
    def explications(self) -> list[str]:
        return [c.explication for c in self.contributions]


def niveau_depuis_score(score: int) -> NiveauConfiance:
    seuils = config_metier().obtenir("correlation.seuils", {}) or {}
    if score >= int(seuils.get("eleve", 70)):
        return NiveauConfiance.ELEVE
    if score >= int(seuils.get("moyen", 40)):
        return NiveauConfiance.MOYEN
    return NiveauConfiance.FAIBLE


def _plafond_site_sensible() -> int:
    """Score maximal d'un compte sensible non corroboré : juste sous « confiance moyenne ».

    Calculé depuis le seuil configuré plutôt que codé en dur : abaisser
    `correlation.seuils.moyen` dans config.yaml ne doit pas faire réapparaître ces
    comptes au-dessus du seuil.
    """
    seuils = config_metier().obtenir("correlation.seuils", {}) or {}
    return max(0, int(seuils.get("moyen", 40)) - 1)


def scorer_profil(profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatScoring:
    """Calcule le score d'un profil et détaille la contribution de chaque règle."""
    contributions: list[ContributionRegle] = []
    somme_ponderee = 0.0
    somme_poids = 0.0
    nb_signaux_positifs = 0

    for regle in charger_regles():
        try:
            resultat = regle.evaluer(profil, contexte)
        except Exception:  # noqa: BLE001 — une règle défaillante ne doit pas invalider tout le score
            journal.exception("Règle « %s » en erreur sur le profil %s", regle.nom, profil.identifiant)
            continue

        if resultat is None:
            continue  # la règle s'abstient : elle ne pèse ni dans un sens ni dans l'autre

        score_borne = max(-1.0, min(1.0, resultat.score))
        somme_ponderee += score_borne * regle.poids
        somme_poids += regle.poids
        if score_borne >= SEUIL_SIGNAL_POSITIF and regle.compte_pour_plafond:
            nb_signaux_positifs += 1

        contributions.append(
            ContributionRegle(
                regle=regle.nom,
                libelle=regle.libelle,
                score_regle=round(score_borne, 3),
                poids=regle.poids,
                contribution_points=round(score_borne * regle.poids, 3),
                explication=resultat.explication,
                detail=resultat.detail,
            )
        )

    if somme_poids == 0:
        score_final = 0
        plafond = None
    else:
        moyenne = somme_ponderee / somme_poids          # -1 .. 1
        brut = max(0.0, min(1.0, moyenne)) * 100        # les scores négatifs deviennent 0
        plafond = PLAFONDS_PAR_NOMBRE_DE_SIGNAUX.get(nb_signaux_positifs, PLAFOND_MAXIMAL)

        # Site à caractère sexuel non corroboré : maintenu sous le seuil de confiance
        # « moyenne », pour qu'il se présente comme une piste à vérifier et non comme
        # une conclusion. Voir le principe 3 en tête de module.
        if (
            nb_signaux_positifs < SIGNAUX_MINIMAUX_SITE_SENSIBLE
            and est_site_sensible(profil.site_nom, profil.site_domaine, profil.tags)
        ):
            plafond = min(plafond, _plafond_site_sensible())

        score_final = int(round(min(brut, plafond)))
        # Le plafond n'est signalé que s'il a réellement rogné le score
        plafond = plafond if brut > plafond else None

    # Un verdict humain prime toujours sur le calcul : l'analyste a vu le profil.
    if profil.verdict_manuel == "faux_positif":
        score_final = 0
    elif profil.verdict_manuel == "valide":
        score_final = 100

    return ResultatScoring(
        profil_id=profil.identifiant,
        score=score_final,
        niveau=niveau_depuis_score(score_final),
        contributions=contributions,
        plafond_applique=plafond,
        nb_signaux_positifs=nb_signaux_positifs,
    )


def scorer_tous(contexte: ContexteCorrelation) -> list[ResultatScoring]:
    """Score l'ensemble des profils d'une investigation.

    Les règles croisées (avatar, email, liens) comparant les profils entre eux, le
    score d'un profil dépend des autres : il faut donc toujours rescorer l'ensemble
    après l'arrivée de nouvelles données, jamais un profil isolément.
    """
    return [scorer_profil(profil, contexte) for profil in contexte.profils]
