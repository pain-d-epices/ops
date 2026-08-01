"""Recherche web ouverte via DuckDuckGo Lite.

Complète Maigret : celui-ci ne teste que des URLs de profil construites sur une liste
de sites connus à l'avance. Une recherche web trouve des mentions du pseudonyme
n'importe où sur le web indexé — site personnel, forum, page non couverte par la base
de Maigret — sans dépendre de cette liste.

`lite.duckduckgo.com` est utilisé plutôt que la version complète du moteur : une page
HTML minimale sans JavaScript, conçue pour les navigateurs texte, donc stable à
analyser et légère à interroger. Aucune clé ni jeton de session n'est nécessaire pour
obtenir la première page de résultats — à la différence d'Ahmia (voir `ahmia.py`).

Gratuit, sans clé API. Pas de bibliothèque tierce de recherche (type `ddgs`) : elle
ferait ses propres requêtes HTTP en dehors du limiteur de débit global du service
(`app/infra/limiteur.py`), ce qui casserait la garantie centrale de l'infrastructure —
ne jamais dépasser le débit toléré par un domaine tiers. Tout passe donc par
`ClientHttp`, comme les autres sources.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

from app.config import config_metier
from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import StatutMaigret
from app.moteur.maigret_runner import ResultatSite
from app.moteur.sources.base import (
    ResultatSource,
    SourceComplementaire,
    url_de_profil_plausible,
)

journal = logging.getLogger(__name__)

URL_RECHERCHE = "https://lite.duckduckgo.com/lite/"

MOTIF_ESPACES = re.compile(r"\s+")


class _AnalyseurResultatsDuckDuckGo(HTMLParser):
    """Extrait titre, URL et extrait de chaque résultat de la page « lite ».

    Structure ciblée (constatée sur `lite.duckduckgo.com`) :
        <a class="result-link" href="//duckduckgo.com/l/?uddg=<url encodée>">Titre</a>
        ...
        <td class="result-snippet">Extrait</td>

    Analyseur à états plutôt qu'expression régulière sur le HTML : plus robuste aux
    variations d'attributs, et n'échoue jamais violemment si la page change — au pire
    `resultats` reste vide, ce qui est traité comme une source sans résultat plutôt
    que comme une erreur (voir `SourceRechercheWeb.rechercher`).
    """

    def __init__(self) -> None:
        super().__init__()
        self.resultats: list[dict[str, str]] = []
        self._dans_titre = False
        self._dans_extrait = False
        self._resultat_courant: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributs = dict(attrs)
        if tag == "a" and attributs.get("class") == "result-link" and attributs.get("href"):
            self._dans_titre = True
            self._resultat_courant = {"href": attributs["href"], "titre": "", "extrait": ""}
        elif tag == "td" and attributs.get("class") == "result-snippet" and self._resultat_courant:
            self._dans_extrait = True

    def handle_data(self, data: str) -> None:
        if self._dans_titre and self._resultat_courant is not None:
            self._resultat_courant["titre"] += data
        elif self._dans_extrait and self._resultat_courant is not None:
            self._resultat_courant["extrait"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._dans_titre:
            self._dans_titre = False
            if self._resultat_courant is not None:
                self.resultats.append(self._resultat_courant)
        elif tag == "td" and self._dans_extrait:
            self._dans_extrait = False
            self._resultat_courant = None


def _texte_normalise(texte: str) -> str:
    return MOTIF_ESPACES.sub(" ", texte).strip()


def _url_cible(href: str) -> str | None:
    """DuckDuckGo Lite fait passer chaque résultat par un lien de redirection
    (`//duckduckgo.com/l/?uddg=<url encodée>`) : l'URL réelle est dans `uddg`."""
    if href.startswith("//"):
        href = "https:" + href
    parametres = parse_qs(urlparse(href).query)
    cible = parametres.get("uddg", [None])[0]
    return unquote(cible) if cible else None


@dataclass
class MentionWeb:
    """Une page du web ouvert où la valeur recherchée apparaît."""

    url: str
    titre: str
    extrait: str

    @property
    def domaine(self) -> str:
        return urlparse(self.url).netloc.lower()


def rechercher_mentions(requete: str, nb_max: int = 10) -> list[MentionWeb]:
    """Pages mentionnant la valeur recherchée, sans exiger que ce soit un profil.

    Complète `SourceRechercheWeb`, qui ne retient que les pages de profil. Cette
    exigence a du sens pour un pseudonyme — un pseudonyme désigne un compte — mais
    aucun pour un numéro de téléphone, une adresse postale ou un nom : là, toute page
    qui mentionne la valeur est une piste (annuaire professionnel, petite annonce,
    page d'entreprise, forum).

    Ces résultats ne sont donc **jamais** enregistrés comme des comptes, mais comme
    des liens rattachés au point de départ : dire « ce numéro apparaît sur cette page »
    est exact, alors que « cette personne possède un compte ici » ne le serait pas.
    """
    if not requete.strip():
        return []
    if not bool(config_metier().obtenir("recherche_web.actif", True)):
        return []

    client = ClientHttp()
    try:
        reponse = client.obtenir(URL_RECHERCHE, parametres_requete={"q": requete})
    except (ErreurReseau, DebitDepasse) as exc:
        journal.info("Recherche de mentions impossible pour « %s » : %s", requete[:60], exc)
        return []
    if reponse.status_code >= 400:
        journal.info("DuckDuckGo a répondu %d pour « %s »", reponse.status_code, requete[:60])
        return []

    analyseur = _AnalyseurResultatsDuckDuckGo()
    analyseur.feed(reponse.text)

    mentions: list[MentionWeb] = []
    vues: set[str] = set()
    for item in analyseur.resultats:
        if len(mentions) >= nb_max:
            break
        url = _url_cible(item["href"])
        if not url:
            continue
        cle = url.rstrip("/").lower()
        if cle in vues:
            continue
        vues.add(cle)
        mentions.append(
            MentionWeb(
                url=url,
                titre=_texte_normalise(item["titre"])[:200],
                extrait=_texte_normalise(item["extrait"])[:500],
            )
        )
    return mentions


class SourceRechercheWeb(SourceComplementaire):
    nom = "recherche_web"
    libelle = "Recherche web (DuckDuckGo)"
    categorie = "web"

    def rechercher(self, pseudo: str) -> ResultatSource:
        resultat = ResultatSource(source=self.nom)
        debut = time.monotonic()

        if not bool(config_metier().obtenir("recherche_web.actif", True)):
            resultat.erreur = "Recherche web désactivée dans la configuration."
            return resultat

        client = ClientHttp()
        try:
            reponse = client.obtenir(URL_RECHERCHE, parametres_requete={"q": pseudo})
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = f"DuckDuckGo indisponible : {exc}"
            return resultat

        if reponse.status_code >= 400:
            resultat.erreur = f"DuckDuckGo a répondu {reponse.status_code}."
            return resultat

        analyseur = _AnalyseurResultatsDuckDuckGo()
        analyseur.feed(reponse.text)
        resultat.nb_resultats_bruts = len(analyseur.resultats)

        nb_max = int(config_metier().obtenir("recherche_web.nb_resultats_max", 10))
        nb_ecartes = 0
        for item in analyseur.resultats:
            if len(resultat.sites) >= nb_max:
                break
            url = _url_cible(item["href"])
            if not url:
                continue
            domaine = urlparse(url).netloc.lower()
            if not domaine:
                continue
            # Un moteur généraliste renvoie surtout des pages *au sujet de* la
            # personne : seules les pages de profil sont retenues (voir
            # `url_de_profil_plausible`).
            if not url_de_profil_plausible(url, pseudo):
                nb_ecartes += 1
                continue
            titre = _texte_normalise(item["titre"])

            resultat.sites.append(
                ResultatSite(
                    site_nom=titre[:200] or domaine,
                    site_domaine=domaine,
                    url=url,
                    pseudo=pseudo,
                    statut=StatutMaigret.TROUVE,
                    tags=["recherche_web"],
                    # Une mention trouvée par recherche web n'est jamais une preuve
                    # aussi solide qu'une URL de profil connue d'avance : le moteur de
                    # corrélation la traite comme un signal plus faible, au même titre
                    # qu'une correspondance approximative de Maigret.
                    est_similaire=True,
                    brut={
                        "titre": titre,
                        "extrait": _texte_normalise(item["extrait"]),
                        "_source": "duckduckgo",
                    },
                )
            )

        if nb_ecartes:
            # Journalisé et non masqué : un filtrage silencieux rendrait
            # incompréhensible l'écart entre « 10 résultats web » et ce qui s'affiche.
            journal.info(
                "Recherche web « %s » : %d page(s) écartée(s) car sans profil "
                "correspondant, %d compte(s) retenu(s)",
                pseudo, nb_ecartes, len(resultat.sites),
            )

        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat
