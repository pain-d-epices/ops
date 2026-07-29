"""Découverte automatique des chercheurs.

Même principe que les modules de site : tout fichier de `chercheurs/` contenant une
classe héritant de `Chercheur` est chargé au démarrage. Ajouter un type de recherche
ne demande donc aucune modification du moteur.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil

from app.moteur.chercheurs.base import Chercheur

journal = logging.getLogger(__name__)

_chercheurs: dict[str, Chercheur] | None = None


def _est_chercheur_concret(objet: object, nom_module: str) -> bool:
    """Filtre les vrais chercheurs parmi les membres d'un module.

    `inspect.isclass` laisse passer les alias de typage — un `Callable[..., None]`
    comme notre `RappelProgression`, ou un `dict[str, Any]`. En Python 3.10 ils
    satisfont même `isinstance(objet, type)`, et ce n'est qu'au moment du `issubclass`
    qu'ils lèvent une TypeError. D'où cette vérification défensive : elle rend la
    découverte insensible aux imports présents dans les modules de chercheurs.
    """
    try:
        if not issubclass(objet, Chercheur) or objet is Chercheur:  # type: ignore[arg-type]
            return False
    except TypeError:
        return False
    # Seules les classes définies dans ce module comptent : sinon un chercheur
    # importé par un autre serait enregistré deux fois.
    if objet.__module__ != nom_module:
        return False
    # Une classe sans type de point de départ est un socle mutualisé, pas un chercheur
    return bool(getattr(objet, "type_point_depart", ""))


def _decouvrir() -> dict[str, Chercheur]:
    import app.moteur.chercheurs as paquet

    trouves: dict[str, Chercheur] = {}
    for info in pkgutil.iter_modules(paquet.__path__):
        if info.name in {"base", "registre"}:
            continue
        try:
            module_python = importlib.import_module(f"{paquet.__name__}.{info.name}")
        except Exception:  # noqa: BLE001 — un chercheur défectueux ne doit pas bloquer le démarrage
            journal.exception("Chercheur « %s » ignoré (erreur d'import)", info.name)
            continue

        for _, objet in inspect.getmembers(module_python, inspect.isclass):
            if not _est_chercheur_concret(objet, module_python.__name__):
                continue
            try:
                instance = objet()
            except Exception:  # noqa: BLE001
                journal.exception("Instanciation impossible du chercheur « %s »", objet.__name__)
                continue
            if instance.type_point_depart in trouves:
                journal.warning(
                    "Deux chercheurs traitent le type « %s » ; le second est ignoré",
                    instance.type_point_depart,
                )
                continue
            trouves[instance.type_point_depart] = instance
    return trouves


def charger_chercheurs(forcer: bool = False) -> dict[str, Chercheur]:
    global _chercheurs
    if _chercheurs is None or forcer:
        _chercheurs = _decouvrir()
        journal.info(
            "%d chercheurs chargés : %s", len(_chercheurs), sorted(_chercheurs)
        )
    return _chercheurs


def chercheur_pour(type_point_depart: str) -> Chercheur | None:
    """Chercheur capable de traiter ce type de point de départ, s'il est disponible."""
    chercheur = charger_chercheurs().get(type_point_depart)
    if chercheur is None or not chercheur.disponible():
        return None
    return chercheur


def chercheurs_disponibles() -> list[Chercheur]:
    return [c for c in charger_chercheurs().values() if c.disponible()]


def reinitialiser_chercheurs() -> None:
    global _chercheurs
    _chercheurs = None
