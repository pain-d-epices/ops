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

# Segments qui *précèdent* le nom d'utilisateur dans une adresse de profil :
# `linkedin.com/in/jean-martin`, `reddit.com/user/jeanmartin`,
# `steamcommunity.com/id/jeanmartin`. C'est le segment suivant qu'il faut retenir.
SEGMENTS_PREFIXE_PROFIL = {
    "in", "user", "users", "u", "profile", "profiles", "profil",
    "people", "member", "members", "author", "id",
}

# Premiers segments qui signalent une page qui n'est pas un profil : une publication
# (`instagram.com/p/ABC123`), un fil (`x.com/i/...`), un sous-forum
# (`reddit.com/r/...`). Extraire un « pseudonyme » de ces adresses lancerait une
# recherche sur un identifiant technique ou un mot de vocabulaire du site.
SEGMENTS_NON_PROFIL = {
    "p", "reel", "reels", "explore", "status", "statuses", "post", "posts",
    "hashtag", "tag", "tags", "search", "watch", "channel", "c", "group",
    "groups", "events", "pages", "share", "video", "videos", "photo", "photos",
    "media", "stories", "story", "live", "shop", "accounts", "i", "intent",
    "download", "feed", "notifications", "messages", "settings", "dashboard",
    "wiki", "article", "articles", "questions", "comments", "r", "topic", "forum",
}

# Un chemin qui se termine par un nom de fichier n'est pas un profil
# (`facebook.com/profile.php?id=…`, `site.fr/index.html`).
EXTENSIONS_FICHIER = {
    "php", "html", "htm", "asp", "aspx", "jsp", "cgi", "json", "xml",
    "jpg", "jpeg", "png", "gif", "webp", "svg", "pdf", "txt",
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
        """Déduit un pseudonyme d'une URL de profil.

        Le nom d'utilisateur est cherché au **début** du chemin, pas à la fin : c'est
        là qu'il se trouve dans la quasi-totalité des adresses de profil
        (`instagram.com/jeanmartin`, `github.com/jeanmartin/un-depot`). Prendre le
        dernier segment donnait « reels » pour `instagram.com/jeanmartin/reels/` et
        l'identifiant du message pour `x.com/jeanmartin/status/1234`.

        Renvoie None pour les raccourcisseurs, les sites génériques et les adresses
        qui ne désignent pas un profil (publication, sous-forum, fichier).
        """
        # Importé ici pour garder `modules` indépendant de `moteur.pivot` au chargement
        from app.moteur.pivot.detecteur import pseudo_exploitable

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

        premier = segments[0].lower()
        if segments[0].startswith("@"):
            # Forme « handle » : mastodon.social/@jeanmartin, tiktok.com/@jeanmartin
            candidat = segments[0]
        elif premier in SEGMENTS_PREFIXE_PROFIL:
            if len(segments) < 2:
                return None
            candidat = segments[1]
        elif premier in SEGMENTS_NON_PROFIL:
            return None
        else:
            candidat = segments[0]

        candidat = candidat.lstrip("@")
        if "." in candidat and candidat.rsplit(".", 1)[-1].lower() in EXTENSIONS_FICHIER:
            return None
        # `pseudo_exploitable` fait autorité dans le projet sur ce qui constitue un
        # pseudonyme recherchable : longueur, caractères admis (les points le sont —
        # `jean.martin` est courant sur Instagram et TikTok), mots trop génériques,
        # suites de chiffres.
        if not pseudo_exploitable(candidat):
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
