"""Client Redis partagé, tolérant à l'absence de Redis.

Redis sert ici à trois choses : la file de tâches Celery, la limitation de débit et la
mémoire des épreuves anti-robot déjà consommées. Les deux dernières sont sur le chemin
critique de requêtes HTTP — inscription, connexion, création d'investigation.

D'où ce module, qui règle trois problèmes mesurés :

1. **Une connexion refusée n'est pas instantanée.** Sur Windows, un port fermé en
   loopback met environ 2 secondes à répondre « refusé » (4 secondes via
   « localhost », qui tente d'abord IPv6). Ouvrir un client à chaque appel ferait donc
   payer ce délai à chaque requête dès que Redis tombe.
2. **redis-py réessaie par défaut.** En version 8, une connexion impossible est
   retentée plusieurs fois avec temporisation. Sur un chemin critique, mieux vaut
   échouer vite et se replier.
3. **Ne jamais retenter est une autre erreur.** Si l'on mémorise l'échec pour toujours,
   Redis revenu ne serait plus utilisé jusqu'au redémarrage du processus. L'échec est
   donc mémorisé pour une durée courte, puis une nouvelle tentative est faite.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.config import parametres

journal = logging.getLogger(__name__)

#: Délai avant de retenter une connexion après un échec. Assez long pour ne pas payer
#: le coût d'une connexion refusée à chaque requête, assez court pour que le retour de
#: Redis soit pris en compte sans redémarrage.
DELAI_NOUVELLE_TENTATIVE = 30.0

#: Délais de connexion et de lecture. Volontairement courts : ce client n'est utilisé
#: que pour de petites opérations, et un blocage ici bloque une requête HTTP.
TIMEOUT_CONNEXION = 1.0
TIMEOUT_LECTURE = 2.0

_client: Any = None
_dernier_echec: float = 0.0
_verrou = threading.Lock()
_echec_signale = False


def client_redis() -> Any | None:
    """Client Redis prêt à l'emploi, ou None s'il est injoignable.

    Ne lève jamais : l'appelant est censé se replier sur un fonctionnement dégradé.
    """
    global _client, _dernier_echec, _echec_signale

    with _verrou:
        if _client is not None:
            return _client
        if time.monotonic() - _dernier_echec < DELAI_NOUVELLE_TENTATIVE:
            return None

        try:
            import redis
            from redis.backoff import NoBackoff
            from redis.retry import Retry

            client = redis.Redis.from_url(
                parametres().redis_url,
                socket_timeout=TIMEOUT_LECTURE,
                socket_connect_timeout=TIMEOUT_CONNEXION,
                # Aucun réessai : sur un chemin critique, un repli immédiat vaut mieux
                # qu'une attente multipliée.
                retry=Retry(NoBackoff(), 0),
                retry_on_timeout=False,
            )
            client.ping()
        except Exception as exc:  # noqa: BLE001
            _dernier_echec = time.monotonic()
            if not _echec_signale:
                journal.warning(
                    "Redis injoignable (%s) : limitation de débit et mémoire des "
                    "épreuves anti-robot en mode dégradé (portée limitée au processus). "
                    "Nouvelle tentative dans %.0f s.",
                    exc, DELAI_NOUVELLE_TENTATIVE,
                )
                _echec_signale = True
            return None

        journal.info("Connexion à Redis établie.")
        _client = client
        _echec_signale = False
        return _client


def signaler_panne() -> None:
    """À appeler quand une commande échoue sur un client pourtant obtenu.

    Redis a pu tomber entre-temps : on jette le client afin que le prochain appel
    reparte proprement, sans réessayer immédiatement.
    """
    global _client, _dernier_echec
    with _verrou:
        _client = None
        _dernier_echec = time.monotonic()


def reinitialiser_client_redis() -> None:
    """Oublie le client et l'historique d'échec. Réservé aux tests."""
    global _client, _dernier_echec, _echec_signale
    with _verrou:
        _client = None
        _dernier_echec = 0.0
        _echec_signale = False
