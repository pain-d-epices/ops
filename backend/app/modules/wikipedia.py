"""Module d'enrichissement Wikipédia / Wikimédia.

API MediaWiki publique, sans clé. La page utilisateur documente souvent des centres
d'intérêt et des liens vers d'autres comptes ; la date d'inscription se lit depuis
l'historique public. Couvre toutes les éditions linguistiques (fr.wikipedia.org,
en.wikipedia.org…) via la correspondance par suffixe de domaine.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


def nettoyer_wikitexte(texte: str | None) -> str:
    """Réduit le wikitexte à du texte lisible : suffisant pour y chercher des pivots.

    Ni un rendu fidèle ni un analyseur complet — juste de quoi repérer une adresse,
    une mention ou un lien dans la page utilisateur, sans les accolades et crochets.
    """
    if not texte:
        return ""
    sans_modeles = re.sub(r"\{\{[^{}]*\}\}", " ", texte)
    # [[lien|texte affiché]] -> texte affiché ; [[lien]] -> lien
    sans_liens = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", sans_modeles)
    sans_gras = sans_liens.replace("'''", "").replace("''", "")
    sans_balises = re.sub(r"<[^>]+>", " ", sans_gras)
    return " ".join(sans_balises.split())


class ModuleWikipedia(ModuleSite):
    nom = "wikipedia"
    libelle = "Wikipédia"
    domaines = ["wikipedia.org", "wikimedia.org", "wiktionary.org", "wikidata.org"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        analyse = urlparse(url_profil if "://" in url_profil else f"https://{url_profil}")
        wiki = analyse.netloc
        identifiant = self._identifiant(url_profil) or pseudo

        if not wiki:
            resultat.erreur = "Édition Wikipédia indéterminable depuis l'URL."
            return resultat

        client = ClientHttp()
        try:
            donnees = client.obtenir_json(
                f"https://{wiki}/w/api.php",
                parametres_requete={
                    "action": "query", "list": "users", "ususers": identifiant,
                    "usprop": "registration", "format": "json",
                },
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        utilisateurs = ((donnees or {}).get("query") or {}).get("users") or []
        if not utilisateurs or "missing" in utilisateurs[0]:
            resultat.erreur = f"Compte Wikipédia introuvable pour « {identifiant} » sur {wiki}."
            return resultat

        resultat.donnees_brutes = utilisateurs[0]
        resultat.ajouter(TypeDonnee.DATE_CREATION, utilisateurs[0].get("registration"))
        self._extraire_page_utilisateur(resultat, client, wiki, identifiant)
        return resultat

    def _extraire_page_utilisateur(
        self, resultat: ResultatEnrichissement, client: ClientHttp, wiki: str, identifiant: str
    ) -> None:
        """Contenu de la page utilisateur : non bloquant, beaucoup de comptes n'en
        ont jamais rédigé une."""
        try:
            page = client.obtenir_json(
                f"https://{wiki}/w/api.php",
                parametres_requete={
                    "action": "parse", "page": f"User:{identifiant}",
                    "prop": "wikitext", "format": "json",
                },
            )
        except (ErreurReseau, DebitDepasse):
            return

        wikitexte = (((page or {}).get("parse") or {}).get("wikitext") or {}).get("*")
        bio = nettoyer_wikitexte(wikitexte)
        if not bio:
            return

        resultat.ajouter(TypeDonnee.BIO, bio[:2000])
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="page utilisateur")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="page utilisateur")
        for mention in self.extraire_mentions(bio):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="page utilisateur")

    @staticmethod
    def _identifiant(url: str) -> str | None:
        """Le pseudonyme suit « /wiki/User: » (ou sa variante localisée « Utilisateur: »)."""
        segments = [s for s in url.split("?")[0].rstrip("/").split("/") if s]
        if not segments:
            return None
        dernier = segments[-1]
        if ":" in dernier:
            return dernier.split(":", 1)[1] or None
        return None
