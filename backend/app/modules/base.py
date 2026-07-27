"""Socle du système de modules d'enrichissement par site.

Un module sait interroger **un** site et en extraire des informations exploitables
(bio, avatar, localisation, liens, date de création, autres pseudonymes, emails).

Pour ajouter le support d'un site : créer un fichier dans `app/modules/`, hériter de
`ModuleSite`, déclarer `nom` et `domaines`, implémenter `enrichir`. Le registre le
découvre automatiquement au démarrage — aucun enregistrement manuel.

Voir le guide détaillé : docs/ajouter-un-module.md
"""

from __future__ import annotations

import io
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.modeles.enums import TypeDonnee
from app.moteur.correlation.base import normaliser

journal = logging.getLogger(__name__)

MOTIF_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
MOTIF_MENTION = re.compile(r"(?:^|[\s(,;])@([A-Za-z0-9_.-]{3,30})\b")
MOTIF_URL = re.compile(r"https?://[^\s<>\"')]+")

# Domaines dont l'extrait d'URL ne constitue pas un pseudonyme exploitable
DOMAINES_NON_PIVOTABLES = {
    "t.co", "bit.ly", "goo.gl", "tinyurl.com", "example.com",
    "wikipedia.org", "youtube.com", "google.com",
}


@dataclass
class InfoExtraite:
    """Une information tirée d'un profil."""

    type: TypeDonnee
    valeur: str
    confiance: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def valeur_normalisee(self) -> str:
        if self.type in (TypeDonnee.EMAIL, TypeDonnee.LIEN_EXTERNE, TypeDonnee.AVATAR_URL):
            return self.valeur.strip().lower()[:500]
        if self.type == TypeDonnee.AVATAR_PHASH:
            return self.valeur.strip().lower()[:500]
        return normaliser(self.valeur)[:500]


@dataclass
class ResultatEnrichissement:
    """Sortie d'un module pour un profil donné."""

    module: str
    informations: list[InfoExtraite] = field(default_factory=list)
    erreur: str | None = None
    donnees_brutes: dict[str, Any] = field(default_factory=dict)

    @property
    def reussi(self) -> bool:
        return self.erreur is None

    def ajouter(
        self,
        type_donnee: TypeDonnee,
        valeur: Any,
        confiance: float = 1.0,
        **meta: Any,
    ) -> None:
        """Ajoute une information en ignorant les valeurs vides ou inutilisables."""
        if valeur is None:
            return
        texte = str(valeur).strip()
        if not texte or texte.lower() in {"none", "null", "n/a", "-"}:
            return
        self.informations.append(
            InfoExtraite(type=type_donnee, valeur=texte[:2000], confiance=confiance, meta=meta)
        )

    def valeurs(self, type_donnee: TypeDonnee) -> list[str]:
        return [i.valeur for i in self.informations if i.type == type_donnee]


class ModuleSite(ABC):
    """Interface commune à tous les modules d'enrichissement."""

    #: identifiant technique du module (unique)
    nom: str = ""
    #: nom affiché dans l'interface
    libelle: str = ""
    #: domaines pris en charge, sans « www. » (ex. ["github.com", "api.github.com"])
    domaines: list[str] = []
    #: le module nécessite-t-il une clé API pour fonctionner ?
    necessite_cle_api: bool = False

    @abstractmethod
    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        """Extrait les informations disponibles pour ce profil."""

    def disponible(self) -> bool:
        """Le module est-il utilisable en l'état (clé API présente, etc.) ?

        Un module indisponible est simplement ignoré : l'enrichissement des autres
        sites continue normalement.
        """
        return True

    def gere(self, domaine: str) -> bool:
        domaine = (domaine or "").lower().removeprefix("www.")
        return any(domaine == d or domaine.endswith(f".{d}") for d in self.domaines)

    # --- Utilitaires partagés par les modules -------------------------------

    @staticmethod
    def extraire_emails(texte: str | None) -> list[str]:
        if not texte:
            return []
        return list(dict.fromkeys(m.lower() for m in MOTIF_EMAIL.findall(texte)))

    @staticmethod
    def extraire_mentions(texte: str | None) -> list[str]:
        """Pseudonymes mentionnés sous la forme « @quelquechose » dans un texte."""
        if not texte:
            return []
        return list(dict.fromkeys(MOTIF_MENTION.findall(texte)))

    @staticmethod
    def extraire_urls(texte: str | None) -> list[str]:
        if not texte:
            return []
        return list(dict.fromkeys(MOTIF_URL.findall(texte)))

    @staticmethod
    def pseudo_depuis_url(url: str) -> str | None:
        """Déduit un pseudonyme du dernier segment d'une URL de profil.

        Renvoie None pour les raccourcisseurs et les sites génériques, dont le chemin
        ne désigne pas une personne.
        """
        try:
            analyse = urlparse(url if "://" in url else f"https://{url}")
        except ValueError:
            return None
        domaine = (analyse.netloc or "").lower().removeprefix("www.")
        if not domaine or any(domaine.endswith(d) for d in DOMAINES_NON_PIVOTABLES):
            return None
        segments = [s for s in (analyse.path or "").split("/") if s]
        if not segments:
            return None
        candidat = segments[-1].lstrip("@")
        if len(candidat) < 3 or len(candidat) > 40 or "." in candidat:
            return None
        return candidat

    @staticmethod
    def hash_perceptuel(contenu_image: bytes | None) -> str | None:
        """Empreinte perceptuelle d'une image d'avatar.

        Résiste au redimensionnement et à la recompression : c'est ce qui permet de
        reconnaître le même avatar servi en 64 px sur un site et en 400 px sur un autre.
        """
        if not contenu_image:
            return None
        try:
            import imagehash
            from PIL import Image

            with Image.open(io.BytesIO(contenu_image)) as image:
                return str(imagehash.phash(image.convert("RGB")))
        except Exception:  # noqa: BLE001 — une image illisible ne doit rien interrompre
            journal.debug("Calcul du hash perceptuel impossible", exc_info=True)
            return None

    def __repr__(self) -> str:
        return f"<Module {self.nom} ({', '.join(self.domaines)})>"
