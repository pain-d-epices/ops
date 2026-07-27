"""Module d'enrichissement Reddit.

Utilise le point d'accès public `about.json`, sans authentification. Reddit tolère
mal les robots anonymes : la limitation de débit globale est réglée bas pour ce
domaine dans config.yaml, et l'en-tête User-Agent identifie clairement le service.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleReddit(ModuleSite):
    nom = "reddit"
    libelle = "Reddit"
    domaines = ["reddit.com", "old.reddit.com"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self._identifiant(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(f"https://www.reddit.com/user/{identifiant}/about.json")
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or "data" not in donnees:
            resultat.erreur = f"Profil Reddit introuvable pour « {identifiant} »."
            return resultat

        contenu = donnees.get("data") or {}
        resultat.donnees_brutes = contenu
        self._extraire(resultat, contenu, client)
        return resultat

    @staticmethod
    def _identifiant(url: str) -> str | None:
        """Extrait le nom d'utilisateur d'une URL Reddit (/user/x, /u/x)."""
        segments = [s for s in url.split("?")[0].split("/") if s]
        for marqueur in ("user", "u"):
            if marqueur in segments:
                position = segments.index(marqueur)
                if position + 1 < len(segments):
                    return segments[position + 1]
        return None

    def _extraire(self, resultat: ResultatEnrichissement, contenu: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, contenu.get("name"))
        if contenu.get("created_utc"):
            resultat.ajouter(TypeDonnee.DATE_CREATION, int(contenu["created_utc"]))

        profil_public = contenu.get("subreddit") or {}
        description = profil_public.get("public_description") or profil_public.get("title")
        resultat.ajouter(TypeDonnee.BIO, description)
        resultat.ajouter(TypeDonnee.NB_ABONNES, profil_public.get("subscribers"))

        for email in self.extraire_emails(description):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="description du profil")
        for lien in self.extraire_urls(description):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="description du profil")
        for mention in self.extraire_mentions(description):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="description du profil")

        # Reddit sert souvent l'avatar via une URL contenant des paramètres échappés
        avatar = (profil_public.get("icon_img") or contenu.get("icon_img") or "").split("?")[0]
        if avatar and "reddit_default" not in avatar and "avatar_default" not in avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
