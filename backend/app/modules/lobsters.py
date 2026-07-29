"""Module d'enrichissement Lobsters.

Communauté technique dotée d'une API JSON publique et documentée pour les profils
(`https://lobste.rs/u/{pseudo}.json`), sans clé ni authentification. Les membres y
déclarent souvent leurs comptes GitHub et X, des pistes de rebond fiables.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleLobsters(ModuleSite):
    nom = "lobsters"
    libelle = "Lobsters"
    domaines = ["lobste.rs"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(f"https://lobste.rs/u/{identifiant}.json")
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not donnees.get("username"):
            resultat.erreur = f"Profil Lobsters introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("created_at"))

        bio = donnees.get("about")
        resultat.ajouter(TypeDonnee.BIO, bio)
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")
        for mention in self.extraire_mentions(bio):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="biographie")

        # Comptes tiers déclarés explicitement : pistes de rebond très fiables
        for champ, service in (("github_username", "GitHub"), ("twitter_username", "X")):
            if donnees.get(champ):
                resultat.ajouter(
                    TypeDonnee.PSEUDO_ALT, donnees[champ], confiance=0.9,
                    source=f"compte {service} déclaré sur Lobsters",
                )

        avatar = donnees.get("avatar_url")
        if avatar:
            if avatar.startswith("/"):
                avatar = f"https://lobste.rs{avatar}"
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
