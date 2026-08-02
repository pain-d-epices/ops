"""Socle du moteur de corrélation : structures de données et interface des règles.

Le moteur travaille sur des structures **pures** (sans SQLAlchemy) : il est ainsi
testable sans base de données, et les règles restent indépendantes du stockage.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.modeles.enums import TypeDonnee


def normaliser(valeur: str) -> str:
    """Forme comparable d'une chaîne : minuscules, sans accent ni ponctuation.

    « Jean-Luc P. » et « jean luc p » deviennent équivalents, ce qui évite de compter
    comme différentes deux valeurs que n'importe quel humain jugerait identiques.
    """
    if not valeur:
        return ""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFKD", valeur) if not unicodedata.combining(c)
    )
    nettoye = re.sub(r"[^a-z0-9]+", " ", sans_accent.lower())
    return " ".join(nettoye.split())


def normaliser_pseudo(pseudo: str) -> str:
    """Normalisation spécifique aux pseudonymes : on retire aussi les espaces.

    Les séparateurs (« john.doe », « john_doe », « john-doe ») désignent en pratique
    le même identifiant selon les sites.
    """
    return normaliser(pseudo).replace(" ", "")


MOTIF_SUFFIXE_NUMERIQUE = re.compile(r"^(.*?)[_\-.]?(\d{1,4})$")


def separer_suffixe_numerique(pseudo: str) -> tuple[str, str | None]:
    """« john92 » -> (« john », « 92 »). Sinon (pseudo, None)."""
    correspondance = MOTIF_SUFFIXE_NUMERIQUE.match(pseudo)
    if not correspondance:
        return pseudo, None
    base, chiffres = correspondance.group(1), correspondance.group(2)
    if len(base) < 3:  # « 12 » ou « ab1 » : la base est trop courte pour être significative
        return pseudo, None
    return base, chiffres


@dataclass
class ProfilEvalue:
    """Vue d'un profil telle que la voit le moteur de corrélation."""

    identifiant: str
    site_nom: str
    site_domaine: str
    url: str
    pseudo_sur_le_site: str
    profondeur: int = 0
    # Trouvé par recherche approximative de Maigret : signal fort de faux positif
    est_similaire: bool = False
    tags: list[str] = field(default_factory=list)
    # Données extraites, regroupées par type : {"email": ["a@b.fr"], "bio": ["..."]}
    donnees: dict[str, list[str]] = field(default_factory=dict)
    verdict_manuel: str | None = None

    def valeurs(self, type_donnee: TypeDonnee | str) -> list[str]:
        cle = type_donnee.value if isinstance(type_donnee, TypeDonnee) else type_donnee
        return self.donnees.get(cle, [])

    def premiere_valeur(self, type_donnee: TypeDonnee | str) -> str | None:
        valeurs = self.valeurs(type_donnee)
        return valeurs[0] if valeurs else None

    def date_creation(self) -> datetime | None:
        """Date de création du compte, tolérante sur le format rencontré selon les sites."""
        brut = self.premiere_valeur(TypeDonnee.DATE_CREATION)
        if not brut:
            return None
        return analyser_date(brut)


def analyser_date(brut: str) -> datetime | None:
    """Analyse une date issue d'un site tiers (ISO, horodatage Unix, formats courants)."""
    brut = str(brut).strip()
    if not brut:
        return None

    # Horodatage Unix (StackOverflow, Twitch et d'autres le renvoient ainsi)
    if brut.isdigit() and 8 <= len(brut) <= 13:
        try:
            valeur = int(brut)
            if len(brut) == 13:  # millisecondes
                valeur //= 1000
            return datetime.utcfromtimestamp(valeur)
        except (ValueError, OSError, OverflowError):
            return None

    for format_date in (
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y",
    ):
        try:
            return datetime.strptime(brut, format_date).replace(tzinfo=None)
        except ValueError:
            continue
    return None


@dataclass
class ContexteCorrelation:
    """Tout ce dont les règles disposent pour évaluer un profil.

    Les règles croisées (avatar identique, lien réciproque, email partagé) ont besoin
    de voir l'ensemble des profils : c'est la comparaison entre comptes qui permet de
    départager un vrai profil d'une homonymie.
    """

    pseudos_reference: list[str]
    profils: list[ProfilEvalue]
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def pseudos_reference_normalises(self) -> list[str]:
        return [normaliser_pseudo(p) for p in self.pseudos_reference if p]

    def autres_profils(self, profil: ProfilEvalue) -> list[ProfilEvalue]:
        return [p for p in self.profils if p.identifiant != profil.identifiant]


@dataclass
class ResultatRegle:
    """Verdict d'une règle pour un profil.

    `score` va de -1 à 1 : une valeur négative est une pénalité (indice de faux positif).
    Une règle qui ne peut pas se prononcer renvoie None et est **exclue du calcul**,
    au lieu de contribuer un zéro qui pénaliserait injustement le profil. Sans cela,
    un compte non enrichi plafonnerait mécaniquement à un score très bas.
    """

    score: float
    explication: str
    detail: dict[str, Any] = field(default_factory=dict)


class RegleCorrelation(ABC):
    """Interface commune à toutes les règles de scoring.

    Pour ajouter une règle : créer un fichier dans `regles/`, hériter de cette classe,
    et déclarer son poids dans `config.yaml`. Le registre la découvre automatiquement.
    """

    #: identifiant technique, doit correspondre à la clé dans config.yaml
    nom: str = ""
    #: libellé affiché dans l'interface
    libelle: str = ""
    #: cette règle compte-t-elle comme un signal indépendant pour lever le plafond
    #: de score (voir `scoreur.PLAFONDS_PAR_NOMBRE_DE_SIGNAUX`) ? À mettre à `False`
    #: pour un signal corroborant mais non discriminant (ex. cohérence temporelle :
    #: presque tous les comptes d'un pseudonyme courant passent ce test, y compris
    #: entre parfaits homonymes ; le laisser compter suffisait à faire passer un
    #: pseudonyme seul de « confiance moyenne » à « confiance élevée »).
    compte_pour_plafond: bool = True

    def __init__(self, poids: float = 1.0, config: dict[str, Any] | None = None):
        self.poids = poids
        self.config = config or {}

    @abstractmethod
    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        """Évalue un profil. Renvoie None si la règle ne peut pas se prononcer."""

    def __repr__(self) -> str:
        return f"<Regle {self.nom} poids={self.poids}>"
