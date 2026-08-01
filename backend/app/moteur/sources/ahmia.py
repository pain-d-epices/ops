"""Recherche dans l'index du réseau Tor via Ahmia (ahmia.fi).

Ahmia indexe les services cachés (.onion) accessibles sur le réseau Tor et exclut
explicitement les contenus illégaux de son index (voir sa politique publique de
blacklist : https://ahmia.fi/blacklist/). Interroger Ahmia revient donc à lire un
index déjà public, au même titre qu'un moteur de recherche classique.

**Ce module ne se connecte jamais à une adresse .onion.** Il ne fait que lire, en
HTTPS classique, la page de résultats publiée sur ahmia.fi — aucune connexion Tor
n'est nécessaire côté serveur, et aucun contenu du dark web n'est téléchargé ni
consulté par Searcher. Seuls le titre, l'extrait et l'adresse .onion déjà indexés par
Ahmia sont récupérés.

Ahmia protège sa page de résultats par un jeton anti-robot à usage unique : un champ
caché, au nom généré aléatoirement à chaque chargement de la page d'accueil, à
renvoyer tel quel avec la recherche. Ce n'est pas une authentification — le jeton ne
protège aucune donnée privée, seulement le débit de requêtes automatisées — mais deux
requêtes sont nécessaires : une pour lire la page d'accueil et en extraire le jeton,
une pour la recherche elle-même.

Ahmia est un service communautaire connu pour son instabilité (délais dépassés,
pannes temporaires). Toute défaillance est donc traitée comme une simple
indisponibilité de la source, jamais comme une erreur bloquante pour l'investigation.
"""

from __future__ import annotations

import logging
import re
import time
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

URL_ACCUEIL = "https://ahmia.fi/"
URL_RECHERCHE = "https://ahmia.fi/search/"

MOTIF_ESPACES = re.compile(r"\s+")
# Adresse .onion v3 (56 caractères) — les v2 (16 caractères) sont dépréciées côté Tor
# depuis 2021 mais restées ici par prudence, certains index n'ayant pas fini de purger.
MOTIF_ONION = re.compile(r"^[a-z2-7]{16,56}\.onion$", re.IGNORECASE)


class _AnalyseurJetonAhmia(HTMLParser):
    """Extrait le champ caché anti-robot du formulaire de recherche de la page d'accueil."""

    def __init__(self) -> None:
        super().__init__()
        self.nom_champ: str | None = None
        self.valeur_champ: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input" or self.nom_champ is not None:
            return
        attributs = dict(attrs)
        if attributs.get("type") != "hidden":
            return
        nom = attributs.get("name") or ""
        # Le jeton CSRF standard de Django ne nous sert à rien ici : Ahmia utilise un
        # second champ caché, au nom généré aléatoirement, dédié à la protection
        # anti-robot du moteur de recherche lui-même.
        if nom and nom != "csrfmiddlewaretoken":
            self.nom_champ = nom
            self.valeur_champ = attributs.get("value") or ""


class _AnalyseurResultatsAhmia(HTMLParser):
    """Extrait titre, lien et extrait de chaque résultat.

    Structure ciblée (gabarit `tor_results.html` du dépôt public ahmia/ahmia-site) :
        <li class="result">
          <h4><a href="/search/redirect?...&redirect_url=<url .onion>">Titre</a></h4>
          <p>Extrait</p>
          <cite>domaine.onion</cite>
        </li>

    Comme pour DuckDuckGo, un changement de gabarit dégrade silencieusement le nombre
    de résultats plutôt que de faire échouer la recherche.
    """

    def __init__(self) -> None:
        super().__init__()
        self.resultats: list[dict[str, str]] = []
        self._dans_resultat = False
        self._dans_titre = False
        self._dans_extrait = False
        self._resultat_courant: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributs = dict(attrs)
        classes = (attributs.get("class") or "").split()

        if tag == "li" and "result" in classes:
            self._dans_resultat = True
            self._resultat_courant = {"href": "", "titre": "", "extrait": ""}
            return
        if not self._dans_resultat or self._resultat_courant is None:
            return

        href = attributs.get("href") or ""
        if tag == "a" and "redirect_url=" in href:
            self._dans_titre = True
            self._resultat_courant["href"] = href
        elif tag == "p" and not self._resultat_courant["extrait"]:
            self._dans_extrait = True

    def handle_data(self, data: str) -> None:
        if self._resultat_courant is None:
            return
        if self._dans_titre:
            self._resultat_courant["titre"] += data
        elif self._dans_extrait:
            self._resultat_courant["extrait"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._dans_titre = False
        elif tag == "p":
            self._dans_extrait = False
        elif tag == "li" and self._dans_resultat:
            self._dans_resultat = False
            if self._resultat_courant and self._resultat_courant["href"]:
                self.resultats.append(self._resultat_courant)
            self._resultat_courant = None


def _texte_normalise(texte: str) -> str:
    return MOTIF_ESPACES.sub(" ", texte).strip()


def _url_onion(href: str) -> str | None:
    """Décode l'URL .onion réelle depuis le lien de redirection d'Ahmia.

    Rejette tout ce qui n'est pas une adresse .onion valide : une protection contre
    une page compromise ou un gabarit changé qui glisserait un lien clearnet — cette
    source ne doit produire que des résultats du réseau Tor, jamais autre chose.
    """
    parametres = parse_qs(urlparse(href).query)
    cible = parametres.get("redirect_url", [None])[0]
    if not cible:
        return None
    cible = unquote(cible)
    domaine = urlparse(cible).netloc.lower()
    if not MOTIF_ONION.match(domaine):
        return None
    return cible


class SourceRechercheDarkWeb(SourceComplementaire):
    nom = "recherche_darkweb"
    libelle = "Recherche dark web (Ahmia)"
    categorie = "dark_web"

    def rechercher(self, pseudo: str) -> ResultatSource:
        resultat = ResultatSource(source=self.nom)
        debut = time.monotonic()

        if not bool(config_metier().obtenir("recherche_darkweb.actif", True)):
            resultat.erreur = "Recherche dark web désactivée dans la configuration."
            return resultat

        client = ClientHttp()

        try:
            page_accueil = client.obtenir(URL_ACCUEIL)
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = f"Ahmia indisponible : {exc}"
            return resultat
        if page_accueil.status_code >= 400:
            resultat.erreur = f"Ahmia a répondu {page_accueil.status_code} (page d'accueil)."
            return resultat

        jeton = _AnalyseurJetonAhmia()
        jeton.feed(page_accueil.text)
        parametres_requete = {"q": pseudo}
        if jeton.nom_champ:
            parametres_requete[jeton.nom_champ] = jeton.valeur_champ

        try:
            reponse = client.obtenir(URL_RECHERCHE, parametres_requete=parametres_requete)
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = f"Ahmia indisponible : {exc}"
            return resultat
        if reponse.status_code >= 400:
            resultat.erreur = f"Ahmia a répondu {reponse.status_code} (recherche)."
            return resultat

        analyseur = _AnalyseurResultatsAhmia()
        analyseur.feed(reponse.text)
        resultat.nb_resultats_bruts = len(analyseur.resultats)

        nb_max = int(config_metier().obtenir("recherche_darkweb.nb_resultats_max", 10))
        nb_ecartes = 0
        for item in analyseur.resultats:
            if len(resultat.sites) >= nb_max:
                break
            url = _url_onion(item["href"])
            if not url:
                continue
            # Même exigence que pour la recherche web : une page qui *mentionne* le
            # pseudonyme n'est pas un compte. Sur le réseau Tor, l'écart est encore
            # plus marqué — l'essentiel de l'index est constitué de places de marché
            # et d'annuaires où le terme recherché n'apparaît que dans du texte.
            if not url_de_profil_plausible(url, pseudo):
                nb_ecartes += 1
                continue
            domaine = urlparse(url).netloc.lower()
            titre = _texte_normalise(item["titre"])

            resultat.sites.append(
                ResultatSite(
                    site_nom=titre[:200] or domaine,
                    site_domaine=domaine,
                    url=url,
                    pseudo=pseudo,
                    statut=StatutMaigret.TROUVE,
                    # Étiquette dédiée : permet à l'interface d'afficher un
                    # avertissement (adresse .onion, jamais visitée par le service).
                    tags=["dark_web"],
                    # Une mention indexée n'est jamais une preuve aussi solide qu'une
                    # URL de profil connue d'avance : signal traité comme plus faible
                    # par le moteur de corrélation, au même titre qu'une
                    # correspondance approximative de Maigret.
                    est_similaire=True,
                    brut={
                        "titre": titre,
                        "extrait": _texte_normalise(item["extrait"]),
                        "_source": "ahmia",
                    },
                )
            )

        if nb_ecartes:
            journal.info(
                "Recherche dark web « %s » : %d page(s) écartée(s) sans profil "
                "correspondant, %d compte(s) retenu(s)",
                pseudo, nb_ecartes, len(resultat.sites),
            )

        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat
