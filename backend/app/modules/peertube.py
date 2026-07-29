"""Module d'enrichissement PeerTube.

Plateforme vidéo fédérée (protocole ActivityPub), API REST officielle et documentée
pour la consultation des comptes. Comme pour Mastodon, l'instance varie d'un profil
à l'autre : le module interroge celle présente dans l'URL.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModulePeerTube(ModuleSite):
    nom = "peertube"
    libelle = "PeerTube"
    # Instances les plus fréquentées ; une instance absente de cette liste n'est
    # simplement pas enrichie (mais reste trouvée par la recherche large).
    domaines = ["peertube.social", "video.blender.org", "tilvids.com", "diode.zone", "framatube.org"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        analyse = urlparse(url_profil if "://" in url_profil else f"https://{url_profil}")
        instance = analyse.netloc
        identifiant = self._identifiant(url_profil) or self.pseudo_depuis_url(url_profil) or pseudo

        if not instance:
            resultat.erreur = "Instance PeerTube indéterminable depuis l'URL."
            return resultat

        client = ClientHttp()
        try:
            donnees = client.obtenir_json(f"https://{instance}/api/v1/accounts/{identifiant}")
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not donnees.get("name"):
            resultat.erreur = f"Compte PeerTube introuvable pour « {identifiant}@{instance} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client, instance)
        return resultat

    @staticmethod
    def _identifiant(url: str) -> str | None:
        """Les URLs de compte suivent /accounts/{pseudo} ou /a/{pseudo}/…"""
        segments = [s for s in url.split("?")[0].rstrip("/").split("/") if s]
        for marqueur in ("accounts", "a"):
            if marqueur in segments:
                position = segments.index(marqueur)
                if position + 1 < len(segments):
                    return segments[position + 1]
        return None

    def _extraire(
        self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp, instance: str
    ) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("displayName"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("createdAt"))
        resultat.ajouter(TypeDonnee.NB_ABONNES, donnees.get("followersCount"))

        bio = donnees.get("description")
        resultat.ajouter(TypeDonnee.BIO, bio)
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="description du profil")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="description du profil")
        for mention in self.extraire_mentions(bio):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="description du profil")

        chemin_avatar = None
        avatars = donnees.get("avatars")
        if isinstance(avatars, list) and avatars:
            chemin_avatar = avatars[-1].get("path")
        elif isinstance(donnees.get("avatar"), dict):
            chemin_avatar = donnees["avatar"].get("path")
        if chemin_avatar:
            url_avatar = (
                chemin_avatar if chemin_avatar.startswith("http") else f"https://{instance}{chemin_avatar}"
            )
            resultat.ajouter(TypeDonnee.AVATAR_URL, url_avatar)
            empreinte = self.hash_perceptuel(client.telecharger(url_avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=url_avatar)
