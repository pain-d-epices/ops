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

journal = logging.getLogger(__name__)

#: Services d'annuaire inversé et de signalement d'appels. Ils génèrent une page pour
#: **tout** numéro, y compris ceux qui n'existent pas : en trouver une n'apprend rien
#: et masquerait les vraies pistes. Relevés en mesurant de vrais numéros le
#: 01/08/2026 ; complétable sans toucher au reste du code.
#:
#: Les annuaires qui publient un *contenu* propre (nom de l'établissement, adresse)
#: en sont volontairement absents : sur « 0140205050 », `annuaire-inverse-france.com`
#: et `infobel.com` donnaient tous deux la réponse — « Musée du Louvre ».
ANNUAIRES_INVERSES = frozenset({
    "truecaller.com", "getcontact.com", "robokiller.com", "numlookup.com",
    "whitepages.com", "thisnumber.com", "ipqualityscore.com", "who-called.co.uk",
    "findwhocallsyou.com", "numtrace.com", "degulesider.dk", "spamcalls.net",
    "shouldianswer.com", "callercenter.com", "phonenumbers.ie", "sync.me",
    "tellows.fr", "tellows.com", "411.com", "appelinconnu.fr", "uisjournal.com",
    "phonenumbers.org", "yellowpages.net", "usphonebook.com",
})

#: Domaines génériques renvoyés par le moteur quand la requête ressemble à une suite
#: de chiffres : ce sont des outils, pas des pages mentionnant le numéro.
DOMAINES_GENERIQUES = frozenset({
    "google.com", "maps.google.com", "bing.com", "duckduckgo.com",
    "calculatorsoup.com", "desmos.com", "w3calc.com",
})


def est_annuaire_inverse(domaine: str) -> bool:
    """Ce domaine est-il un service générique plutôt qu'une page de contenu ?"""
    domaine = (domaine or "").strip().lower().removeprefix("www.")
    if not domaine:
        return True
    indesirables = ANNUAIRES_INVERSES | DOMAINES_GENERIQUES
    return any(domaine == d or domaine.endswith("." + d) for d in indesirables)


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

        # --- Mentions du numéro sur le web ouvert ---
        # C'est ici que se trouve la valeur d'enquête : un numéro publié sur un
        # annuaire professionnel, une petite annonce ou une page d'entreprise relie le
        # numéro à un nom, une société ou une adresse.
        #
        # `user-scanner` a été retiré de ce chercheur : il teste des **noms
        # d'utilisateur**, or un numéro n'en est pas un. Mesuré le 01/08/2026, il
        # fabriquait de faux comptes — « https://youtube.com/@+33184944000 », alors
        # qu'un identifiant YouTube ne peut pas contenir de « + ». Annoncer à un
        # analyste que la cible possède un compte inexistant est le pire défaut
        # possible pour cet outil.
        self._chercher_mentions(numero, resultat, rappel)

        if rappel:
            rappel(2, 2, "Recherche par téléphone terminée")
        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat

    def _chercher_mentions(self, numero, resultat: ResultatChercheur, rappel=None) -> None:
        """Cherche le numéro sur le web, sous les graphies qui donnent des résultats.

        Deux enseignements de la mesure du 01/08/2026, qui dictent cette méthode :

        - **Le format compact est le seul qui fonctionne.** Cherché « 0140205050 »,
          le numéro du Louvre remonte l'annuaire inversé, Infobel et `contact.louvre.fr`.
          Cherché « 01 40 20 50 50 », le moteur traite les groupes comme des mots
          séparés et renvoie des calculatrices et des cartes. Les graphies espacées
          sont donc écartées.
        - **Les guillemets font échouer la requête.** `lite.duckduckgo.com` renvoie
          zéro résultat sur une expression entre guillemets ; sans eux, la même
          requête en renvoie six.
        """
        import re as _re

        import phonenumbers

        from app.moteur.sources.duckduckgo import rechercher_mentions

        if not config_metier().obtenir("telephone.recherche_web", True):
            return

        # Graphies compactes : nationale (« 0140205050 ») puis internationale
        # (« +33140205050 »). La première est celle sous laquelle les annuaires
        # publient un numéro national ; la seconde couvre les sites internationaux.
        national = _re.sub(
            r"\D", "", phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.NATIONAL)
        )
        international = phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.E164)
        graphies = [g for g in dict.fromkeys([national, international]) if g]

        nb_max = int(config_metier().obtenir("telephone.mentions_max", 8))
        vues: set[str] = set()
        retenues = 0
        for graphie in graphies:
            if retenues >= nb_max:
                break
            if rappel:
                rappel(1, 2, f"Recherche du numéro sur le web ({graphie})")
            for mention in rechercher_mentions(graphie, nb_max=nb_max):
                cle = mention.url.rstrip("/").lower()
                if cle in vues:
                    continue
                vues.add(cle)
                if est_annuaire_inverse(mention.domaine):
                    # Ces sites publient une page pour *tout* numéro : en trouver une
                    # ne prouve rien et noierait les vraies pistes.
                    continue
                if retenues >= nb_max:
                    break
                retenues += 1
                resultat.ajouter_information(
                    TypeDonnee.LIEN_EXTERNE,
                    mention.url,
                    confiance=0.5,   # une mention n'est pas une preuve d'appartenance
                    source="page mentionnant le numéro",
                    titre=mention.titre,
                    extrait=mention.extrait,
                )
            resultat.nb_sources_consultees += 1

        journal.info(
            "Numéro : %d page(s) consultée(s), %d retenue(s) après filtrage des annuaires",
            len(vues), retenues,
        )
