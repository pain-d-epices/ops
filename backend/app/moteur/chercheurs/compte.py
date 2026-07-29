"""Chercheur à partir de l'adresse d'un compte.

Permet de démarrer une investigation avec un profil déjà identifié
(`https://github.com/quelquun`) plutôt qu'avec un pseudonyme seul.

Deux temps :

1. le compte fourni est enregistré tel quel et enrichi par le module du site, s'il
   en existe un — on récupère ainsi immédiatement bio, avatar, localisation, liens ;
2. le pseudonyme extrait de l'adresse alimente la recherche large habituelle.

Le premier temps a une valeur particulière : l'analyste **sait** que ce compte
appartient à sa cible. Il est donc enregistré comme certain, ce qui donne au moteur de
corrélation un point de référence solide au lieu d'une simple hypothèse.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

from app.modeles.enums import StatutMaigret, TypeDonnee, TypePointDepart
from app.modules.base import ModuleSite
from app.modules.registre import module_pour_domaine
from app.moteur.chercheurs.base import Chercheur, RappelProgression, ResultatChercheur
from app.moteur.maigret_runner import ResultatSite

journal = logging.getLogger(__name__)


class ChercheurCompte(Chercheur):
    nom = "compte"
    libelle = "Recherche à partir d'un compte connu"
    type_point_depart = TypePointDepart.COMPTE.value
    fonctionnalite_requise = "recherche_depuis_compte"

    def valider(self, valeur: str) -> str | None:
        valeur = (valeur or "").strip()
        if not valeur:
            return None
        if "://" not in valeur:
            valeur = f"https://{valeur}"
        try:
            analyse = urlparse(valeur)
        except ValueError:
            return None
        # Une adresse de compte comporte un domaine et un chemin identifiant
        if not analyse.netloc or "." not in analyse.netloc:
            return None
        return valeur

    def chercher(
        self,
        valeur: str,
        options: dict[str, Any] | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatChercheur:
        options = options or {}
        resultat = ResultatChercheur(entree=valeur, type_entree=self.type_point_depart)
        debut = time.monotonic()

        url = self.valider(valeur)
        if url is None:
            resultat.erreur = f"« {valeur} » n'est pas une adresse de profil exploitable."
            return resultat

        domaine = urlparse(url).netloc.lower()
        pseudo = ModuleSite.pseudo_depuis_url(url)
        module = module_pour_domaine(domaine)

        if rappel:
            rappel(1, 2, f"Enregistrement du compte {domaine}")

        # Le compte fourni par l'analyste est tenu pour acquis : c'est son point de
        # départ, pas une hypothèse à valider.
        resultat.comptes.append(
            ResultatSite(
                site_nom=(module.libelle if module else domaine.removeprefix("www.")),
                site_domaine=domaine,
                url=url,
                pseudo=pseudo or url,
                statut=StatutMaigret.TROUVE,
                brut={"_source": "point_de_depart", "fourni_par_analyste": True},
            )
        )
        resultat.nb_sources_consultees += 1
        resultat.detail["module_disponible"] = module.nom if module else None

        # Le pseudonyme déduit relance la recherche large : c'est lui qui transforme
        # un compte isolé en cartographie.
        if pseudo:
            resultat.ajouter_information(
                TypeDonnee.PSEUDO_ALT,
                pseudo,
                confiance=0.95,
                source=f"pseudonyme extrait de l'adresse fournie ({domaine})",
            )

        if module is None:
            journal.info("Aucun module d'enrichissement pour %s", domaine)

        if rappel:
            rappel(2, 2, "Compte enregistré")
        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat
