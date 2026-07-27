"""File d'attente globale par site cible (limitation de débit).

Point essentiel pour un service multi-clients : la limite est **globale par domaine**,
partagée entre toutes les organisations. Si trois clients interrogent GitHub en même
temps, ils se partagent le même budget de requêtes. Sans cela, la montée en charge
commerciale entraînerait le bannissement de l'adresse IP du service — donc une panne
pour tous les clients à la fois.

Algorithme : seau à jetons (token bucket) dans Redis, mis à jour par un script Lua
pour que l'opération reste atomique entre plusieurs workers.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from app.config import config_metier, parametres

journal = logging.getLogger(__name__)

# Le script s'exécute côté Redis : lecture, recharge et consommation forment une
# seule opération indivisible, même avec plusieurs workers concurrents.
SCRIPT_SEAU = """
local cle = KEYS[1]
local debit = tonumber(ARGV[1])       -- jetons rechargés par seconde
local capacite = tonumber(ARGV[2])    -- taille du seau (rafale autorisée)
local maintenant = tonumber(ARGV[3])
local cout = tonumber(ARGV[4])

local donnees = redis.call('HMGET', cle, 'jetons', 'horodatage')
local jetons = tonumber(donnees[1])
local dernier = tonumber(donnees[2])

if jetons == nil then
  jetons = capacite
  dernier = maintenant
end

local ecoule = math.max(0, maintenant - dernier)
jetons = math.min(capacite, jetons + ecoule * debit)

local attente = 0
if jetons >= cout then
  jetons = jetons - cout
else
  attente = (cout - jetons) / debit
end

redis.call('HMSET', cle, 'jetons', jetons, 'horodatage', maintenant)
redis.call('EXPIRE', cle, 3600)
return tostring(attente)
"""


@dataclass
class ReglageDebit:
    requetes_par_minute: int
    rafale: int

    @property
    def debit_par_seconde(self) -> float:
        return max(0.001, self.requetes_par_minute / 60.0)


def reglage_pour(domaine: str) -> ReglageDebit:
    """Réglage propre au domaine, sinon réglage par défaut (config.yaml)."""
    conf = config_metier().section("rate_limiting")
    par_domaine = conf.get("par_domaine", {}) or {}
    defaut = conf.get("defaut", {}) or {}
    valeurs = par_domaine.get(domaine.lower(), defaut)
    return ReglageDebit(
        requetes_par_minute=int(valeurs.get("requetes_par_minute", defaut.get("requetes_par_minute", 30))),
        rafale=int(valeurs.get("rafale", defaut.get("rafale", 10))),
    )


class LimiteurMemoire:
    """Repli utilisé quand Redis est indisponible (développement local, tests).

    Ne coordonne qu'un seul processus : suffisant en développement, insuffisant en
    production où plusieurs workers tournent en parallèle.
    """

    def __init__(self) -> None:
        self._seaux: dict[str, tuple[float, float]] = {}
        self._verrou = threading.Lock()

    def attente_requise(self, domaine: str, cout: float = 1.0) -> float:
        reglage = reglage_pour(domaine)
        maintenant = time.monotonic()
        with self._verrou:
            jetons, dernier = self._seaux.get(domaine, (float(reglage.rafale), maintenant))
            jetons = min(reglage.rafale, jetons + (maintenant - dernier) * reglage.debit_par_seconde)
            if jetons >= cout:
                self._seaux[domaine] = (jetons - cout, maintenant)
                return 0.0
            attente = (cout - jetons) / reglage.debit_par_seconde
            self._seaux[domaine] = (jetons, maintenant)
            return attente


class LimiteurDebit:
    """Limiteur global partagé par tous les workers, adossé à Redis."""

    def __init__(self, url_redis: str | None = None):
        self._url = url_redis or parametres().redis_url
        self._client = None
        self._script = None
        self._repli = LimiteurMemoire()
        self._redis_indisponible_signale = False

    def _obtenir_client(self):
        if self._client is None:
            try:
                import redis

                self._client = redis.Redis.from_url(self._url, socket_timeout=2)
                self._client.ping()
                self._script = self._client.register_script(SCRIPT_SEAU)
            except Exception as exc:  # noqa: BLE001
                if not self._redis_indisponible_signale:
                    journal.warning(
                        "Redis indisponible (%s) : limitation de débit en mémoire, "
                        "non partagée entre workers.",
                        exc,
                    )
                    self._redis_indisponible_signale = True
                self._client = False  # marqueur « tentative effectuée, en échec »
        return self._client or None

    def attente_requise(self, domaine: str, cout: float = 1.0) -> float:
        """Durée d'attente, en secondes, avant de pouvoir émettre une requête."""
        domaine = (domaine or "inconnu").lower()
        client = self._obtenir_client()
        if client is None or self._script is None:
            return self._repli.attente_requise(domaine, cout)

        reglage = reglage_pour(domaine)
        try:
            resultat = self._script(
                keys=[f"debit:site:{domaine}"],
                args=[reglage.debit_par_seconde, reglage.rafale, time.time(), cout],
            )
            return max(0.0, float(resultat))
        except Exception as exc:  # noqa: BLE001
            journal.warning("Limitation de débit Redis en échec (%s) : repli mémoire", exc)
            return self._repli.attente_requise(domaine, cout)

    def attendre(self, domaine: str, cout: float = 1.0, attente_max: float = 60.0) -> bool:
        """Bloque jusqu'à obtention d'un jeton. Renvoie False si l'attente dépasse la limite.

        Le plafond d'attente évite qu'un worker reste bloqué indéfiniment sur un site
        saturé alors qu'il pourrait traiter d'autres profils.
        """
        total_attendu = 0.0
        while True:
            attente = self.attente_requise(domaine, cout)
            if attente <= 0:
                return True
            if total_attendu + attente > attente_max:
                journal.info("Attente trop longue pour %s (%.1fs) : requête abandonnée", domaine, attente)
                return False
            time.sleep(min(attente, 1.0))
            total_attendu += min(attente, 1.0)


_limiteur: LimiteurDebit | None = None


def limiteur() -> LimiteurDebit:
    global _limiteur
    if _limiteur is None:
        _limiteur = LimiteurDebit()
    return _limiteur


def definir_limiteur(nouveau: LimiteurDebit | None) -> None:
    global _limiteur
    _limiteur = nouveau
