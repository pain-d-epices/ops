"""Identification des comptes trouvés sur des sites à caractère sexuel.

Le palier gratuit n'y a pas accès : ces résultats sont écartés avant enregistrement,
donc jamais présentés ni exportés. C'est une limite commerciale, mais aussi une
précaution — un compte de ce type est la donnée la plus sensible qu'une investigation
puisse révéler, et le palier gratuit n'est soumis à aucune vérification d'usage.

## Deux sources d'identification, volontairement

1. **Les étiquettes de Maigret** (`porn`, `erotic`, `webcam`…). Elles font autorité
   quand elles sont présentes : elles viennent de la base de sites elle-même.
2. **Une liste explicite de domaines.** Une quinzaine de sites manifestement adultes
   de la base de Maigret n'ont aucune étiquette adéquate (Fansly, Eporner,
   AdultFriendFinder, PornhubPornstars…). S'appuyer sur les seules étiquettes les
   laisserait passer.

Un filtrage par mots-clés dans le domaine a été écarté : il produit des faux
positifs difficiles à prévoir (« illustrators.ru » contient « lust »,
« antiscam.space » contient « scam » donc « cam », « forums.wyzecam.com » aussi).
Mieux vaut une liste explicite, vérifiable et complétable.

En cas de doute, la règle est d'écarter : sur-filtrer prive le palier gratuit d'un
résultat, sous-filtrer lui livre ce qu'il n'a pas acheté.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from app.moteur.maigret_runner import ResultatSite

#: Étiquettes de la base Maigret qui désignent un site à caractère sexuel.
#: `webcam` en fait partie : dans cette base, elle ne désigne que des sites de
#: diffusion pour adultes (Livejasmin, Stripchat, BongaCams, Chaturbate…).
#: `dating` en est volontairement absente : un site de rencontres n'est pas
#: pornographique, et l'exclure priverait d'un signal d'investigation légitime.
TAGS_SENSIBLES = frozenset({
    "porn", "erotic", "nsfw", "xxx", "adult", "webcam", "escort", "hentai",
})

#: Domaines à caractère sexuel de la base Maigret dépourvus d'étiquette adéquate.
#: Relevés en parcourant la base ; à compléter si Maigret en ajoute.
DOMAINES_SENSIBLES = frozenset({
    "adultfriendfinder.com",
    "adultism.com",
    "actual-porn.org",
    "eporner.com",
    "fabswingers.com",
    "fansly.com",
    "pornsavant.com",
    "seneporno.com",
    "sexforum.ixbb.ru",
    "sexforum.ws",
    "sexforum.win",
    "sexopedia.ru",
    "smutty.com",
})

#: Noms de sites sans domaine exploitable dans la base (`urlMain` absent).
NOMS_SENSIBLES = frozenset({
    "pornhubpornstars",
    "fansly",
    "seneporno",
    "fabswingers",
    "eporner",
})


def _domaine_correspond(domaine: str) -> bool:
    """Vrai si le domaine, ou l'un de ses domaines parents, figure dans la liste.

    Comparer par suffixe permet de couvrir les sous-domaines et les miroirs
    (`m.smutty.com` comme `smutty.com`) sans les énumérer.
    """
    domaine = domaine.strip().lower().removeprefix("www.")
    if not domaine:
        return False
    return any(
        domaine == sensible or domaine.endswith("." + sensible)
        for sensible in DOMAINES_SENSIBLES
    )


def est_site_sensible(
    site_nom: str | None,
    site_domaine: str | None,
    tags: Iterable[str] | None = None,
) -> bool:
    """Ce compte est-il hébergé par un site à caractère sexuel ?"""
    etiquettes = {str(t).strip().lower() for t in (tags or []) if str(t).strip()}
    if etiquettes & TAGS_SENSIBLES:
        return True
    if _domaine_correspond(site_domaine or ""):
        return True
    return (site_nom or "").strip().lower() in NOMS_SENSIBLES


T = TypeVar("T", bound="ResultatSite")


def filtrer_sites_sensibles(sites: list[T]) -> tuple[list[T], int]:
    """Retire les comptes sur sites sensibles.

    Renvoie la liste conservée et le nombre d'éléments écartés — ce dernier est
    journalisé plutôt que masqué : un filtrage silencieux rendrait un écart de
    résultats entre deux paliers impossible à expliquer.
    """
    conserves = [
        site
        for site in sites
        if not est_site_sensible(site.site_nom, site.site_domaine, site.tags)
    ]
    return conserves, len(sites) - len(conserves)
