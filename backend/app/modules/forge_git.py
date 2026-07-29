"""Modules d'enrichissement des forges Git compatibles Gitea/Forgejo et Gitee.

Codeberg et Gitee exposent la même forme d'API que Gitea : la logique d'extraction
est donc mutualisée dans une classe de base, chaque forge n'ayant plus qu'à déclarer
son domaine et son adresse d'API. Ajouter une autre instance Forgejo (une forge
d'entreprise, par exemple) revient à écrire quatre lignes.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleForgeGit(ModuleSite):
    """Socle commun aux forges exposant l'API Gitea/Forgejo (`/api/v1/users/{login}`)."""

    #: adresse de base de l'API, sans barre finale
    base_api: str = ""

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(f"{self.base_api}/{identifiant}")
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not (donnees.get("login") or donnees.get("username")):
            resultat.erreur = f"Profil {self.libelle} introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("full_name") or donnees.get("name"))
        resultat.ajouter(TypeDonnee.BIO, donnees.get("description") or donnees.get("bio"))
        resultat.ajouter(TypeDonnee.LOCALISATION, donnees.get("location"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("created") or donnees.get("created_at"))
        resultat.ajouter(TypeDonnee.NB_ABONNES, donnees.get("followers_count") or donnees.get("followers"))
        resultat.ajouter(TypeDonnee.LIEN_EXTERNE, donnees.get("website") or donnees.get("blog"))

        # L'email n'est renvoyé que si l'utilisateur l'a rendu public
        resultat.ajouter(TypeDonnee.EMAIL, donnees.get("email"))

        biographie = donnees.get("description") or donnees.get("bio")
        for email in self.extraire_emails(biographie):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(biographie):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")
        for mention in self.extraire_mentions(biographie):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="biographie")

        avatar = donnees.get("avatar_url")
        if avatar and "gravatar.com/avatar/" not in avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)


class ModuleCodeberg(ModuleForgeGit):
    nom = "codeberg"
    libelle = "Codeberg"
    domaines = ["codeberg.org"]
    base_api = "https://codeberg.org/api/v1/users"


class ModuleGitee(ModuleForgeGit):
    nom = "gitee"
    libelle = "Gitee"
    domaines = ["gitee.com"]
    base_api = "https://gitee.com/api/v5/users"
