"""Chercheur par adresse postale.

Utilise **Nominatim** (OpenStreetMap, données sous ODbL, service gratuit) pour
normaliser une adresse et en obtenir les coordonnées. Pour les adresses françaises,
l'API de la Base Adresse Nationale est interrogée en priorité : plus précise sur le
territoire et sans limite de débit contraignante.

L'apport principal n'est pas la géolocalisation en soi, mais la **normalisation** :
« 12 rue de la Paix, Paris » et « 12 R. de la Paix 75002 » deviennent comparables, ce
qui permet de les rapprocher des localisations déclarées sur les profils.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import config_metier
from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee, TypePointDepart
from app.moteur.chercheurs.base import Chercheur, RappelProgression, ResultatChercheur

journal = logging.getLogger(__name__)

URL_NOMINATIM = "https://nominatim.openstreetmap.org/search"
URL_BAN = "https://api-adresse.data.gouv.fr/search/"


class ChercheurAdresse(Chercheur):
    nom = "adresse"
    libelle = "Recherche par adresse postale"
    type_point_depart = TypePointDepart.ADRESSE.value
    fonctionnalite_requise = "recherche_adresse"

    def valider(self, valeur: str) -> str | None:
        valeur = (valeur or "").strip()
        # Une adresse exploitable comporte au moins un numéro et un libellé de voie
        return valeur if len(valeur) >= 5 and len(valeur.split()) >= 2 else None

    def chercher(
        self,
        valeur: str,
        options: dict[str, Any] | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatChercheur:
        options = options or {}
        resultat = ResultatChercheur(entree=valeur, type_entree=self.type_point_depart)
        debut = time.monotonic()

        adresse = self.valider(valeur)
        if adresse is None:
            resultat.erreur = f"« {valeur} » est trop imprécis pour être recherché comme adresse."
            return resultat

        if rappel:
            rappel(1, 2, "Normalisation de l'adresse")

        trouvee = self._chercher_ban(adresse, resultat)
        if not trouvee:
            self._chercher_nominatim(adresse, resultat)

        if rappel:
            rappel(2, 2, "Recherche par adresse terminée")
        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat

    def _chercher_ban(self, adresse: str, resultat: ResultatChercheur) -> bool:
        """Base Adresse Nationale : précise, gratuite, sans clé, pour la France."""
        if not config_metier().obtenir("adresse.utiliser_ban", True):
            return False

        client = ClientHttp()
        try:
            donnees = client.obtenir_json(URL_BAN, parametres_requete={"q": adresse, "limit": 1})
        except (ErreurReseau, DebitDepasse) as exc:
            journal.info("Base Adresse Nationale injoignable : %s", exc)
            return False

        if not isinstance(donnees, dict):
            return False
        resultats = donnees.get("features") or []
        if not resultats:
            return False

        proprietes = resultats[0].get("properties") or {}
        # En dessous de ce score, la correspondance est trop incertaine pour être
        # présentée comme un fait à un analyste.
        if float(proprietes.get("score", 0)) < 0.5:
            return False

        resultat.nb_sources_consultees += 1
        resultat.detail["source"] = "Base Adresse Nationale"
        resultat.detail["score_correspondance"] = round(float(proprietes.get("score", 0)), 2)

        resultat.ajouter_information(
            TypeDonnee.LOCALISATION,
            proprietes.get("label"),
            confiance=float(proprietes.get("score", 0.5)),
            source="Base Adresse Nationale",
        )
        for cle, type_donnee in (("city", TypeDonnee.LOCALISATION), ("context", TypeDonnee.LOCALISATION)):
            if proprietes.get(cle):
                resultat.ajouter_information(
                    type_donnee, proprietes[cle], confiance=0.7, source="Base Adresse Nationale"
                )

        coordonnees = (resultats[0].get("geometry") or {}).get("coordinates")
        if coordonnees and len(coordonnees) == 2:
            resultat.detail["longitude"], resultat.detail["latitude"] = coordonnees
        return True

    def _chercher_nominatim(self, adresse: str, resultat: ResultatChercheur) -> None:
        """Nominatim : couverture mondiale, en repli de la Base Adresse Nationale."""
        # Nominatim exige un User-Agent identifiable et limite à une requête par
        # seconde : la politique d'usage du service l'impose explicitement.
        client = ClientHttp()
        try:
            donnees = client.obtenir_json(
                URL_NOMINATIM,
                parametres_requete={
                    "q": adresse,
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 1,
                },
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = f"Service de géocodage injoignable : {exc}"
            return

        if not isinstance(donnees, list) or not donnees:
            resultat.detail["adresse_introuvable"] = True
            return

        lieu = donnees[0]
        resultat.nb_sources_consultees += 1
        resultat.detail["source"] = "Nominatim (OpenStreetMap)"

        resultat.ajouter_information(
            TypeDonnee.LOCALISATION,
            lieu.get("display_name"),
            confiance=0.8,
            source="Nominatim (OpenStreetMap)",
        )
        detail_adresse = lieu.get("address") or {}
        for cle in ("city", "town", "village", "state", "country"):
            if detail_adresse.get(cle):
                resultat.ajouter_information(
                    TypeDonnee.LOCALISATION, detail_adresse[cle], confiance=0.7, source="Nominatim"
                )
                break

        if lieu.get("lat") and lieu.get("lon"):
            resultat.detail["latitude"] = float(lieu["lat"])
            resultat.detail["longitude"] = float(lieu["lon"])
