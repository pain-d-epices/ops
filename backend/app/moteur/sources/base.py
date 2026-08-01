"""Socle des sources de recherche complémentaires (web ouvert, dark web).

Une source complète la recherche large (Maigret) pour le **même pseudonyme**, sans en
dépendre : elle renvoie des comptes candidats supplémentaires, trouvés autrement que
par construction d'URL de profil sur une liste de sites connus à l'avance.

Ce n'est ni un module (qui approfondit un profil déjà trouvé, voir `app/modules/`) ni
un chercheur (qui part d'un type de point de départ différent, voir
`app/moteur/chercheurs/`) : une source tourne systématiquement en complément de
Maigret, dans `executer_recherche`.

Pour en ajouter une : créer un fichier dans `app/moteur/sources/`, hériter de
`SourceComplementaire`, déclarer `nom` et `categorie`, implémenter `rechercher`. Le
registre la découvre automatiquement au démarrage — aucun enregistrement manuel.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.moteur.maigret_runner import ResultatSite

journal = logging.getLogger(__name__)


def cle_url(url: str) -> str:
    """Forme normalisée d'une adresse, pour comparer deux comptes.

    Sans elle, `https://github.com/torvalds` et `https://www.github.com/torvalds`
    passaient pour deux comptes distincts — cas réellement observé, Maigret utilisant
    `www.github.com` là où la recherche web renvoie `github.com`. Le préfixe `www.`,
    le schéma et la barre oblique finale sont donc neutralisés.
    """
    from urllib.parse import urlparse

    analyse = urlparse(url if "://" in url else f"https://{url}")
    domaine = (analyse.netloc or "").lower().removeprefix("www.")
    chemin = (analyse.path or "").rstrip("/").lower()
    return f"{domaine}{chemin}" or url.strip().lower()


def cle_compte(url: str) -> str:
    """Identifie le **compte** derrière une adresse, et non la page consultée.

    Deux adresses différentes d'un même site peuvent désigner le même compte :
    `github.com/torvalds` (le profil) et `github.com/torvalds/linux` (un dépôt de ce
    profil). Comparer les URL entières les traitait comme deux comptes distincts — le
    compte GitHub de la cible apparaissait alors deux fois dans les résultats, une
    fois via Maigret et une fois via la recherche web (constaté le 01/08/2026).

    La clé retenue est donc « domaine + nom d'utilisateur », et non le chemin complet.
    Le sous-domaine est conservé : `gist.github.com/torvalds` est bien un autre
    service, donc un autre compte, que `github.com/torvalds`.

    Quand aucun nom d'utilisateur ne peut être extrait, on retombe sur la
    normalisation d'URL, qui reste préférable à une comparaison brute.
    """
    from urllib.parse import urlparse

    from app.modules.base import ModuleSite
    from app.moteur.correlation.base import normaliser

    analyse = urlparse(url if "://" in url else f"https://{url}")
    domaine = (analyse.netloc or "").lower().removeprefix("www.")
    extrait = ModuleSite.pseudo_depuis_url(url)
    if domaine and extrait:
        return f"{domaine}/@{normaliser(extrait)}"
    return cle_url(url)


def url_de_profil_plausible(url: str, pseudo: str) -> bool:
    """L'adresse désigne-t-elle un profil **de cette personne**, et non une page à son sujet ?

    Un moteur de recherche généraliste répond à « torvalds » par des articles
    d'encyclopédie, des dépêches de presse et des pages de résultats — utiles à un
    lecteur, mais ce ne sont pas des comptes. Les enregistrer comme tels remplissait la
    liste de profils de faux comptes : sur une mesure réelle, 10 des 11 résultats web
    étaient des pages *au sujet de* Linus Torvalds (Britannica, ZDNet, Wikipédia,
    Google Scholar…), pas des comptes lui appartenant.

    Le tri s'appuie sur `pseudo_depuis_url`, qui fait déjà autorité dans le projet sur
    « cette adresse est-elle une page de profil, et de qui ? » : on ne garde le
    résultat que si le pseudonyme qu'elle en extrait est bien celui recherché.
    Concrètement, `github.com/torvalds/linux` est conservé, tandis que
    `britannica.com/biography/Linus-Torvalds` et `en.wikipedia.org/wiki/Linus_Torvalds`
    sont écartés.
    """
    from app.modules.base import ModuleSite
    from app.moteur.correlation.base import normaliser

    extrait = ModuleSite.pseudo_depuis_url(url)
    if not extrait:
        return False
    return normaliser(extrait) == normaliser(pseudo)


@dataclass
class ResultatSource:
    """Sortie d'une source pour un pseudonyme donné."""

    source: str
    sites: list[ResultatSite] = field(default_factory=list)
    #: nombre de résultats bruts rendus par la source, avant filtrage/troncature
    nb_resultats_bruts: int = 0
    duree_secondes: float = 0.0
    erreur: str | None = None

    @property
    def reussie(self) -> bool:
        return self.erreur is None


class SourceComplementaire(ABC):
    """Interface commune à toutes les sources complémentaires."""

    #: identifiant technique de la source (unique)
    nom: str = ""
    #: nom affiché dans l'interface
    libelle: str = ""
    #: "web" (indexé par les moteurs de recherche grand public) ou "dark_web"
    #: (réseau Tor ; une source de cette catégorie ne se connecte jamais à une
    #: adresse .onion, elle ne fait que lire un index déjà public en HTTPS classique)
    categorie: str = "web"

    @abstractmethod
    def rechercher(self, pseudo: str) -> ResultatSource:
        """Cherche des mentions du pseudonyme via cette source."""

    def disponible(self) -> bool:
        """La source est-elle utilisable en l'état (pas de clé manquante, etc.) ?

        Une source indisponible est simplement ignorée : les autres continuent.
        Une panne réseau ponctuelle n'est PAS de la responsabilité de cette méthode :
        elle se traduit par `ResultatSource.erreur`, pas par `disponible() == False`.
        """
        return True

    def __repr__(self) -> str:
        return f"<Source {self.nom} ({self.categorie})>"
