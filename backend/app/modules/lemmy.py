"""Module d'enrichissement Lemmy.

Réseau social fédéré de liens et de discussions, API REST publique et documentée.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleLemmy(ModuleSite):
    nom = "lemmy"
    libelle = "Lemmy"
    # Instances les plus fréquentées ; une instance absente de cette liste n'est
    # simplement pas enrichie (mais reste trouvée par la recherche large).
    domaines = ["lemmy.world", "lemmy.ml", "lemm.ee", "sh.itjust.works", "beehaw.org", "lemmy.zip"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        analyse = urlparse(url_profil if "://" in url_profil else f"https://{url_profil}")
        instance = analyse.netloc
        identifiant = self._identifiant(url_profil) or pseudo

        if not instance:
            resultat.erreur = "Instance Lemmy indéterminable depuis l'URL."
            return resultat

        client = ClientHttp()
        try:
            donnees = client.obtenir_json(
                f"https://{instance}/api/v3/user", parametres_requete={"username": identifiant}
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        vue = (donnees or {}).get("person_view") if isinstance(donnees, dict) else None
        if not vue or not vue.get("person"):
            resultat.erreur = f"Compte Lemmy introuvable pour « {identifiant}@{instance} »."
            return resultat

        resultat.donnees_brutes = vue
        self._extraire(resultat, vue, client)
        return resultat

    @staticmethod
    def _identifiant(url: str) -> str | None:
        """Les profils Lemmy suivent /u/{pseudo}."""
        segments = [s for s in url.split("?")[0].rstrip("/").split("/") if s]
        if "u" in segments:
            position = segments.index("u")
            if position + 1 < len(segments):
                return segments[position + 1]
        return None

    def _extraire(self, resultat: ResultatEnrichissement, vue: dict[str, Any], client: ClientHttp) -> None:
        personne = vue.get("person") or {}

        resultat.ajouter(TypeDonnee.NOM_AFFICHE, personne.get("display_name"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, personne.get("published"))

        bio = personne.get("bio")
        resultat.ajouter(TypeDonnee.BIO, bio)
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")
        for mention in self.extraire_mentions(bio):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="biographie")

        avatar = personne.get("avatar")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
