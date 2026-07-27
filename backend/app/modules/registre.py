"""Découverte automatique des modules de site.

Tout fichier de `app/modules/` contenant une classe héritant de `ModuleSite` est
chargé au démarrage. Le moteur choisit ensuite le module à appliquer d'après le
domaine du profil trouvé par Maigret.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil

from app.modules.base import ModuleSite

journal = logging.getLogger(__name__)

_modules: dict[str, ModuleSite] | None = None


def _decouvrir() -> dict[str, ModuleSite]:
    import app.modules as paquet

    trouves: dict[str, ModuleSite] = {}
    for info in pkgutil.iter_modules(paquet.__path__):
        if info.name in {"base", "registre"}:
            continue
        try:
            module_python = importlib.import_module(f"{paquet.__name__}.{info.name}")
        except Exception:  # noqa: BLE001 — un module défectueux ne doit pas bloquer le démarrage
            journal.exception("Module de site « %s » ignoré (erreur d'import)", info.name)
            continue

        for _, objet in inspect.getmembers(module_python, inspect.isclass):
            if (
                issubclass(objet, ModuleSite)
                and objet is not ModuleSite
                and objet.__module__ == module_python.__name__
            ):
                try:
                    instance = objet()
                except Exception:  # noqa: BLE001
                    journal.exception("Instanciation impossible du module « %s »", objet.__name__)
                    continue
                if instance.nom in trouves:
                    journal.warning("Deux modules portent le nom « %s » ; le second est ignoré", instance.nom)
                    continue
                trouves[instance.nom] = instance
    return trouves


def charger_modules(forcer: bool = False) -> dict[str, ModuleSite]:
    global _modules
    if _modules is None or forcer:
        _modules = _decouvrir()
        journal.info("%d modules de site chargés : %s", len(_modules), sorted(_modules))
    return _modules


def module_pour_domaine(domaine: str) -> ModuleSite | None:
    """Module capable d'enrichir un profil de ce domaine, s'il en existe un de disponible."""
    if not domaine:
        return None
    for module in charger_modules().values():
        if module.gere(domaine) and module.disponible():
            return module
    return None


def modules_disponibles() -> list[ModuleSite]:
    return [m for m in charger_modules().values() if m.disponible()]


def domaines_couverts() -> set[str]:
    couverts: set[str] = set()
    for module in modules_disponibles():
        couverts.update(module.domaines)
    return couverts


def reinitialiser_modules() -> None:
    global _modules
    _modules = None
