"""Module d'enrichissement Hacker News.

API Firebase publique, sans authentification ni limite documentée. Le champ « about »
contient fréquemment une adresse électronique et des liens vers d'autres profils.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement
from app.modules.mastodon import nettoyer_html

journal = logging.getLogger(__name__)


class ModuleHackerNews(ModuleSite):
    nom = "hackernews"
    libelle = "Hacker News"
    domaines = ["news.ycombinator.com", "hacker-news.firebaseio.com"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self._identifiant(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(
                f"https://hacker-news.firebaseio.com/v0/user/{identifiant}.json"
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not donnees.get("id"):
            resultat.erreur = f"Profil Hacker News introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees)
        return resultat

    @staticmethod
    def _identifiant(url: str) -> str | None:
        """Le nom d'utilisateur est passé en paramètre : /user?id=xxx"""
        if "id=" in url:
            return url.split("id=")[-1].split("&")[0]
        return None

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any]) -> None:
        if donnees.get("created"):
            resultat.ajouter(TypeDonnee.DATE_CREATION, int(donnees["created"]))

        about = nettoyer_html(donnees.get("about"))
        resultat.ajouter(TypeDonnee.BIO, about)

        for email in self.extraire_emails(about):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.85, source="profil Hacker News")
        for lien in self.extraire_urls(about):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.85, source="profil Hacker News")
            pseudo_deduit = self.pseudo_depuis_url(lien)
            if pseudo_deduit:
                resultat.ajouter(
                    TypeDonnee.PSEUDO_ALT, pseudo_deduit, confiance=0.6, source="lien du profil"
                )
        for mention in self.extraire_mentions(about):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="profil Hacker News")

        # Hacker News ne propose pas d'avatar : rien à hacher pour ce site.
