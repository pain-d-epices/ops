"""Découverte automatique des règles de corrélation.

Toute classe héritant de `RegleCorrelation` placée dans `regles/` est chargée au
démarrage. Son poids et ses paramètres proviennent de `config.yaml`, section
`correlation.regles.<nom>`. Une règle absente de la configuration reste active avec
un poids de 1.0 ; une règle marquée `actif: false` est ignorée.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any

from app.config import config_metier
from app.moteur.correlation.base import RegleCorrelation

journal = logging.getLogger(__name__)

_regles_chargees: list[RegleCorrelation] | None = None


def _classes_de_regles() -> list[type[RegleCorrelation]]:
    from app.moteur.correlation import regles as paquet_regles

    classes: list[type[RegleCorrelation]] = []
    for info in pkgutil.iter_modules(paquet_regles.__path__):
        try:
            module = importlib.import_module(f"{paquet_regles.__name__}.{info.name}")
        except Exception:  # noqa: BLE001 — une règle défectueuse ne doit pas empêcher le démarrage
            journal.exception("Règle de corrélation « %s » ignorée (erreur d'import)", info.name)
            continue

        for _, objet in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(objet, RegleCorrelation)
                and objet is not RegleCorrelation
                and objet.__module__ == module.__name__
            ):
                classes.append(objet)
    return classes


def charger_regles(forcer: bool = False) -> list[RegleCorrelation]:
    """Instancie les règles actives, configurées d'après config.yaml."""
    global _regles_chargees
    if _regles_chargees is not None and not forcer:
        return _regles_chargees

    configuration: dict[str, Any] = config_metier().section("correlation").get("regles", {}) or {}
    instances: list[RegleCorrelation] = []

    for classe in _classes_de_regles():
        nom = classe.nom or classe.__name__
        parametres_regle = dict(configuration.get(nom, {}))
        if parametres_regle.get("actif") is False:
            journal.info("Règle de corrélation « %s » désactivée par configuration", nom)
            continue
        poids = float(parametres_regle.pop("poids", 1.0))
        parametres_regle.pop("actif", None)
        instances.append(classe(poids=poids, config=parametres_regle))

    instances.sort(key=lambda regle: regle.nom)
    _regles_chargees = instances
    journal.info("%d règles de corrélation chargées : %s", len(instances), [r.nom for r in instances])
    return instances


def reinitialiser_regles() -> None:
    """Vide le cache des règles (tests, ou rechargement après modification de config.yaml)."""
    global _regles_chargees
    _regles_chargees = None
