"""Module d'enrichissement MixCloud.

API publique et documentée, sans clé ni authentification.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleMixCloud(ModuleSite):
    nom = "mixcloud"
    libelle = "MixCloud"
    domaines = ["mixcloud.com", "api.mixcloud.com"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(f"https://api.mixcloud.com/{identifiant}/")
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not donnees.get("username"):
            resultat.erreur = f"Profil MixCloud introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("name"))
        resultat.ajouter(TypeDonnee.BIO, donnees.get("biog"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("created_time"))
        resultat.ajouter(TypeDonnee.NB_ABONNES, donnees.get("follower_count"))

        # La localisation est renvoyée en deux champs distincts
        ville = (donnees.get("city") or "").strip()
        pays = (donnees.get("country") or "").strip()
        lieu = ", ".join(partie for partie in (ville, pays) if partie)
        resultat.ajouter(TypeDonnee.LOCALISATION, lieu)

        bio = donnees.get("biog")
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")
        for mention in self.extraire_mentions(bio):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="biographie")

        avatar = (donnees.get("pictures") or {}).get("large") or (donnees.get("pictures") or {}).get("medium")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
