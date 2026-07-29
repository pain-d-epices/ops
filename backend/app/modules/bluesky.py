"""Module d'enrichissement Bluesky.

Bluesky repose sur le protocole AT, dont l'API de consultation est entièrement
ouverte : aucune clé, aucune authentification pour lire un profil public.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)

API_PUBLIQUE = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"


class ModuleBluesky(ModuleSite):
    nom = "bluesky"
    libelle = "Bluesky"
    domaines = ["bsky.app", "bsky.social", "public.api.bsky.app"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self._identifiant(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(API_PUBLIQUE, parametres_requete={"actor": identifiant})
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not donnees.get("handle"):
            resultat.erreur = f"Profil Bluesky introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    @staticmethod
    def _identifiant(url: str) -> str | None:
        """Extrait l'identifiant d'une URL de la forme /profile/quelquechose.bsky.social."""
        segments = [s for s in url.split("?")[0].split("/") if s]
        if "profile" in segments:
            position = segments.index("profile")
            if position + 1 < len(segments):
                return segments[position + 1]
        # Certains résultats pointent directement vers bsky.app/identifiant
        return segments[-1] if len(segments) > 1 else None

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("displayName"))
        resultat.ajouter(TypeDonnee.BIO, donnees.get("description"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("createdAt"))
        resultat.ajouter(TypeDonnee.NB_ABONNES, donnees.get("followersCount"))

        # Le handle contient souvent un domaine personnel vérifié : « prenom.fr » plutôt
        # que « prenom.bsky.social ». C'est alors une piste de premier ordre, puisque
        # l'utilisateur a dû prouver qu'il contrôlait ce domaine.
        handle = str(donnees.get("handle") or "")
        if handle and not handle.endswith(".bsky.social"):
            resultat.ajouter(
                TypeDonnee.LIEN_EXTERNE,
                f"https://{handle}",
                confiance=0.95,
                source="domaine personnel vérifié sur Bluesky",
            )

        description = donnees.get("description")
        for email in self.extraire_emails(description):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(description):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")
            pseudo_deduit = self.pseudo_depuis_url(lien)
            if pseudo_deduit:
                resultat.ajouter(
                    TypeDonnee.PSEUDO_ALT, pseudo_deduit, confiance=0.6, source="lien de la biographie"
                )
        for mention in self.extraire_mentions(description):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="biographie")

        avatar = donnees.get("avatar")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
