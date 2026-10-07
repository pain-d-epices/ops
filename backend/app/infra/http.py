"""Client HTTP commun aux modules de site.

Centralise ce qu'aucun module ne devrait réimplémenter : limitation de débit globale,
délais d'attente, nouvelles tentatives sur erreur transitoire, et identification
honnête du robot via l'en-tête User-Agent.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import config_metier
from app.infra.limiteur import limiteur

journal = logging.getLogger(__name__)


class ErreurReseau(Exception):
    """Échec réseau après épuisement des tentatives."""


class DebitDepasse(Exception):
    """Le quota de requêtes du site cible est saturé ; réessayer plus tard."""


class ClientHttp:
    """Client HTTP synchrone, respectueux des sites interrogés."""

    def __init__(self, entetes_supplementaires: dict[str, str] | None = None):
        conf = config_metier().section("reseau")
        self.timeout_connexion = float(conf.get("timeout_connexion", 10))
        self.timeout_lecture = float(conf.get("timeout_lecture", 20))
        self.tentatives_max = int(conf.get("tentatives_max", 3))
        # Un User-Agent identifiable est une bonne pratique : il permet à un site de
        # nous contacter ou de nous limiter proprement plutôt que de nous bannir.
        self.user_agent = str(conf.get("user_agent", "OpsOSINT/0.1"))
        self.entetes_supplementaires = entetes_supplementaires or {}

    def _entetes(self, supplementaires: dict[str, str] | None = None) -> dict[str, str]:
        entetes = {"User-Agent": self.user_agent, "Accept": "application/json, text/html;q=0.9"}
        entetes.update(self.entetes_supplementaires)
        entetes.update(supplementaires or {})
        return entetes

    def obtenir(
        self,
        url: str,
        *,
        entetes: dict[str, str] | None = None,
        parametres_requete: dict[str, Any] | None = None,
        attente_max: float = 30.0,
    ) -> httpx.Response:
        """Requête GET, après obtention d'un jeton auprès du limiteur global."""
        domaine = urlparse(url).netloc.lower()

        if not limiteur().attendre(domaine, attente_max=attente_max):
            raise DebitDepasse(
                f"Le quota de requêtes vers {domaine} est saturé. "
                "La demande sera à relancer plus tard."
            )

        derniere_erreur: Exception | None = None
        for tentative in range(1, self.tentatives_max + 1):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(self.timeout_lecture, connect=self.timeout_connexion),
                    follow_redirects=True,
                ) as client:
                    reponse = client.get(url, headers=self._entetes(entetes), params=parametres_requete)

                # 429 / 5xx : erreurs transitoires, on retente après recul.
                if reponse.status_code == 429:
                    attente = float(reponse.headers.get("Retry-After", 5))
                    journal.info("429 reçu de %s, attente de %.0fs", domaine, attente)
                    if tentative < self.tentatives_max:
                        limiteur().attendre(domaine, cout=3, attente_max=attente_max)
                        continue
                    raise DebitDepasse(f"{domaine} limite nos requêtes (429).")

                if reponse.status_code >= 500 and tentative < self.tentatives_max:
                    journal.info("Erreur %d de %s, nouvelle tentative", reponse.status_code, domaine)
                    continue

                return reponse

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                derniere_erreur = exc
                journal.info("Tentative %d/%d en échec sur %s : %s", tentative, self.tentatives_max, url, exc)

        raise ErreurReseau(f"Échec de la requête vers {url} : {derniere_erreur}")

    def obtenir_json(self, url: str, **kwargs: Any) -> dict[str, Any] | list[Any] | None:
        """GET renvoyant du JSON. None si le site répond 404 ou un contenu non JSON."""
        reponse = self.obtenir(url, **kwargs)
        if reponse.status_code == 404:
            return None
        if reponse.status_code >= 400:
            journal.info("Réponse %d pour %s", reponse.status_code, url)
            return None
        try:
            return reponse.json()
        except ValueError:
            journal.info("Réponse non JSON pour %s", url)
            return None

    def telecharger(self, url: str, taille_max: int = 5 * 1024 * 1024, **kwargs: Any) -> bytes | None:
        """Télécharge un contenu binaire (avatar), avec une taille maximale.

        Le plafond protège d'un site malveillant qui servirait un fichier énorme pour
        saturer la mémoire d'un worker.
        """
        try:
            reponse = self.obtenir(url, **kwargs)
        except (ErreurReseau, DebitDepasse) as exc:
            journal.info("Téléchargement impossible (%s) : %s", url, exc)
            return None

        if reponse.status_code >= 400:
            return None

        contenu = reponse.content
        if len(contenu) > taille_max:
            journal.info("Contenu ignoré (%d octets > %d) : %s", len(contenu), taille_max, url)
            return None
        return contenu


_client: ClientHttp | None = None


def client_http() -> ClientHttp:
    global _client
    if _client is None:
        _client = ClientHttp()
    return _client
