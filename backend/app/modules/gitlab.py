"""Module d'enrichissement GitLab (gitlab.com).

API publique v4, sans authentification pour les profils publics.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleGitLab(ModuleSite):
    nom = "gitlab"
    libelle = "GitLab"
    domaines = ["gitlab.com"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            # L'API ne permet pas d'interroger un profil par son nom directement :
            # il faut d'abord résoudre le nom en identifiant numérique.
            liste = client.obtenir_json(
                "https://gitlab.com/api/v4/users", parametres_requete={"username": identifiant}
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(liste, list) or not liste:
            resultat.erreur = f"Profil GitLab introuvable pour « {identifiant} »."
            return resultat

        apercu = liste[0]
        donnees: dict[str, Any] = apercu
        try:
            detail = client.obtenir_json(f"https://gitlab.com/api/v4/users/{apercu.get('id')}")
            if isinstance(detail, dict):
                donnees = {**apercu, **detail}
        except (ErreurReseau, DebitDepasse):
            # Le détail est un bonus : l'aperçu contient déjà l'essentiel.
            journal.info("Détail GitLab indisponible pour « %s »", identifiant)

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("name"))
        resultat.ajouter(TypeDonnee.BIO, donnees.get("bio"))
        resultat.ajouter(TypeDonnee.LOCALISATION, donnees.get("location"))
        resultat.ajouter(TypeDonnee.ENTREPRISE, donnees.get("organization") or donnees.get("job_title"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("created_at"))
        resultat.ajouter(TypeDonnee.EMAIL, donnees.get("public_email"))
        resultat.ajouter(TypeDonnee.LIEN_EXTERNE, donnees.get("website_url"))

        for cle, source in (
            ("twitter", "compte X déclaré sur GitLab"),
            ("skype", "compte Skype déclaré sur GitLab"),
            ("discord", "compte Discord déclaré sur GitLab"),
        ):
            if donnees.get(cle):
                resultat.ajouter(TypeDonnee.PSEUDO_ALT, donnees[cle], confiance=0.85, source=source)

        if donnees.get("linkedin"):
            resultat.ajouter(
                TypeDonnee.LIEN_EXTERNE,
                f"https://www.linkedin.com/in/{donnees['linkedin']}",
                confiance=0.9,
                source="profil LinkedIn déclaré sur GitLab",
            )

        bio = donnees.get("bio")
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")

        avatar = donnees.get("avatar_url")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
