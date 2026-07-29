"""Module d'enrichissement Dev.to.

API publique documentée, sans clé pour la consultation des profils. Particulièrement
intéressante : les utilisateurs y déclarent explicitement leurs comptes GitHub et
X/Twitter, ce qui fournit des pistes de rebond fiables.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleDevTo(ModuleSite):
    nom = "devto"
    libelle = "Dev.to"
    domaines = ["dev.to"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(
                "https://dev.to/api/users/by_username", parametres_requete={"url": identifiant}
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not donnees.get("username"):
            resultat.erreur = f"Profil Dev.to introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("name"))
        resultat.ajouter(TypeDonnee.BIO, donnees.get("summary"))
        resultat.ajouter(TypeDonnee.LOCALISATION, donnees.get("location"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("joined_at"))
        resultat.ajouter(TypeDonnee.LIEN_EXTERNE, donnees.get("website_url"))

        # Comptes tiers déclarés par l'utilisateur : pistes de rebond très fiables
        for champ, service in (("github_username", "GitHub"), ("twitter_username", "X")):
            if donnees.get(champ):
                resultat.ajouter(
                    TypeDonnee.PSEUDO_ALT,
                    donnees[champ],
                    confiance=0.9,
                    source=f"compte {service} déclaré sur Dev.to",
                )

        resume = donnees.get("summary")
        for email in self.extraire_emails(resume):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(resume):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")

        avatar = donnees.get("profile_image") or donnees.get("profile_image_90")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
