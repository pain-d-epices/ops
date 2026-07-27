"""WebSocket de suivi temps réel d'une investigation.

Le navigateur ouvre une connexion par investigation ; l'API s'abonne au canal Redis
correspondant et relaie les événements publiés par les workers.

Deux contrôles à l'ouverture, avant tout abonnement :
  - le jeton d'accès doit être valide ;
  - l'investigation doit appartenir à une organisation dont l'utilisateur est membre.
Sans ces vérifications, il suffirait de connaître un identifiant d'investigation pour
observer en direct le travail d'un autre client.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import parametres
from app.db.session import FabriqueSession
from app.infra.evenements import canal
from app.modeles.investigation import Investigation
from app.modeles.organisation import Appartenance
from app.securite.dependances import NOM_COOKIE_ACCES
from app.securite.jetons import JetonInvalide, decoder_jeton_acces

journal = logging.getLogger(__name__)
routeur = APIRouter(tags=["Temps réel"])

CODE_NON_AUTORISE = 4401
CODE_INTROUVABLE = 4404
CODE_INDISPONIBLE = 4503


def _autoriser(jeton: str, investigation_id: str) -> tuple[bool, int, str]:
    """Vérifie le jeton et l'appartenance. Renvoie (autorisé, code de fermeture, motif)."""
    try:
        contenu = decoder_jeton_acces(jeton)
    except JetonInvalide as exc:
        return False, CODE_NON_AUTORISE, str(exc)

    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            return False, CODE_INTROUVABLE, "Investigation introuvable."

        appartenance = session.scalar(
            select(Appartenance).where(
                Appartenance.utilisateur_id == contenu.utilisateur_id,
                Appartenance.organisation_id == investigation.organisation_id,
            )
        )
        if appartenance is None:
            # Même réponse que pour une investigation inexistante : ne pas révéler
            # qu'un identifiant valide existe chez un autre client.
            return False, CODE_INTROUVABLE, "Investigation introuvable."
        return True, 0, ""
    finally:
        session.close()


@routeur.websocket("/ws/investigations/{investigation_id}")
async def suivre_investigation(
    websocket: WebSocket,
    investigation_id: str,
    jeton: str | None = Query(default=None),
) -> None:
    # Le cookie httpOnly est la voie normale ; le paramètre `jeton` sert aux clients
    # qui ne peuvent pas transmettre de cookies (outils tiers, tests).
    jeton_effectif = websocket.cookies.get(NOM_COOKIE_ACCES) or jeton
    if not jeton_effectif:
        await websocket.close(code=CODE_NON_AUTORISE, reason="Authentification requise.")
        return

    autorise, code, motif = _autoriser(jeton_effectif, investigation_id)
    if not autorise:
        await websocket.close(code=code, reason=motif)
        return

    await websocket.accept()

    try:
        import redis.asyncio as redis_async
    except ImportError:
        await websocket.close(code=CODE_INDISPONIBLE, reason="Suivi temps réel indisponible.")
        return

    client = redis_async.Redis.from_url(parametres().redis_url)
    abonnement = client.pubsub()

    try:
        await abonnement.subscribe(canal(investigation_id))
        await websocket.send_json({"type": "connecte", "investigation_id": investigation_id})

        while True:
            message = await abonnement.get_message(ignore_subscribe_messages=True, timeout=30.0)
            if message is None:
                # Ping périodique : maintient la connexion ouverte à travers les
                # proxys qui coupent les connexions inactives.
                await websocket.send_json({"type": "ping"})
                continue

            donnees = message.get("data")
            if isinstance(donnees, bytes):
                donnees = donnees.decode("utf-8", errors="replace")
            await websocket.send_text(str(donnees))

    except WebSocketDisconnect:
        journal.debug("Client déconnecté du suivi de l'investigation %s", investigation_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        journal.exception("Erreur sur le canal temps réel de l'investigation %s", investigation_id)
    finally:
        try:
            await abonnement.unsubscribe(canal(investigation_id))
            await abonnement.close()
            await client.aclose()
        except Exception:  # noqa: BLE001
            journal.debug("Fermeture du canal Redis imparfaite", exc_info=True)
