"""Découverte automatique des sources complémentaires.

Même principe que les modules de site et les chercheurs : tout fichier de
`app/moteur/sources/` contenant une classe héritant de `SourceComplementaire` est
chargé au démarrage. Ajouter une source (un nouveau moteur de recherche dark web, par
exemple) ne demande donc aucune modification de `executer_recherche`.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil

from app.moteur.sources.base import SourceComplementaire

journal = logging.getLogger(__name__)

_sources: dict[str, SourceComplementaire] | None = None


def _decouvrir() -> dict[str, SourceComplementaire]:
    import app.moteur.sources as paquet

    trouvees: dict[str, SourceComplementaire] = {}
    for info in pkgutil.iter_modules(paquet.__path__):
        if info.name in {"base", "registre"}:
            continue
        try:
            module_python = importlib.import_module(f"{paquet.__name__}.{info.name}")
        except Exception:  # noqa: BLE001 — une source défectueuse ne doit pas bloquer le démarrage
            journal.exception("Source complémentaire « %s » ignorée (erreur d'import)", info.name)
            continue

        for _, objet in inspect.getmembers(module_python, inspect.isclass):
            try:
                est_source = issubclass(objet, SourceComplementaire) and objet is not SourceComplementaire
            except TypeError:
                # `inspect.isclass` laisse passer certains alias de typage qui font
                # ensuite échouer `issubclass` avec une TypeError (même précaution
                # que pour les modules et les chercheurs).
                continue
            if not (est_source and objet.__module__ == module_python.__name__ and objet.nom):
                continue
            try:
                instance = objet()
            except Exception:  # noqa: BLE001
                journal.exception("Instanciation impossible de la source « %s »", objet.__name__)
                continue
            if instance.nom in trouvees:
                journal.warning("Deux sources portent le nom « %s » ; la seconde est ignorée", instance.nom)
                continue
            trouvees[instance.nom] = instance
    return trouvees


def charger_sources(forcer: bool = False) -> dict[str, SourceComplementaire]:
    global _sources
    if _sources is None or forcer:
        _sources = _decouvrir()
        journal.info("%d source(s) complémentaire(s) chargée(s) : %s", len(_sources), sorted(_sources))
    return _sources


def sources_disponibles() -> list[SourceComplementaire]:
    return [s for s in charger_sources().values() if s.disponible()]


def reinitialiser_sources() -> None:
    global _sources
    _sources = None
