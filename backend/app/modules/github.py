"""Module d'enrichissement GitHub.

Utilise l'API publique et documentée de GitHub — aucun contournement, aucun scraping.
Sans jeton : 60 requêtes par heure. Avec un jeton personnel (GITHUB_TOKEN) : 5000.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import parametres
from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleGitHub(ModuleSite):
    nom = "github"
    libelle = "GitHub"
    domaines = ["github.com", "api.github.com", "gist.github.com"]

    def _client(self) -> ClientHttp:
        entetes = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        jeton = parametres().github_token
        if jeton:
            entetes["Authorization"] = f"Bearer {jeton}"
        return ClientHttp(entetes_supplementaires=entetes)

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = self._client()

        try:
            donnees = client.obtenir_json(f"https://api.github.com/users/{identifiant}")
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict):
            resultat.erreur = f"Profil GitHub introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("name"))
        resultat.ajouter(TypeDonnee.BIO, donnees.get("bio"))
        resultat.ajouter(TypeDonnee.LOCALISATION, donnees.get("location"))
        resultat.ajouter(TypeDonnee.ENTREPRISE, donnees.get("company"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("created_at"))
        resultat.ajouter(TypeDonnee.NB_ABONNES, donnees.get("followers"))

        # L'email public est renseigné volontairement par l'utilisateur : c'est un
        # pivot de premier ordre quand il est présent.
        resultat.ajouter(TypeDonnee.EMAIL, donnees.get("email"))

        site_perso = donnees.get("blog")
        if site_perso:
            url = site_perso if "://" in site_perso else f"https://{site_perso}"
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, url)

        # Le compte X/Twitter déclaré est un pseudonyme, pas un lien : il alimente
        # directement une nouvelle recherche Maigret lors du pivot.
        if donnees.get("twitter_username"):
            resultat.ajouter(
                TypeDonnee.PSEUDO_ALT,
                donnees["twitter_username"],
                confiance=0.9,
                source="compte X déclaré sur GitHub",
            )

        # Pseudonymes et adresses mentionnés dans la biographie
        for email in self.extraire_emails(donnees.get("bio")):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for mention in self.extraire_mentions(donnees.get("bio")):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.6, source="biographie")
        for lien in self.extraire_urls(donnees.get("bio")):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")

        avatar = donnees.get("avatar_url")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
