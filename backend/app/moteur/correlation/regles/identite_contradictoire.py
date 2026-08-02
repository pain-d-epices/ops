"""Règle : l'identité déclarée sur le compte désigne-t-elle bien la même personne ?

C'est la seule règle qui sait dire **non**. Les autres ne savent qu'ajouter de la
confiance : un compte homonyme, dont rien ne contredit l'appartenance, conserve donc
le score que lui vaut son seul pseudonyme identique.

Or l'homonymie est le mode d'échec dominant de la recherche par pseudonyme. Vérifié à
la main le 02/08/2026 sur « torvalds », en ouvrant les comptes remontés : la plupart
existent réellement, mais appartiennent à d'autres personnes —
`instagram.com/torvalds` déclare « Marco Migozzi », `untappd.com/torvalds`
« Torvald Storaas », `fl.ru/torvalds` « Alexandr Torvalds », et le compte Steam
« WTF Gaming », domicilié en Indonésie. Le moteur disposait de ces noms — les modules
les avaient extraits — et les laissait malgré tout à 65 %, « confiance moyenne ».

Deux signaux, du plus discriminant au plus faible :

1. **Le nom déclaré.** Une identité nominative (au moins deux mots) qui ne partage
   aucune racine ni avec le pseudonyme recherché, ni avec un nom déclaré sur un autre
   compte, désigne selon toute vraisemblance quelqu'un d'autre. Le même raisonnement
   filtre déjà les rebonds (voir `moteur/pivot/detecteur.py`) : il valait pour décider
   d'une relance, il vaut pour décider d'un score.

2. **La localisation**, à défaut de nom exploitable. Signal plus faible et pénalité
   plus légère : on déménage, on renseigne un pays d'origine plutôt qu'un domicile, et
   les comptes de jeu affichent volontiers une localisation fantaisiste.

L'exigence de **deux mots** pour le nom est ce qui rend la règle sûre. Un nom
d'affichage d'un seul terme (« NaraKa », « ken », un pseudonyme stylisé) n'est pas une
identité civile : la règle s'abstient plutôt que de pénaliser un compte légitime dont
le propriétaire n'a simplement pas mis son vrai nom.
"""

from __future__ import annotations

from app.modeles.enums import TypeDonnee
from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    RegleCorrelation,
    ResultatRegle,
    normaliser,
    normaliser_pseudo,
)

#: Un nom d'identité civile compte au moins deux mots (« Linus Torvalds »). En deçà,
#: c'est un pseudonyme d'affichage, sur lequel la règle ne se prononce pas.
MOTS_MINIMAUX_NOM = 2

#: Sous cette longueur, la comparaison de racines n'a plus de sens : trop de chaînes
#: courtes se contiennent l'une l'autre par accident.
LONGUEUR_MINIMALE_RACINE = 4


def _partagent_une_racine(a: str, b: str) -> bool:
    """L'une des deux chaînes compactes contient-elle l'autre ?

    « linustorvalds » et « torvalds » partagent une racine ; « marcomigozzi » et
    « torvalds » n'en partagent aucune.
    """
    if len(a) < LONGUEUR_MINIMALE_RACINE or len(b) < LONGUEUR_MINIMALE_RACINE:
        return False
    return a in b or b in a


def _apporte_plus_que_la_reference(nom_affiche: str, reference: str) -> bool:
    """Le nom contient-il un mot que le pseudonyme recherché n'explique pas ?

    « Linus Torvalds » en apporte un (« linus ») ; « Torvalds Torvalds » aucun — ce
    n'est que le nom d'utilisateur recopié par le site dans le champ « nom ».
    """
    for mot in normaliser(nom_affiche).split():
        if not _partagent_une_racine(mot, reference) and mot != reference:
            return True
    return False


class RegleIdentiteContradictoire(RegleCorrelation):
    nom = "identite_contradictoire"
    libelle = "Cohérence de l'identité déclarée"

    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        resultat = self._evaluer_nom(profil, contexte)
        if resultat is not None:
            return resultat
        return self._evaluer_localisation(profil, contexte)

    # --- 1. Nom déclaré ----------------------------------------------------

    def _evaluer_nom(
        self, profil: ProfilEvalue, contexte: ContexteCorrelation
    ) -> ResultatRegle | None:
        noms = self._noms_nominatifs(profil)
        if not noms:
            return None

        references = [r for r in contexte.pseudos_reference_normalises if r]

        for nom_affiche, nom_compact in noms:
            for reference in references:
                if not _partagent_une_racine(nom_compact, reference):
                    continue
                # Beaucoup de sites remplissent le nom affiché avec le nom
                # d'utilisateur : « Torvalds Torvalds » sur SoundCloud, relevé le
                # 02/08/2026. Le « nom » ne dit alors rien de plus que le pseudonyme,
                # et le compter comme un second signal reviendrait à faire voter deux
                # fois la même information — assez pour hisser un inconnu en confiance
                # élevée. Il faut donc au moins un mot que le pseudonyme n'explique pas.
                if not _apporte_plus_que_la_reference(nom_affiche, reference):
                    continue
                return ResultatRegle(
                    score=0.6,
                    explication=(
                        f"Nom déclaré « {nom_affiche} » cohérent avec le pseudonyme "
                        f"recherché « {reference} »"
                    ),
                    detail={"nom": nom_affiche, "reference": reference},
                )

        # Le nom ne rappelle pas le pseudonyme recherché. Il peut malgré tout être
        # déclaré à l'identique sur un autre compte — mais **cela ne le rapproche pas
        # de la cible**. Constaté en conditions réelles le 02/08/2026 : sur
        # « torvalds », Instagram et Pinterest déclarent tous deux « Marco Migozzi ».
        # Se corroborer mutuellement les faisait passer tous les deux en confiance
        # élevée, alors que la conclusion correcte est l'inverse — un tiers possède ce
        # pseudonyme sur plusieurs plateformes.
        #
        # La pénalité est donc maintenue, simplement atténuée : deux comptes cohérents
        # entre eux valent mieux qu'un nom isolé, sans jamais suffire à conclure. Un
        # compte réellement rattaché à la cible se rattrape par les autres règles
        # (avatar commun, adresse partagée, lien explicite), qui, elles, prouvent
        # quelque chose.
        nom_affiche, nom_compact = noms[0]
        for autre in contexte.autres_profils(profil):
            if autre.verdict_manuel == "faux_positif":
                continue
            for _, nom_autre_compact in self._noms_nominatifs(autre):
                if _partagent_une_racine(nom_compact, nom_autre_compact):
                    return ResultatRegle(
                        score=-0.25,
                        explication=(
                            f"Le compte déclare « {nom_affiche} », sans rapport avec le "
                            f"pseudonyme recherché — nom également porté par le profil "
                            f"{autre.site_nom}, vraisemblablement le même tiers"
                        ),
                        detail={
                            "nom": nom_affiche,
                            "site": autre.site_nom,
                            "type": "nom_etranger_partage",
                        },
                    )

        return ResultatRegle(
            score=-0.7,
            explication=(
                f"Le compte déclare « {nom_affiche} », sans rapport avec le pseudonyme "
                f"recherché ni avec les autres comptes : homonyme probable"
            ),
            detail={"nom": nom_affiche, "type": "nom_etranger"},
        )

    # --- 2. Localisation, à défaut de nom ----------------------------------

    def _evaluer_localisation(
        self, profil: ProfilEvalue, contexte: ContexteCorrelation
    ) -> ResultatRegle | None:
        lieu = normaliser(profil.premiere_valeur(TypeDonnee.LOCALISATION) or "")
        if not lieu:
            return None

        mots_lieu = set(lieu.split())
        lieux_etrangers: list[str] = []

        for autre in contexte.autres_profils(profil):
            if autre.verdict_manuel == "faux_positif":
                continue
            lieu_autre = normaliser(autre.premiere_valeur(TypeDonnee.LOCALISATION) or "")
            if not lieu_autre:
                continue
            if mots_lieu & set(lieu_autre.split()):
                # Un seul recoupement suffit à considérer les localisations comme
                # compatibles : « Portland » et « Portland, OR » désignent le même lieu.
                return None
            lieux_etrangers.append(lieu_autre)

        # Une seule localisation divergente peut venir d'un déménagement ; il en faut
        # plusieurs, toutes différentes de celle-ci, pour que le compte se détache.
        if len(lieux_etrangers) < int(self.config.get("lieux_divergents_minimum", 2)):
            return None

        return ResultatRegle(
            score=-0.4,
            explication=(
                f"Localisation déclarée « {lieu} » incompatible avec celle des autres "
                f"comptes ({', '.join(sorted(set(lieux_etrangers))[:3])})"
            ),
            detail={"localisation": lieu, "autres": sorted(set(lieux_etrangers))},
        )

    # --- Utilitaires -------------------------------------------------------

    @staticmethod
    def _noms_nominatifs(profil: ProfilEvalue) -> list[tuple[str, str]]:
        """Noms d'au moins deux mots déclarés par ce compte, forme affichée et compacte."""
        noms: list[tuple[str, str]] = []
        for type_donnee in (TypeDonnee.NOM_REEL, TypeDonnee.NOM_AFFICHE):
            for valeur in profil.valeurs(type_donnee):
                affiche = (valeur or "").strip()
                if len(affiche.split()) < MOTS_MINIMAUX_NOM:
                    continue
                compact = normaliser_pseudo(affiche)
                if len(compact) >= LONGUEUR_MINIMALE_RACINE:
                    noms.append((affiche, compact))
        return noms
