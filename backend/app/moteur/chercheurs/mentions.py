"""Exploitation des pages qui mentionnent un numéro ou une adresse.

Un chercheur par téléphone ou par adresse ne peut pas identifier le titulaire : rien
de public ne relie un numéro à une personne. En revanche, quand le numéro est
**professionnel ou institutionnel**, la réponse est écrite en toutes lettres dans les
pages qui le citent — et l'outil se contentait de rendre les liens.

Mesuré le 02/08/2026 sur le standard du Louvre (`+33140205050`) : le nom figurait dans
six titres sur huit et l'adresse postale complète dans un extrait, sans qu'aucun nœud
« entreprise » ou « localisation » ne soit produit. L'analyste devait ouvrir huit
onglets pour lire ce que l'outil avait déjà sous les yeux.

Deux extractions, toutes deux fondées sur le **consensus entre domaines** :

- le **nom de l'entité**, retenu seulement s'il apparaît sur au moins deux sites
  indépendants. Un titre isolé peut dire n'importe quoi ; deux sites qui nomment la
  même entité se corroborent. C'est le même principe que la corrélation des comptes ;
- l'**adresse postale**, reconnue à sa forme française (numéro, voie, code postal à
  cinq chiffres, commune).

Ces valeurs restent des **indices** : la confiance attribuée le dit (0.7 et 0.6), et
elles ne sont jamais présentées comme l'identité du titulaire.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from typing import Protocol

#: Services d'annuaire inversé et de signalement d'appels. Ils génèrent une page pour
#: **tout** numéro, y compris inexistant : en trouver une n'apprend rien et masquerait
#: les vraies pistes. Relevés en mesurant de vrais numéros les 01 et 02/08/2026 ;
#: complétable sans toucher au reste du code.
#:
#: Les annuaires qui publient un *contenu* propre (nom de l'établissement, adresse) en
#: sont volontairement absents : sur « 0140205050 », `annuaire-inverse-france.com` et
#: `infobel.com` donnaient tous deux la réponse — « Musée du Louvre ».
ANNUAIRES_INVERSES = frozenset({
    "truecaller.com", "getcontact.com", "robokiller.com", "numlookup.com",
    "whitepages.com", "thisnumber.com", "ipqualityscore.com", "who-called.co.uk",
    "findwhocallsyou.com", "numtrace.com", "degulesider.dk", "spamcalls.net",
    "shouldianswer.com", "callercenter.com", "phonenumbers.ie", "sync.me",
    "tellows.fr", "tellows.com", "411.com", "appelinconnu.fr", "uisjournal.com",
    "phonenumbers.org", "yellowpages.net", "usphonebook.com",
    # Ajoutés le 02/08/2026 : passaient au travers du filtre sur « 0140205050 »,
    # alors qu'ils ne publient que des compteurs d'avis (« 7 opinions, majoritaire :
    # indifférent »), sans jamais nommer le titulaire.
    "quinumero.info", "pagesjaunes-inverse.fr", "annuaire-inverse.net",
    "qui-appelle.fr", "numero-inconnu.fr", "signal-arnaques.com",
    "telefoonnummer.info", "nomorobo.com", "everycaller.com", "callerid.com",
})

#: Domaines génériques renvoyés par le moteur quand la requête ressemble à une suite
#: de chiffres ou à une adresse : ce sont des outils (cartes, itinéraires,
#: calculatrices), pas des pages de contenu sur la valeur cherchée.
DOMAINES_GENERIQUES = frozenset({
    "google.com", "maps.google.com", "bing.com", "duckduckgo.com",
    "calculatorsoup.com", "desmos.com", "w3calc.com",
    # Ajoutés le 02/08/2026 : bruit constaté sur la recherche par adresse, qui
    # n'appliquait aucun filtre (itinéraires, estimation immobilière, cartographie).
    "ratp.fr", "citymapper.com", "mappy.com", "viamichelin.fr", "waze.com",
    "openstreetmap.org", "meilleursagents.com", "seloger.com", "logic-immo.com",
    "yelp.com", "tripadvisor.fr", "tripadvisor.com",
})

#: Formulations typiques des pages sans contenu propre. Un extrait qui n'en sort pas
#: ne dit rien du titulaire, quel que soit le domaine — utile là où la liste de
#: domaines est forcément en retard sur le web.
MOTIFS_SANS_CONTENU = (
    re.compile(r"\bqui\s+est\s+ce\s+num[ée]ro\b", re.IGNORECASE),
    re.compile(r"\b[àa]\s+qui\s+appartient\s+ce\s+num[ée]ro\b", re.IGNORECASE),
    re.compile(r"\bnombre\s+d.opinions\b", re.IGNORECASE),
    re.compile(r"\bopinion\s+majoritaire\b", re.IGNORECASE),
    re.compile(r"\b(who|whose)\s+(is|called)\s+(this|that)\s+number\b", re.IGNORECASE),
    re.compile(r"\bunknown\s+caller\b", re.IGNORECASE),
    re.compile(r"\bsignaler\s+ce\s+num[ée]ro\b", re.IGNORECASE),
)

#: Suffixes de titre à retirer : « <contenu> - <nom du site> », « <contenu> | <site> ».
SEPARATEURS_TITRE = re.compile(r"\s+[-–—|·:]\s+")

#: Amorces rédactionnelles fréquentes des annuaires, à retirer avant comparaison.
#: « Comment contacter Musée du Louvre : téléphone » -> « Musée du Louvre ».
AMORCES_TITRE = re.compile(
    r"^(?:comment\s+)?(?:contacter|joindre|appeler|t[ée]l[ée]phone\s+de|"
    r"num[ée]ro\s+de|coordonn[ée]es\s+de|avis\s+sur|horaires\s+de|adresse\s+de)\s+",
    re.IGNORECASE,
)

#: Adresse postale française : numéro de voie, libellé, code postal, commune.
#: Le numéro de voie est borné à quatre chiffres pour ne pas confondre avec un
#: numéro de téléphone collé au texte (« 0140205050 musées - Paris »).
MOTIF_ADRESSE_FR = re.compile(
    r"\b(\d{1,4}(?:\s*(?:bis|ter|quater))?)\s+"          # numéro de voie
    r"([A-Za-zÀ-ÿ][\w'’.\-]*(?:\s+[\w'’.\-]+){0,6}?)"    # libellé de voie
    r"\s*,?\s+(\d{5})\s+"                                # code postal
    r"([A-Za-zÀ-ÿ][\wÀ-ÿ'’\-]*(?:[\s\-][A-Za-zÀ-ÿ][\wÀ-ÿ'’\-]*){0,3})",  # commune
    re.UNICODE,
)

#: En deçà, un « nom » n'est qu'un fragment : trop court pour désigner une entité.
LONGUEUR_MINIMALE_NOM = 4
LONGUEUR_MAXIMALE_NOM = 80

#: Nombre de domaines distincts devant nommer la même entité. Deux suffisent : un
#: titre isolé peut dire n'importe quoi, deux sites indépendants se corroborent.
DOMAINES_CONCORDANTS_MINIMUM = 2


class Mention(Protocol):
    """Ce que cette analyse attend d'une mention (cf. `sources.duckduckgo.MentionWeb`)."""

    url: str
    titre: str
    extrait: str

    @property
    def domaine(self) -> str: ...


def _normaliser(valeur: str) -> str:
    """Forme comparable : minuscules, sans accent, espaces réduits."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFKD", valeur) if not unicodedata.combining(c)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sans_accent.lower()).split())


def est_domaine_sans_contenu(domaine: str) -> bool:
    """Ce domaine est-il un service générique plutôt qu'une page de contenu ?"""
    domaine = (domaine or "").strip().lower().removeprefix("www.")
    if not domaine:
        return True
    indesirables = ANNUAIRES_INVERSES | DOMAINES_GENERIQUES
    return any(domaine == d or domaine.endswith("." + d) for d in indesirables)


def est_mention_sans_contenu(mention: Mention) -> bool:
    """Page inutile : domaine générique, ou contenu réduit à « qui est ce numéro ? ».

    Le second critère rattrape ce que la liste de domaines laisse passer : elle sera
    toujours en retard sur les sites qui apparaissent, alors que ces formulations, elles,
    ne changent pas.
    """
    if est_domaine_sans_contenu(mention.domaine):
        return True
    texte = f"{mention.titre} {mention.extrait}"
    return any(motif.search(texte) for motif in MOTIFS_SANS_CONTENU)


def _candidats_de_titre(titre: str) -> list[str]:
    """Segments d'un titre susceptibles de nommer l'entité.

    « MUSEE DU LOUVRE Paris - Annuaire inversé » donne « MUSEE DU LOUVRE Paris » ;
    « Comment contacter Musée du Louvre : téléphone » donne « Musée du Louvre ».
    Tous les segments sont proposés : le consensus entre domaines fera le tri.
    """
    candidats: list[str] = []
    for segment in SEPARATEURS_TITRE.split(titre or ""):
        segment = AMORCES_TITRE.sub("", segment.strip(" \t-–—|·:,")).strip()
        # Une virgule sépare souvent le nom de sa ville : « Musée Du Louvre, Paris, FR »
        for morceau in (segment, segment.split(",")[0].strip()):
            if LONGUEUR_MINIMALE_NOM <= len(morceau) <= LONGUEUR_MAXIMALE_NOM:
                candidats.append(morceau)
    return candidats


def nom_entite_consensuel(mentions: Iterable[Mention]) -> str | None:
    """Nom d'entité sur lequel au moins deux domaines distincts s'accordent.

    Renvoie la graphie la plus lisible parmi celles rencontrées (on préfère
    « Musée du Louvre » à « MUSEE DU LOUVRE »), ou None si rien ne fait consensus —
    ce qui est le cas normal pour un numéro de particulier.
    """
    domaines_par_nom: dict[str, set[str]] = defaultdict(set)
    graphies: dict[str, list[str]] = defaultdict(list)

    for mention in mentions:
        if est_mention_sans_contenu(mention):
            continue
        domaine = mention.domaine.removeprefix("www.")
        for candidat in _candidats_de_titre(mention.titre):
            cle = _normaliser(candidat)
            if len(cle) < LONGUEUR_MINIMALE_NOM or cle.isdigit():
                continue
            domaines_par_nom[cle].add(domaine)
            graphies[cle].append(candidat)

    retenus = {
        cle: domaines
        for cle, domaines in domaines_par_nom.items()
        if len(domaines) >= DOMAINES_CONCORDANTS_MINIMUM
    }
    if not retenus:
        return None

    # Le nom le plus corroboré ; à égalité, le plus spécifique (le plus long).
    meilleure_cle = max(retenus, key=lambda c: (len(retenus[c]), len(c)))
    # Graphie la plus lisible : on écarte les titres tout en majuscules quand une
    # variante en casse normale existe.
    return min(
        graphies[meilleure_cle],
        key=lambda g: (g.isupper(), len(g)),
    )


def adresse_postale(mentions: Iterable[Mention], numero_a_ignorer: str = "") -> str | None:
    """Première adresse postale française reconnue dans les extraits.

    `numero_a_ignorer` évite qu'une suite de chiffres appartenant au numéro recherché
    ne soit prise pour un numéro de voie.
    """
    chiffres_numero = re.sub(r"\D", "", numero_a_ignorer or "")

    for mention in mentions:
        if est_mention_sans_contenu(mention):
            continue
        for correspondance in MOTIF_ADRESSE_FR.finditer(mention.extrait or ""):
            numero_voie, voie, code_postal, commune = correspondance.groups()
            if chiffres_numero and numero_voie in chiffres_numero:
                continue
            if code_postal in chiffres_numero:
                continue
            adresse = f"{numero_voie} {voie} {code_postal} {commune}".strip()
            adresse = " ".join(adresse.split())
            if len(adresse) <= 120:
                return adresse
    return None
