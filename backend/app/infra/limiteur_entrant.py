"""Limitation du débit des requêtes **entrantes**, par adresse IP.

À ne pas confondre avec [`limiteur.py`](limiteur.py), qui fait l'inverse : celui-ci
protège Searcher de ses propres utilisateurs, l'autre protège les sites interrogés de
Searcher (pour ne pas faire bannir l'adresse IP du service).

Deux mécanismes complémentaires :

- **Seau à jetons** — lisse le débit. Autorise une rafale courte puis impose un
  rythme. C'est ce qu'il faut pour la connexion ou la création d'investigation, où un
  usage normal peut être irrégulier.
- **Compteur à fenêtre fixe** — plafond dur sur une période. C'est ce qu'il faut pour
  « pas plus de N comptes créés par jour et par IP » : un seau à jetons se recharge,
  donc n'impose aucun plafond absolu.

Le script Lua du seau est réutilisé depuis `limiteur.py` : l'algorithme est le même,
seules les clés et les valeurs de réglage diffèrent.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.config import config_metier
from app.infra.limiteur import SCRIPT_SEAU
from app.infra.redis_client import client_redis, signaler_panne

journal = logging.getLogger(__name__)

# Incrémente un compteur et pose son expiration au premier passage seulement : la
# fenêtre part de la première requête et ne se prolonge pas à chaque appel suivant.
SCRIPT_COMPTEUR = """
local cle = KEYS[1]
local fenetre = tonumber(ARGV[1])
local valeur = redis.call('INCR', cle)
if valeur == 1 then
  redis.call('EXPIRE', cle, fenetre)
end
return valeur
"""


@dataclass
class ReglageEntrant:
    requetes_par_minute: int
    rafale: int

    @property
    def debit_par_seconde(self) -> float:
        return max(0.001, self.requetes_par_minute / 60.0)


#: Réglages de repli, appliqués si `config.yaml` ne dit rien. Volontairement stricts :
#: une configuration absente ne doit pas se traduire par une absence de protection.
REGLAGES_DEFAUT: dict[str, ReglageEntrant] = {
    "inscription": ReglageEntrant(requetes_par_minute=3, rafale=3),
    "connexion": ReglageEntrant(requetes_par_minute=10, rafale=10),
    "investigation": ReglageEntrant(requetes_par_minute=20, rafale=10),
    "defi": ReglageEntrant(requetes_par_minute=30, rafale=15),
}


def reglage_pour(action: str) -> ReglageEntrant:
    conf = config_metier().section("anti_abus")
    valeurs = (conf.get("debit", {}) or {}).get(action) or {}
    defaut = REGLAGES_DEFAUT.get(action, ReglageEntrant(30, 15))
    return ReglageEntrant(
        requetes_par_minute=int(valeurs.get("requetes_par_minute", defaut.requetes_par_minute)),
        rafale=int(valeurs.get("rafale", defaut.rafale)),
    )


def adresse_client(requete: Request) -> str:
    """Adresse IP de l'appelant.

    `X-Forwarded-For` n'est lu **que** si un proxy de confiance est déclaré dans la
    configuration. Le lire systématiquement serait une faille : l'en-tête est fourni
    par le client, donc un attaquant le changerait à chaque requête et contournerait
    toute limitation par IP.
    """
    conf = config_metier().section("anti_abus")
    if conf.get("derriere_un_proxy_de_confiance", False):
        transmise = requete.headers.get("x-forwarded-for", "")
        # Le premier élément est l'adresse d'origine, les suivants sont les relais.
        premiere = transmise.split(",")[0].strip()
        if premiere:
            return premiere
    return requete.client.host if requete.client else "inconnue"


class LimiteurEntrant:
    """Limiteur par IP adossé à Redis, avec repli mémoire si Redis manque."""

    def __init__(self) -> None:
        self._seau = None
        self._compteur = None
        self._client_prepare = None
        self._seaux_memoire: dict[str, tuple[float, float]] = {}
        self._compteurs_memoire: dict[str, tuple[int, float]] = {}
        self._verrou = threading.Lock()

    def _obtenir_client(self):
        """Client Redis avec ses scripts enregistrés, ou None.

        La disponibilité de Redis et le coût d'une connexion refusée sont gérés par
        `infra/redis_client` : ici on ne fait que (ré)enregistrer les scripts quand le
        client change.
        """
        client = client_redis()
        if client is None:
            return None
        if client is not self._client_prepare:
            try:
                self._seau = client.register_script(SCRIPT_SEAU)
                self._compteur = client.register_script(SCRIPT_COMPTEUR)
                self._client_prepare = client
            except Exception as exc:  # noqa: BLE001
                journal.warning("Enregistrement des scripts Redis en échec (%s)", exc)
                signaler_panne()
                return None
        return client

    # --- Seau à jetons ------------------------------------------------------

    def attente_requise(self, action: str, ip: str) -> float:
        """Secondes à attendre avant que cette IP puisse refaire cette action."""
        reglage = reglage_pour(action)
        client = self._obtenir_client()
        cle = f"entrant:{action}:{ip}"

        if client is not None and self._seau is not None:
            try:
                return max(0.0, float(self._seau(
                    keys=[cle],
                    args=[reglage.debit_par_seconde, reglage.rafale, time.time(), 1],
                )))
            except Exception as exc:  # noqa: BLE001
                journal.warning("Limitation par IP via Redis en échec (%s) : repli mémoire", exc)
                signaler_panne()

        maintenant = time.monotonic()
        with self._verrou:
            jetons, dernier = self._seaux_memoire.get(cle, (float(reglage.rafale), maintenant))
            jetons = min(reglage.rafale, jetons + (maintenant - dernier) * reglage.debit_par_seconde)
            if jetons >= 1:
                self._seaux_memoire[cle] = (jetons - 1, maintenant)
                return 0.0
            self._seaux_memoire[cle] = (jetons, maintenant)
            return (1 - jetons) / reglage.debit_par_seconde

    # --- Compteur à fenêtre fixe -------------------------------------------

    def compter(self, action: str, ip: str, fenetre_secondes: int) -> int:
        """Incrémente le compteur de cette IP pour cette action et rend son total."""
        client = self._obtenir_client()
        cle = f"entrant:cpt:{action}:{ip}"

        if client is not None and self._compteur is not None:
            try:
                return int(self._compteur(keys=[cle], args=[fenetre_secondes]))
            except Exception as exc:  # noqa: BLE001
                journal.warning("Comptage par IP via Redis en échec (%s) : repli mémoire", exc)
                signaler_panne()

        maintenant = time.monotonic()
        with self._verrou:
            valeur, debut = self._compteurs_memoire.get(cle, (0, maintenant))
            if maintenant - debut >= fenetre_secondes:
                valeur, debut = 0, maintenant
            valeur += 1
            self._compteurs_memoire[cle] = (valeur, debut)
            return valeur


_limiteur_entrant: LimiteurEntrant | None = None


def limiteur_entrant() -> LimiteurEntrant:
    global _limiteur_entrant
    if _limiteur_entrant is None:
        _limiteur_entrant = LimiteurEntrant()
    return _limiteur_entrant


def reinitialiser_limiteur_entrant() -> None:
    """Remet le limiteur à zéro. Réservé aux tests, qui enchaînent les inscriptions."""
    global _limiteur_entrant
    _limiteur_entrant = None


def exiger_debit(action: str):
    """Dépendance FastAPI : refuse la requête si l'IP dépasse le débit autorisé.

    Le message reste vague sur le mécanisme, mais donne le délai : un utilisateur
    légitime doit comprendre qu'il suffit d'attendre, sans qu'un attaquant apprenne
    les réglages exacts.
    """

    def verifier(requete: Request) -> None:
        if not config_metier().obtenir("anti_abus.actif", True):
            return
        ip = adresse_client(requete)
        attente = limiteur_entrant().attente_requise(action, ip)
        if attente > 0:
            secondes = max(1, round(attente))
            journal.info("Débit dépassé pour %s depuis %s (%.1fs)", action, ip, attente)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Trop de requêtes. Réessayez dans {secondes} seconde"
                f"{'s' if secondes > 1 else ''}.",
                headers={"Retry-After": str(secondes)},
            )

    return verifier
