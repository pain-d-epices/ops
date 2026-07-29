"""Module d'enrichissement Liberapay.

Plateforme de financement participatif récurrent, à but non lucratif. Son API de
consultation publique est minimale (aucune biographie), mais confirme l'existence du
compte et fournit son avatar — utile pour la corrélation par empreinte perceptuelle.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleLiberapay(ModuleSite):
    nom = "liberapay"
    libelle = "Liberapay"
    domaines = ["liberapay.com"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(f"https://liberapay.com/{identifiant}/public.json")
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not donnees.get("username"):
            resultat.erreur = f"Profil Liberapay introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        # Le nombre de mécènes est l'équivalent le plus proche d'un nombre d'abonnés
        resultat.ajouter(TypeDonnee.NB_ABONNES, donnees.get("npatrons"))

        avatar = donnees.get("avatar_url")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
