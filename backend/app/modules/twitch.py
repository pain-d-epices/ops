"""Module d'enrichissement Twitch.

API Helix officielle. Nécessite une application Twitch gratuite : identifiant et
secret à renseigner dans TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET
(https://dev.twitch.tv/console/apps).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import parametres
from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)

URL_JETON = "https://id.twitch.tv/oauth2/token"
URL_UTILISATEURS = "https://api.twitch.tv/helix/users"

# Jeton d'application mis en cache en mémoire : Twitch en délivre un valable
# plusieurs semaines, en redemander un à chaque enrichissement solliciterait
# inutilement leur serveur d'authentification.
_jeton_cache: dict[str, Any] = {"valeur": None, "expire_le": 0.0}


def _jeton_application() -> str | None:
    if _jeton_cache["valeur"] and time.monotonic() < _jeton_cache["expire_le"]:
        return _jeton_cache["valeur"]

    identifiant = parametres().twitch_client_id
    secret = parametres().twitch_client_secret
    if not identifiant or not secret:
        return None

    try:
        reponse = httpx.post(
            URL_JETON,
            params={"client_id": identifiant, "client_secret": secret, "grant_type": "client_credentials"},
            timeout=10,
        )
        reponse.raise_for_status()
        donnees = reponse.json()
    except (httpx.HTTPError, ValueError):
        journal.warning("Jeton Twitch inobtenable", exc_info=True)
        return None

    _jeton_cache["valeur"] = donnees.get("access_token")
    # Marge de sécurité de cinq minutes avant l'expiration annoncée
    _jeton_cache["expire_le"] = time.monotonic() + max(0, int(donnees.get("expires_in", 0)) - 300)
    return _jeton_cache["valeur"]


class ModuleTwitch(ModuleSite):
    nom = "twitch"
    libelle = "Twitch"
    domaines = ["twitch.tv", "www.twitch.tv"]
    necessite_cle_api = True

    def disponible(self) -> bool:
        return bool(parametres().twitch_client_id and parametres().twitch_client_secret)

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo

        jeton = _jeton_application()
        if not jeton:
            resultat.erreur = "Authentification Twitch indisponible (clé absente ou invalide)."
            return resultat

        client = ClientHttp(
            entetes_supplementaires={
                "Client-Id": parametres().twitch_client_id,
                "Authorization": f"Bearer {jeton}",
            }
        )

        try:
            donnees = client.obtenir_json(URL_UTILISATEURS, parametres_requete={"login": identifiant.lower()})
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        utilisateurs = (donnees or {}).get("data") if isinstance(donnees, dict) else None
        if not utilisateurs:
            resultat.erreur = f"Chaîne Twitch introuvable pour « {identifiant} »."
            return resultat

        chaine = utilisateurs[0]
        resultat.donnees_brutes = chaine
        self._extraire(resultat, chaine, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, chaine: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, chaine.get("display_name"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, chaine.get("created_at"))

        bio = chaine.get("description")
        resultat.ajouter(TypeDonnee.BIO, bio)
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="description de la chaîne")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="description de la chaîne")

        avatar = chaine.get("profile_image_url")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
