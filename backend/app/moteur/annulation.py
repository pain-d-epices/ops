"""Arrêt d'une investigation en cours.

## Pourquoi une annulation *coopérative* et non un `revoke` Celery

Celery sait révoquer une tâche, mais `revoke(terminate=True)` tue le processus qui
l'exécute. Le worker de ce projet tourne en `--pool=solo` sous Windows (contrainte
documentée dans le README) : le processus qui exécute la tâche **est** le worker.
Le terminer arrêterait donc le service entier pour tous les clients, pas une seule
recherche.

Par ailleurs, une investigation n'est pas *une* tâche mais une chaîne :
recherche → enrichissement → pivot → nouvelle recherche… Chaque maillon met le
suivant en file. Révoquer le maillon en cours laisserait les suivants démarrer.

D'où ce mécanisme : un **drapeau d'arrêt** que chaque étape consulte à ses points de
reprise. Toute étape qui le voit levé s'interrompt proprement et n'enchaîne pas sur
la suivante. C'est aussi ce qui permet d'interrompre Maigret, dont le sous-processus
est surveillé pendant son exécution (voir `maigret_runner`).

## Où vit le drapeau

La **base de données fait foi** : `investigations.statut == "annulee"` survit à un
redémarrage de Redis comme du worker, et c'est déjà la valeur que lit l'interface.

Redis n'est qu'un **cache de lecture rapide**, parce que la surveillance de Maigret
consulte le drapeau chaque seconde pendant plusieurs minutes : y répondre par une
requête SQL à chaque fois chargerait la base sans raison. Redis absent, tout continue
de fonctionner — simplement avec une requête SQL par consultation.
"""

from __future__ import annotations

import logging

from app.infra.redis_client import client_redis, signaler_panne

journal = logging.getLogger(__name__)

#: Durée de vie du drapeau dans Redis. Large devant la durée maximale d'une
#: investigation (rebonds compris), courte devant l'accumulation de clés mortes.
DUREE_DRAPEAU_SECONDES = 24 * 3600


def _cle(investigation_id: str) -> str:
    return f"annulation:investigation:{investigation_id}"


def marquer_annulation(investigation_id: str) -> None:
    """Lève le drapeau d'arrêt dans le cache rapide.

    N'écrit **pas** en base : l'appelant (l'endpoint d'annulation) le fait dans sa
    propre transaction, avec le reste de ses écritures. Cette fonction ne gère que
    le cache.
    """
    client = client_redis()
    if client is None:
        return
    try:
        client.setex(_cle(investigation_id), DUREE_DRAPEAU_SECONDES, "1")
    except Exception:  # noqa: BLE001 — Redis absent : la base fait foi de toute façon
        signaler_panne()


def oublier_annulation(investigation_id: str) -> None:
    """Retire le drapeau du cache (relance d'une investigation, tests)."""
    client = client_redis()
    if client is None:
        return
    try:
        client.delete(_cle(investigation_id))
    except Exception:  # noqa: BLE001
        signaler_panne()


def _drapeau_dans_cache(investigation_id: str) -> bool | None:
    """True/False si le cache répond, None s'il est indisponible."""
    client = client_redis()
    if client is None:
        return None
    try:
        return client.exists(_cle(investigation_id)) > 0
    except Exception:  # noqa: BLE001
        signaler_panne()
        return None


def est_annulee(investigation_id: str, session=None) -> bool:
    """L'investigation a-t-elle été annulée ?

    Consulte d'abord le cache. Un drapeau présent fait foi immédiatement ; son
    absence est confirmée en base quand une session est fournie, car le cache peut
    avoir expiré ou Redis avoir redémarré.

    Sans session, seul le cache est consulté : c'est le mode utilisé par la
    surveillance de Maigret, qui interroge chaque seconde et n'a pas de session
    ouverte (l'appel réseau se fait volontairement hors transaction).
    """
    dans_cache = _drapeau_dans_cache(investigation_id)
    if dans_cache:
        return True
    if session is None:
        # Cache muet et pas de base à consulter : ne pas interrompre une recherche
        # sur un doute. Le prochain point de reprise disposant d'une session
        # tranchera.
        return False

    from app.modeles.enums import StatutInvestigation
    from app.modeles.investigation import Investigation

    statut = session.query(Investigation.statut).filter(
        Investigation.id == investigation_id
    ).scalar()
    annulee = statut == StatutInvestigation.ANNULEE.value
    if annulee and dans_cache is False:
        # Le cache avait expiré alors que l'annulation tient toujours : on le
        # réamorce pour que la surveillance de Maigret la voie sans session.
        marquer_annulation(investigation_id)
    return annulee


class InvestigationAnnulee(Exception):
    """Levée par une tâche qui constate que l'investigation a été arrêtée."""


def interrompre_si_annulee(investigation_id: str, session=None) -> None:
    """Point de reprise : lève `InvestigationAnnulee` si l'arrêt a été demandé."""
    if est_annulee(investigation_id, session):
        raise InvestigationAnnulee(investigation_id)
