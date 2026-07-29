"""Module d'enrichissement Goodreads.

Goodreads a fermé son API publique en 2020, mais continue de servir sans clé les
flux RSS des étagères de lecture : c'est la seule voie gratuite restante. L'apport
est modeste (pas de biographie structurée), mais confirme le compte et permet de
chercher des pivots dans les titres publiés.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleGoodreads(ModuleSite):
    nom = "goodreads"
    libelle = "Goodreads"
    domaines = ["goodreads.com"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self._identifiant_numerique(url_profil)
        if not identifiant:
            resultat.erreur = "Identifiant numérique Goodreads introuvable dans l'URL."
            return resultat

        client = ClientHttp()
        try:
            reponse = client.obtenir(
                f"https://www.goodreads.com/review/list_rss/{identifiant}",
                parametres_requete={"shelf": "read"},
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if reponse.status_code >= 400:
            resultat.erreur = f"Étagère Goodreads introuvable pour l'identifiant « {identifiant} »."
            return resultat

        try:
            racine = ET.fromstring(reponse.text)
        except ET.ParseError:
            resultat.erreur = "Flux Goodreads illisible."
            return resultat

        canal = racine.find("channel")
        if canal is None:
            resultat.erreur = f"Étagère Goodreads introuvable pour l'identifiant « {identifiant} »."
            return resultat

        self._extraire(resultat, canal)
        return resultat

    @staticmethod
    def _identifiant_numerique(url: str) -> str | None:
        """L'identifiant Goodreads précède le tiret dans .../show/12345678-jean-martin."""
        segments = [s for s in url.split("?")[0].rstrip("/").split("/") if s]
        if not segments:
            return None
        candidat = segments[-1].split("-")[0]
        return candidat if candidat.isdigit() else None

    def _extraire(self, resultat: ResultatEnrichissement, canal: ET.Element) -> None:
        titre = (canal.findtext("title") or "").strip()
        description = (canal.findtext("description") or "").strip()
        resultat.donnees_brutes = {"titre": titre, "description": description}

        texte_libre = f"{titre} {description}"
        for email in self.extraire_emails(texte_libre):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.7, source="étagère Goodreads")
        for lien in self.extraire_urls(texte_libre):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.7, source="étagère Goodreads")

        # Les titres des livres lus permettent d'y chercher les mêmes pivots ; on se
        # limite aux premiers pour rester léger.
        for item in canal.findall("item")[:20]:
            titre_livre = item.findtext("title") or ""
            for mention in self.extraire_mentions(titre_livre):
                resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.4, source="étagère Goodreads")
