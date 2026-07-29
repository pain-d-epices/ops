"""Chercheur de pseudonymes : Maigret, complété par user-scanner.

Les deux outils se recoupent partiellement mais ne couvrent pas les mêmes sites :
Maigret construit des URLs de profil sur ~3000 sites, user-scanner interroge les
formulaires d'inscription de ~220 autres et renvoie en prime des données de profil
déjà extraites. Les faire tourner ensemble élargit sensiblement la couverture.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import config_metier
from app.modeles.enums import TypePointDepart
from app.moteur.chercheurs.base import Chercheur, RappelProgression, ResultatChercheur
from app.moteur.maigret_runner import OptionsRecherche, runner
from app.moteur.user_scanner_runner import OptionsUserScanner, runner_user_scanner

journal = logging.getLogger(__name__)


class ChercheurPseudo(Chercheur):
    nom = "pseudo"
    libelle = "Pseudonyme"
    exemple = "jeanmartin"
    type_point_depart = TypePointDepart.PSEUDO.value
    # Accessible à tous les paliers : c'est la fonctionnalité d'appel du produit
    fonctionnalite_requise = ""

    def chercher(
        self,
        valeur: str,
        options: dict[str, Any] | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatChercheur:
        options = options or {}
        resultat = ResultatChercheur(entree=valeur, type_entree=self.type_point_depart)
        debut = time.monotonic()

        # --- Maigret : le socle historique ---
        options_maigret = OptionsRecherche.depuis_config(
            top_sites=options.get("top_sites"),
            sites_exclus=options.get("sites_exclus") or [],
            extraction_activee=bool(options.get("extraction_activee")),
        )
        resultat_maigret = runner().lancer(valeur, options_maigret, rappel=rappel)

        resultat.comptes.extend(resultat_maigret.comptes_trouves)
        resultat.nb_sources_consultees += resultat_maigret.nb_sites_total
        if resultat_maigret.erreur:
            resultat.erreur = resultat_maigret.erreur

        # --- user-scanner : couverture complémentaire ---
        if options.get("user_scanner_actif", True) and config_metier().obtenir(
            "user_scanner.actif", True
        ):
            urls_connues = {compte.url.rstrip("/").lower() for compte in resultat.comptes}
            complement = runner_user_scanner().lancer(
                valeur, "pseudo", OptionsUserScanner.depuis_config()
            )
            for compte in complement.sites:
                # Ne pas compter deux fois un site déjà trouvé par Maigret
                if compte.url.rstrip("/").lower() in urls_connues:
                    continue
                resultat.comptes.append(compte)
            resultat.nb_sources_consultees += complement.nb_sites_testes
            if complement.erreur:
                journal.info("user-scanner indisponible pour « %s » : %s", valeur, complement.erreur)

        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat
