"""Chercheur par adresse électronique.

Trois voies complémentaires, de la plus fiable à la plus indicative :

1. **Gravatar** — le hash MD5 de l'adresse donne accès à un profil public que la
   personne a elle-même rempli : nom, sites déclarés, comptes liés. C'est la seule
   source qui renvoie de véritables informations, et non une simple présence.
2. **Partie locale comme pseudonyme** — `jean.martin@…` conduit à rechercher
   `jean.martin`, ce qui rebranche toute la puissance de la recherche par pseudonyme.
3. **user-scanner** — répond à « cette adresse est-elle inscrite ici ? » sur ~144
   sites. Utile pour cartographier une présence, mais ne fournit ni lien de profil ni
   donnée exploitable : ces résultats sont donc marqués comme non identifiants.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any

from app.config import config_metier
from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee, TypePointDepart
from app.modules.base import ModuleSite
from app.moteur.chercheurs.base import Chercheur, RappelProgression, ResultatChercheur
from app.moteur.user_scanner_runner import OptionsUserScanner, runner_user_scanner

journal = logging.getLogger(__name__)

MOTIF_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]{2,}$")

# Domaines jetables : trouver un compte derrière n'apprend rien sur une personne
DOMAINES_JETABLES = {
    "mailinator.com", "yopmail.com", "guerrillamail.com", "10minutemail.com",
    "tempmail.com", "throwawaymail.com", "trashmail.com",
}


class ChercheurEmail(Chercheur):
    nom = "email"
    libelle = "Recherche par adresse électronique"
    type_point_depart = TypePointDepart.EMAIL.value
    fonctionnalite_requise = "recherche_email"

    def valider(self, valeur: str) -> str | None:
        valeur = (valeur or "").strip().lower()
        return valeur if MOTIF_EMAIL.match(valeur) else None

    def chercher(
        self,
        valeur: str,
        options: dict[str, Any] | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatChercheur:
        options = options or {}
        adresse = self.valider(valeur)
        resultat = ResultatChercheur(entree=valeur, type_entree=self.type_point_depart)

        if adresse is None:
            resultat.erreur = f"« {valeur} » n'est pas une adresse électronique valide."
            return resultat

        debut = time.monotonic()
        partie_locale, domaine = adresse.split("@", 1)

        resultat.ajouter_information(TypeDonnee.EMAIL, adresse, confiance=1.0)

        if domaine in DOMAINES_JETABLES:
            resultat.detail["domaine_jetable"] = True
            journal.info("Adresse jetable détectée : %s", domaine)

        # --- 1. Gravatar ---
        if rappel:
            rappel(1, 3, "Consultation de Gravatar")
        self._chercher_gravatar(adresse, resultat)

        # --- 2. La partie locale devient un pseudonyme à rechercher ---
        # C'est le pivot le plus fructueux : beaucoup de personnes réutilisent la
        # partie locale de leur adresse comme pseudonyme sur d'autres sites.
        if ModuleSite.pseudo_depuis_url(f"https://exemple.fr/{partie_locale}"):
            resultat.ajouter_information(
                TypeDonnee.PSEUDO_ALT,
                partie_locale,
                confiance=0.7,
                source="partie locale de l'adresse électronique",
            )

        # --- 3. user-scanner : présence sur les sites ---
        if options.get("user_scanner_actif", True) and config_metier().obtenir(
            "user_scanner.actif", True
        ):
            if rappel:
                rappel(2, 3, "Recherche de la présence de l'adresse sur les sites")
            complement = runner_user_scanner().lancer(
                adresse, "email", OptionsUserScanner.depuis_config()
            )
            resultat.comptes.extend(complement.sites)
            resultat.nb_sources_consultees += complement.nb_sites_testes
            if complement.erreur:
                journal.info("user-scanner indisponible pour « %s » : %s", adresse, complement.erreur)

        if rappel:
            rappel(3, 3, "Recherche par adresse terminée")
        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat

    def _chercher_gravatar(self, adresse: str, resultat: ResultatChercheur) -> None:
        """Interroge le profil public Gravatar associé à l'adresse.

        Gravatar est un service d'avatar universel : le profil, quand il existe, a été
        rempli volontairement par la personne. C'est donc une source publique et
        consentie, contrairement à un test d'inscription.
        """
        empreinte = hashlib.md5(adresse.encode("utf-8")).hexdigest()  # noqa: S324 — imposé par l'API Gravatar
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(f"https://fr.gravatar.com/{empreinte}.json")
        except (ErreurReseau, DebitDepasse) as exc:
            journal.info("Gravatar injoignable pour cette adresse : %s", exc)
            return

        if not isinstance(donnees, dict):
            return

        profils = donnees.get("entry") or []
        if not profils:
            return
        profil = profils[0]

        resultat.detail["gravatar"] = True
        resultat.ajouter_information(
            TypeDonnee.NOM_AFFICHE, profil.get("displayName"), confiance=0.9, source="Gravatar"
        )
        resultat.ajouter_information(
            TypeDonnee.BIO, (profil.get("aboutMe") or "")[:2000], confiance=0.9, source="Gravatar"
        )

        nom = profil.get("name") or {}
        if isinstance(nom, dict) and nom.get("formatted"):
            resultat.ajouter_information(
                TypeDonnee.NOM_REEL, nom["formatted"], confiance=0.85, source="Gravatar"
            )

        for lieu in profil.get("currentLocation") or []:
            resultat.ajouter_information(TypeDonnee.LOCALISATION, lieu, confiance=0.8, source="Gravatar")

        # Comptes déclarés par la personne sur son profil Gravatar : pistes fiables
        for compte in profil.get("accounts") or []:
            if not isinstance(compte, dict):
                continue
            if compte.get("url"):
                resultat.ajouter_information(
                    TypeDonnee.LIEN_EXTERNE,
                    compte["url"],
                    confiance=0.95,
                    source=f"compte {compte.get('shortname', '')} déclaré sur Gravatar",
                )
            if compte.get("username"):
                resultat.ajouter_information(
                    TypeDonnee.PSEUDO_ALT,
                    compte["username"],
                    confiance=0.9,
                    source=f"compte {compte.get('shortname', '')} déclaré sur Gravatar",
                )

        for lien in profil.get("urls") or []:
            if isinstance(lien, dict) and lien.get("value"):
                resultat.ajouter_information(
                    TypeDonnee.LIEN_EXTERNE, lien["value"], confiance=0.9, source="Gravatar"
                )

        avatar = profil.get("thumbnailUrl")
        if avatar:
            resultat.ajouter_information(TypeDonnee.AVATAR_URL, avatar, source="Gravatar")
            empreinte_image = ModuleSite.hash_perceptuel(client.telecharger(avatar))
            if empreinte_image:
                resultat.ajouter_information(
                    TypeDonnee.AVATAR_PHASH, empreinte_image, source="avatar Gravatar"
                )
