"""Socle des chercheurs : découverte de comptes à partir d'un point de départ.

Un **chercheur** répond à la question « à partir de cette information, que peut-on
trouver ? ». Là où un *module* enrichit un profil déjà connu, un chercheur part d'une
donnée brute et découvre des comptes ou des informations nouvelles.

Cette abstraction généralise ce qui était auparavant codé en dur autour de Maigret :
celui-ci devient un chercheur parmi d'autres, spécialisé dans les pseudonymes. Ajouter
la recherche par adresse électronique, par téléphone ou par adresse postale revient
alors à écrire un fichier dans `chercheurs/`, comme pour les modules de site.

Tous les chercheurs produisent le même type de résultat, ce qui permet de réutiliser
sans modification toute la chaîne existante : enregistrement des profils, corrélation,
construction du graphe et détection de rebonds.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.modeles.enums import TypeDonnee, TypePointDepart
from app.modules.base import InfoExtraite
from app.moteur.maigret_runner import ResultatSite

journal = logging.getLogger(__name__)

# (étape_courante, progression_estimée_en_pourcent, message)
RappelProgression = Callable[[int, int, str], None]


@dataclass
class ResultatChercheur:
    """Sortie unifiée de tout chercheur.

    Deux natures de résultats, volontairement distinguées :

    - `comptes` : des profils sur des sites, qui deviendront des nœuds « compte » et
      seront soumis au moteur de corrélation ;
    - `informations` : des données rattachées au point de départ lui-même (le nom
      derrière une adresse Gravatar, l'opérateur d'un numéro, les coordonnées d'une
      adresse postale). Elles n'appartiennent à aucun compte particulier.
    """

    entree: str
    type_entree: str
    comptes: list[ResultatSite] = field(default_factory=list)
    informations: list[InfoExtraite] = field(default_factory=list)
    nb_sources_consultees: int = 0
    duree_secondes: float = 0.0
    erreur: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def reussie(self) -> bool:
        return self.erreur is None

    def valeurs_information(self, type_donnee: TypeDonnee) -> list[str]:
        """Valeurs déjà collectées pour ce type, dans leur ordre d'ajout."""
        return [i.valeur for i in self.informations if i.type == type_donnee]

    def ajouter_information(
        self, type_donnee: TypeDonnee, valeur: Any, confiance: float = 1.0, **meta: Any
    ) -> None:
        """Ajoute une information en ignorant les valeurs vides."""
        if valeur is None:
            return
        texte = str(valeur).strip()
        if not texte or texte.lower() in {"none", "null", "n/a", "-"}:
            return
        self.informations.append(
            InfoExtraite(type=type_donnee, valeur=texte[:2000], confiance=confiance, meta=meta)
        )


class Chercheur(ABC):
    """Interface commune à tous les chercheurs.

    Pour en ajouter un : créer un fichier dans `app/moteur/chercheurs/`, hériter de
    cette classe, déclarer `type_point_depart`, implémenter `chercher`. Le registre le
    découvre automatiquement au démarrage.
    """

    #: identifiant technique du chercheur
    nom: str = ""
    #: libellé affiché dans l'interface
    libelle: str = ""
    #: exemple de saisie, affiché en aide dans le formulaire
    exemple: str = ""
    #: type de point de départ traité (voir TypePointDepart)
    type_point_depart: str = ""
    #: code de fonctionnalité exigé dans le plan de l'organisation ; vide = accessible à tous
    fonctionnalite_requise: str = ""

    @abstractmethod
    def chercher(
        self,
        valeur: str,
        options: dict[str, Any] | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatChercheur:
        """Cherche à partir de la valeur fournie."""

    def disponible(self) -> bool:
        """Le chercheur est-il utilisable en l'état (outil installé, clé présente) ?

        Un chercheur indisponible est simplement ignoré : les autres continuent.
        """
        return True

    def valider(self, valeur: str) -> str | None:
        """Vérifie et normalise la valeur d'entrée.

        Renvoie la valeur normalisée, ou None si elle ne correspond pas à ce type.
        """
        valeur = (valeur or "").strip()
        return valeur or None

    def __repr__(self) -> str:
        return f"<Chercheur {self.nom} ({self.type_point_depart})>"


def detecter_type(valeur: str) -> str:
    """Devine le type d'un point de départ saisi par l'utilisateur.

    Permet à l'interface d'accepter une saisie libre : l'analyste colle ce qu'il a,
    sans avoir à choisir un type dans une liste.
    """
    valeur = (valeur or "").strip()
    if not valeur:
        return TypePointDepart.PSEUDO.value

    if valeur.startswith(("http://", "https://")) or (
        "/" in valeur and "." in valeur.split("/")[0]
    ):
        return TypePointDepart.COMPTE.value

    if "@" in valeur and "." in valeur.split("@")[-1] and " " not in valeur:
        return TypePointDepart.EMAIL.value

    # Un numéro : essentiellement des chiffres, éventuellement un + et des séparateurs
    sans_separateurs = valeur.replace(" ", "").replace(".", "").replace("-", "").replace("/", "")
    if sans_separateurs.lstrip("+").isdigit() and 6 <= len(sans_separateurs.lstrip("+")) <= 15:
        return TypePointDepart.TELEPHONE.value

    # Une adresse postale contient typiquement un numéro et plusieurs mots
    mots = valeur.split()
    if len(mots) >= 3 and any(mot.isdigit() for mot in mots):
        return TypePointDepart.ADRESSE.value

    # Deux mots ou plus sans chiffre : plutôt un nom de personne qu'un pseudonyme
    if len(mots) >= 2 and not any(caractere.isdigit() for caractere in valeur):
        return TypePointDepart.NOM.value

    return TypePointDepart.PSEUDO.value
