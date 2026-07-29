"""Module d'enrichissement Last.fm.

Historique d'écoute et localisation déclarée. Nécessite une clé API gratuite
(https://www.last.fm/api/account/create), à renseigner dans LASTFM_API_KEY.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import parametres
from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)

API = "https://ws.audioscrobbler.com/2.0/"


class ModuleLastFm(ModuleSite):
    nom = "lastfm"
    libelle = "Last.fm"
    domaines = ["last.fm", "www.last.fm"]
    necessite_cle_api = True

    def disponible(self) -> bool:
        return bool(parametres().lastfm_api_key)

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(
                API,
                parametres_requete={
                    "method": "user.getinfo",
                    "user": identifiant,
                    "api_key": parametres().lastfm_api_key,
                    "format": "json",
                },
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        utilisateur = (donnees or {}).get("user") if isinstance(donnees, dict) else None
        if not utilisateur:
            resultat.erreur = f"Profil Last.fm introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = utilisateur
        self._extraire(resultat, utilisateur, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, utilisateur: dict[str, Any], client: ClientHttp) -> None:
        # Le nom réel est une déclaration explicite de l'utilisateur : signal fort
        resultat.ajouter(TypeDonnee.NOM_REEL, utilisateur.get("realname"), confiance=0.9)
        resultat.ajouter(TypeDonnee.LOCALISATION, utilisateur.get("country"))

        inscription = (utilisateur.get("registered") or {}).get("unixtime")
        if inscription:
            try:
                resultat.ajouter(TypeDonnee.DATE_CREATION, int(inscription))
            except (TypeError, ValueError):
                pass

        images = utilisateur.get("image") or []
        avatar = next(
            (i.get("#text") for i in reversed(images) if isinstance(i, dict) and i.get("#text")),
            None,
        )
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
