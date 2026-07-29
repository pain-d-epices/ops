"""Module d'enrichissement Letterboxd.

Le site sert un flux RSS public du journal de chaque compte, sans clé ni
authentification. Comme pour Goodreads, l'apport est surtout la confirmation du
compte et la recherche de pivots dans le texte des critiques publiées.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement
from app.modules.mastodon import nettoyer_html

journal = logging.getLogger(__name__)


class ModuleLetterboxd(ModuleSite):
    nom = "letterboxd"
    libelle = "Letterboxd"
    domaines = ["letterboxd.com"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            reponse = client.obtenir(f"https://letterboxd.com/{identifiant}/rss/")
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if reponse.status_code >= 400:
            resultat.erreur = f"Journal Letterboxd introuvable pour « {identifiant} »."
            return resultat

        try:
            racine = ET.fromstring(reponse.text)
        except ET.ParseError:
            resultat.erreur = "Flux Letterboxd illisible."
            return resultat

        canal = racine.find("channel")
        if canal is None:
            resultat.erreur = f"Journal Letterboxd introuvable pour « {identifiant} »."
            return resultat

        self._extraire(resultat, canal)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, canal: ET.Element) -> None:
        titre = (canal.findtext("title") or "").strip()
        description = (canal.findtext("description") or "").strip()
        resultat.donnees_brutes = {"titre": titre, "description": description}

        # Les critiques (« description » de chaque entrée) sont parfois assez
        # personnelles pour contenir un pivot ; on les agrège, dans une limite
        # raisonnable.
        textes = [titre, description]
        for item in canal.findall("item")[:10]:
            textes.append(nettoyer_html(item.findtext("description")))
        texte_libre = " ".join(t for t in textes if t)[:5000]

        for email in self.extraire_emails(texte_libre):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.7, source="journal Letterboxd")
        for lien in self.extraire_urls(texte_libre):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.7, source="journal Letterboxd")
        for mention in self.extraire_mentions(texte_libre):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.4, source="journal Letterboxd")
