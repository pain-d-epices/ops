"""Détection des données pivotables dans les informations extraites.

Un « pivot » est une information qui permet de repartir en recherche : un pseudonyme
alternatif relance Maigret, un lien vers un site couvert par un module déclenche un
enrichissement direct, une adresse électronique ouvre les deux voies.

Le filtrage effectué ici est ce qui empêche l'explosion combinatoire : sans lui, la
moindre bio contenant cinq liens multiplierait les recherches à chaque niveau.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.config import config_metier
from app.modeles.enums import TypeDonnee
from app.moteur.correlation.base import normaliser_pseudo

journal = logging.getLogger(__name__)

ACTION_RECHERCHE = "recherche_maigret"
ACTION_ENRICHISSEMENT = "enrichissement_direct"

# Pseudonymes trop génériques pour désigner quelqu'un : les rechercher produirait
# des milliers de comptes sans rapport avec la cible.
PSEUDOS_INEXPLOITABLES = {
    "admin", "user", "test", "info", "contact", "support", "root", "guest",
    "home", "index", "about", "profile", "login", "signup", "null", "none",
    "www", "mail", "email", "blog", "news", "help", "team", "official",
}

MOTIF_PSEUDO_VALIDE = re.compile(r"^[A-Za-z0-9_.\-]{3,40}$")


@dataclass
class Pivot:
    """Une opportunité de pivot détectée, avant décision d'exécution."""

    type_pivot: str          # correspond à TypeDonnee
    valeur: str
    valeur_normalisee: str
    action: str
    libelle: str             # texte affiché à l'analyste : « email trouvé dans la bio GitHub »
    profil_source_id: str | None = None
    donnee_source_id: str | None = None
    confiance: float = 1.0
    meta: dict[str, str] = field(default_factory=dict)


@dataclass
class DonneeCandidate:
    """Vue minimale d'une donnée extraite, pour la détection de pivots."""

    identifiant: str
    type: str
    valeur: str
    valeur_normalisee: str
    #: Compte d'origine. Nul lorsque la donnée vient d'un point de départ et non d'un
    #: profil trouvé (nom issu d'un profil Gravatar, opérateur d'un numéro).
    profil_id: str | None
    profil_site: str
    confiance: float = 1.0
    module_source: str = ""


def pseudo_exploitable(pseudo: str) -> bool:
    """Un pseudonyme mérite-t-il de déclencher une recherche complète ?"""
    pseudo = (pseudo or "").strip().lstrip("@")
    if not MOTIF_PSEUDO_VALIDE.match(pseudo):
        return False
    if normaliser_pseudo(pseudo) in PSEUDOS_INEXPLOITABLES:
        return False
    # Une suite de chiffres n'est pas un pseudonyme
    return not pseudo.isdigit()


class DetecteurPivot:
    """Transforme des données extraites en pivots candidats."""

    def __init__(
        self,
        valeurs_deja_explorees: set[str] | None = None,
        pseudos_reference: list[str] | None = None,
    ):
        # Anti-cycle : « john » trouve un email qui redonne « john ». Sans cette
        # mémoire, l'investigation tournerait en boucle jusqu'à épuisement des quotas.
        self.deja_explorees = valeurs_deja_explorees or set()
        #: Pseudonymes sur lesquels porte l'investigation. Servent à écarter les noms
        #: qui n'ont manifestement aucun rapport avec la cible (voir `_pivot_nom`).
        self.pseudos_reference = [
            normaliser_pseudo(p) for p in (pseudos_reference or []) if p and p.strip()
        ]
        conf = config_metier().section("pivot")
        self.types_pivotables: dict[str, str] = conf.get("types_pivotables", {}) or {}

    def detecter(self, donnees: list[DonneeCandidate]) -> list[Pivot]:
        pivots: list[Pivot] = []
        vus_dans_ce_lot: set[str] = set()

        for donnee in donnees:
            pivot = self._analyser(donnee)
            if pivot is None:
                continue

            cle = f"{pivot.action}:{pivot.valeur_normalisee}"
            if cle in self.deja_explorees or cle in vus_dans_ce_lot:
                continue

            vus_dans_ce_lot.add(cle)
            pivots.append(pivot)

        # Les pivots les plus fiables d'abord : si un plafond tronque la liste,
        # ce sont les meilleurs qui sont conservés.
        pivots.sort(key=lambda p: p.confiance, reverse=True)
        return pivots

    def _analyser(self, donnee: DonneeCandidate) -> Pivot | None:
        if donnee.type not in self.types_pivotables:
            return None

        if donnee.type == TypeDonnee.PSEUDO_ALT.value:
            return self._pivot_pseudo(donnee)
        if donnee.type == TypeDonnee.EMAIL.value:
            return self._pivot_email(donnee)
        if donnee.type == TypeDonnee.LIEN_EXTERNE.value:
            return self._pivot_lien(donnee)
        if donnee.type in (TypeDonnee.NOM_REEL.value, TypeDonnee.NOM_AFFICHE.value):
            return self._pivot_nom(donnee)
        return None

    def _pivot_pseudo(self, donnee: DonneeCandidate) -> Pivot | None:
        pseudo = donnee.valeur.strip().lstrip("@")
        if not pseudo_exploitable(pseudo):
            return None
        return Pivot(
            type_pivot=TypeDonnee.PSEUDO_ALT.value,
            valeur=pseudo,
            valeur_normalisee=normaliser_pseudo(pseudo),
            action=ACTION_RECHERCHE,
            libelle=f"Pseudonyme « {pseudo} » mentionné sur {donnee.profil_site}",
            profil_source_id=donnee.profil_id,
            donnee_source_id=donnee.identifiant,
            confiance=donnee.confiance,
        )

    def _pivot_email(self, donnee: DonneeCandidate) -> Pivot | None:
        email = donnee.valeur.strip().lower()
        if "@" not in email:
            return None

        # La partie locale d'une adresse est très souvent le pseudonyme utilisé
        # ailleurs : c'est ce qui rend le pivot par email fructueux.
        partie_locale = email.split("@")[0]
        if not pseudo_exploitable(partie_locale):
            return None

        return Pivot(
            type_pivot=TypeDonnee.EMAIL.value,
            valeur=partie_locale,
            valeur_normalisee=normaliser_pseudo(partie_locale),
            action=ACTION_RECHERCHE,
            libelle=f"Adresse « {email} » trouvée sur {donnee.profil_site}",
            profil_source_id=donnee.profil_id,
            donnee_source_id=donnee.identifiant,
            confiance=donnee.confiance * 0.9,
            meta={"email_complet": email},
        )

    def _pivot_lien(self, donnee: DonneeCandidate) -> Pivot | None:
        """Un lien externe n'est un pivot que si un module sait exploiter son domaine."""
        from app.modules.registre import module_pour_domaine

        url = donnee.valeur.strip()
        domaine = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
        if not domaine:
            return None

        module = module_pour_domaine(domaine)
        if module is None:
            # Aucun module ne couvre ce site : le lien reste dans le graphe comme
            # information, mais ne déclenche aucune requête inutile.
            return None

        return Pivot(
            type_pivot=TypeDonnee.LIEN_EXTERNE.value,
            valeur=url,
            valeur_normalisee=url.lower().rstrip("/"),
            action=ACTION_ENRICHISSEMENT,
            libelle=f"Lien vers {module.libelle} déclaré sur {donnee.profil_site}",
            profil_source_id=donnee.profil_id,
            donnee_source_id=donnee.identifiant,
            confiance=donnee.confiance,
            meta={"module": module.nom, "domaine": domaine},
        )

    def _pivot_nom(self, donnee: DonneeCandidate) -> Pivot | None:
        """Un nom ne devient un pivot que sous une forme de pseudonyme plausible.

        Rechercher « Jean Martin » sur 500 sites ne donnerait que du bruit : seule
        une graphie compacte (« jeanmartin ») a une chance de correspondre à un compte.

        S'applique au nom réel comme au nom affiché. L'exigence de deux mots écarte
        d'elle-même les noms affichés qui ne sont que des prénoms ou des pseudonymes
        déjà connus (« Nicolas », « ken ») : seule une identité complète est retenue.
        """
        nom = donnee.valeur.strip()
        if len(nom.split()) < 2:
            return None
        compact = normaliser_pseudo(nom)
        if not pseudo_exploitable(compact) or len(compact) < 5:
            return None

        # Un nom qui ne partage aucune racine avec ce qu'on recherche désigne
        # vraisemblablement quelqu'un d'autre : c'est le nom affiché d'un compte
        # homonyme, donc d'un faux positif. Mesuré le 01/08/2026 sur « torvalds » :
        # « Marco Migozzi » déclenchait une recherche complète sans le moindre rapport
        # avec la cible, là où « Linus Torvalds » et « Patricia Torvalds » étaient
        # deux pistes légitimes.
        if self.pseudos_reference and not any(
            reference in compact or compact in reference
            for reference in self.pseudos_reference
        ):
            return None

        return Pivot(
            # Le type d'origine est conservé : l'analyste doit pouvoir distinguer un
            # rebond parti d'un nom déclaré comme réel d'un rebond parti d'un simple
            # nom d'affichage, dont la fiabilité n'est pas la même.
            type_pivot=donnee.type,
            valeur=compact,
            valeur_normalisee=compact,
            action=ACTION_RECHERCHE,
            libelle=f"Nom « {nom} » déclaré sur {donnee.profil_site}",
            profil_source_id=donnee.profil_id,
            donnee_source_id=donnee.identifiant,
            confiance=donnee.confiance * 0.6,   # signal plus faible : homonymies fréquentes
            meta={"nom_complet": nom},
        )
