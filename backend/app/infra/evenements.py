"""Bus d'événements temps réel entre les workers et les clients WebSocket.

Les tâches Celery s'exécutent dans des processus distincts de l'API : elles ne peuvent
pas écrire directement dans une connexion WebSocket. Elles publient donc leurs
événements dans Redis, et l'API les relaie aux navigateurs connectés.

Chaque événement porte l'`organisation_id` : c'est le contrôle qui empêche un client
de recevoir la progression d'une investigation appartenant à un autre.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from app.config import parametres
from app.db.base import maintenant

journal = logging.getLogger(__name__)


class TypeEvenement(str, Enum):
    PROGRESSION = "progression"
    ETAPE = "etape"
    PROFIL_TROUVE = "profil_trouve"
    PROFIL_MIS_A_JOUR = "profil_mis_a_jour"
    NOEUD_AJOUTE = "noeud_ajoute"
    PIVOT_PROPOSE = "pivot_propose"
    RECHERCHE_TERMINEE = "recherche_terminee"
    INVESTIGATION_TERMINEE = "investigation_terminee"
    ERREUR = "erreur"


@dataclass
class Evenement:
    type: TypeEvenement
    investigation_id: str
    organisation_id: str
    donnees: dict[str, Any] = field(default_factory=dict)
    horodatage: str = ""

    def __post_init__(self) -> None:
        if not self.horodatage:
            self.horodatage = maintenant().isoformat()

    def vers_json(self) -> str:
        contenu = asdict(self)
        contenu["type"] = self.type.value
        return json.dumps(contenu, ensure_ascii=False, default=str)


def canal(investigation_id: str) -> str:
    return f"investigation:{investigation_id}"


class BusEvenements:
    """Publication d'événements. Silencieux si Redis est absent (développement local)."""

    def __init__(self, url_redis: str | None = None):
        self._url = url_redis or parametres().redis_url
        self._client = None
        self._echec_signale = False

    def _obtenir_client(self):
        if self._client is None:
            try:
                import redis

                self._client = redis.Redis.from_url(self._url, socket_timeout=2)
                self._client.ping()
            except Exception as exc:  # noqa: BLE001
                if not self._echec_signale:
                    journal.warning("Redis indisponible (%s) : suivi temps réel désactivé.", exc)
                    self._echec_signale = True
                self._client = False
        return self._client or None

    def publier(self, evenement: Evenement) -> None:
        """Publie un événement. Un échec ne doit jamais interrompre l'investigation :
        perdre une mise à jour d'affichage est sans gravité, perdre la recherche non."""
        client = self._obtenir_client()
        if client is None:
            return
        try:
            client.publish(canal(evenement.investigation_id), evenement.vers_json())
        except Exception:  # noqa: BLE001
            journal.debug("Publication d'événement en échec", exc_info=True)

    def emettre(
        self,
        type_evenement: TypeEvenement,
        investigation_id: str,
        organisation_id: str,
        **donnees: Any,
    ) -> None:
        self.publier(
            Evenement(
                type=type_evenement,
                investigation_id=investigation_id,
                organisation_id=organisation_id,
                donnees=donnees,
            )
        )


_bus: BusEvenements | None = None


def bus() -> BusEvenements:
    global _bus
    if _bus is None:
        _bus = BusEvenements()
    return _bus
