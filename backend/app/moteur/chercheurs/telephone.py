"""Chercheur par numéro de téléphone.

S'appuie sur **libphonenumber** (bibliothèque de Google, licence Apache 2.0, donc
utilisable dans un produit commercial fermé) pour tout ce qui est déductible du numéro
lui-même : validité, pays, opérateur d'origine, type de ligne, fuseau horaire.

Ces éléments ne désignent personne à eux seuls, mais ils orientent l'enquête et
alimentent la corrélation : un numéro mobile français attribué à un opérateur donné
est cohérent — ou non — avec une localisation déclarée sur un profil.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.config import config_metier
from app.modeles.enums import TypeDonnee, TypePointDepart
from app.moteur.chercheurs.base import Chercheur, RappelProgression, ResultatChercheur
from app.moteur.user_scanner_runner import OptionsUserScanner, runner_user_scanner

journal = logging.getLogger(__name__)

LIBELLES_TYPE_LIGNE = {
    0: "ligne fixe",
    1: "mobile",
    2: "fixe ou mobile",
    3: "numéro gratuit",
    4: "numéro surtaxé",
    5: "coût partagé",
    6: "voix sur IP",
    7: "numéro personnel",
    8: "radiomessagerie",
    9: "carte prépayée",
    10: "usage interne",
    27: "voix sur IP",
}


class ChercheurTelephone(Chercheur):
    nom = "telephone"
    libelle = "Numéro de téléphone"
    exemple = "+33 6 12 34 56 78"
    type_point_depart = TypePointDepart.TELEPHONE.value
    fonctionnalite_requise = "recherche_telephone"

    def disponible(self) -> bool:
        try:
            import phonenumbers  # noqa: F401
        except ImportError:
            journal.warning("La bibliothèque phonenumbers est absente : chercheur désactivé")
            return False
        return True

    def valider(self, valeur: str) -> str | None:
        valeur = (valeur or "").strip()
        chiffres = re.sub(r"[^\d+]", "", valeur)
        return chiffres if len(chiffres.lstrip("+")) >= 6 else None

    def chercher(
        self,
        valeur: str,
        options: dict[str, Any] | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatChercheur:
        import phonenumbers
        from phonenumbers import carrier, geocoder, timezone

        options = options or {}
        resultat = ResultatChercheur(entree=valeur, type_entree=self.type_point_depart)
        debut = time.monotonic()

        numero_brut = self.valider(valeur)
        if numero_brut is None:
            resultat.erreur = f"« {valeur} » n'est pas un numéro de téléphone exploitable."
            return resultat

        # Le pays par défaut sert aux numéros saisis sans indicatif international
        pays_defaut = str(
            options.get("pays_defaut") or config_metier().obtenir("telephone.pays_defaut", "FR")
        )

        try:
            numero = phonenumbers.parse(numero_brut, None if numero_brut.startswith("+") else pays_defaut)
        except phonenumbers.NumberParseException as exc:
            resultat.erreur = f"Numéro illisible : {exc}"
            return resultat

        if not phonenumbers.is_valid_number(numero):
            resultat.erreur = (
                "Ce numéro n'est pas valide. Vérifiez l'indicatif international "
                f"(pays supposé : {pays_defaut})."
            )
            return resultat

        format_international = phonenumbers.format_number(
            numero, phonenumbers.PhoneNumberFormat.E164
        )
        resultat.detail["numero_normalise"] = format_international

        resultat.ajouter_information(TypeDonnee.TELEPHONE, format_international, confiance=1.0)

        region = geocoder.description_for_number(numero, "fr")
        if region:
            resultat.ajouter_information(
                TypeDonnee.LOCALISATION, region, confiance=0.6, source="indicatif du numéro"
            )

        operateur = carrier.name_for_number(numero, "fr")
        if operateur:
            resultat.ajouter_information(
                TypeDonnee.ENTREPRISE,
                operateur,
                confiance=0.9,
                source="opérateur d'attribution du numéro",
            )

        type_ligne = phonenumbers.number_type(numero)
        resultat.detail["type_ligne"] = LIBELLES_TYPE_LIGNE.get(type_ligne, "inconnu")
        resultat.detail["pays"] = phonenumbers.region_code_for_number(numero)
        resultat.detail["fuseaux"] = list(timezone.time_zones_for_number(numero))
        resultat.nb_sources_consultees += 1

        if rappel:
            rappel(1, 2, f"Numéro validé ({resultat.detail['type_ligne']})")

        # user-scanner accepte un numéro comme identifiant sur certains services
        if options.get("user_scanner_actif", True) and config_metier().obtenir(
            "user_scanner.actif", True
        ):
            complement = runner_user_scanner().lancer(
                format_international, "pseudo", OptionsUserScanner.depuis_config()
            )
            resultat.comptes.extend(complement.sites)
            resultat.nb_sources_consultees += complement.nb_sites_testes
            if complement.erreur:
                journal.info("user-scanner indisponible pour ce numéro : %s", complement.erreur)

        if rappel:
            rappel(2, 2, "Recherche par téléphone terminée")
        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat
