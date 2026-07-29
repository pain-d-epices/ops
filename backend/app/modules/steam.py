"""Module d'enrichissement Steam.

Utilise le format XML public des profils (`?xml=1`), officiellement prévu par Valve
et accessible sans clé d'API. C'est un choix délibéré : l'API Web de Steam
imposerait à chaque exploitant du service d'obtenir et de configurer une clé, alors
que ce point d'accès fournit déjà les informations publiques du profil.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement
from app.modules.mastodon import nettoyer_html

journal = logging.getLogger(__name__)


class ModuleSteam(ModuleSite):
    nom = "steam"
    libelle = "Steam"
    domaines = ["steamcommunity.com"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        # Un profil est accessible soit par son alias (/id/alias), soit par son
        # identifiant numérique (/profiles/7656…). On tente les deux formes.
        chemins = ["id", "profiles"] if identifiant.isdigit() else ["id"]
        racine = None

        for chemin in chemins:
            try:
                reponse = client.obtenir(f"https://steamcommunity.com/{chemin}/{identifiant}/?xml=1")
            except (ErreurReseau, DebitDepasse) as exc:
                resultat.erreur = str(exc)
                return resultat

            if reponse.status_code >= 400:
                continue
            try:
                candidat = ET.fromstring(reponse.text)
            except ET.ParseError:
                continue
            # Steam renvoie un document <response><error> quand le profil n'existe pas
            if candidat.tag == "profile":
                racine = candidat
                break

        if racine is None:
            resultat.erreur = f"Profil Steam introuvable pour « {identifiant} »."
            return resultat

        self._extraire(resultat, racine, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, racine: ET.Element, client: ClientHttp) -> None:
        def texte(balise: str) -> str | None:
            element = racine.find(balise)
            return element.text.strip() if element is not None and element.text else None

        resultat.donnees_brutes = {
            balise: texte(balise)
            for balise in ("steamID", "steamID64", "customURL", "realname", "location", "memberSince")
        }

        resultat.ajouter(TypeDonnee.NOM_AFFICHE, texte("steamID"))
        # Le nom réel est saisi volontairement par l'utilisateur : signal fort
        resultat.ajouter(TypeDonnee.NOM_REEL, texte("realname"), confiance=0.9)
        resultat.ajouter(TypeDonnee.LOCALISATION, texte("location"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, texte("memberSince"))

        # L'alias personnalisé est un pseudonyme choisi, souvent réutilisé ailleurs
        alias = texte("customURL")
        if alias:
            resultat.ajouter(
                TypeDonnee.PSEUDO_ALT, alias, confiance=0.85, source="alias Steam personnalisé"
            )

        resume = nettoyer_html(texte("summary"))
        resultat.ajouter(TypeDonnee.BIO, resume)
        for email in self.extraire_emails(resume):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="description du profil")
        for lien in self.extraire_urls(resume):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="description du profil")

        avatar = texte("avatarFull") or texte("avatarMedium")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
