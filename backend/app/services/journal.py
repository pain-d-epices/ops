"""Écriture du journal d'accès.

Chaque recherche lancée est tracée avec son auteur, son organisation et sa cible.
C'est une obligation pratique pour un service commercial traitant des données de
tiers : sans ce journal, impossible de démontrer qui a fait quoi en cas de contrôle
RGPD ou d'usage abusif par un client.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.base import maintenant
from app.modeles.enums import ActionJournal
from app.modeles.journal import EntreeJournal


def _tronquer(valeur: str | None, taille: int) -> str | None:
    if valeur is None:
        return None
    return valeur[:taille]


def journaliser(
    session: Session,
    action: ActionJournal | str,
    *,
    organisation_id: str | None = None,
    utilisateur_id: str | None = None,
    email_utilisateur: str | None = None,
    cible: str | None = None,
    investigation_id: str | None = None,
    requete: Request | None = None,
    detail: dict[str, Any] | None = None,
    resultat: str | None = None,
) -> EntreeJournal:
    """Ajoute une entrée au journal. N'effectue pas de commit : suit la transaction appelante."""
    ip = None
    agent = None
    if requete is not None:
        # X-Forwarded-For est renseigné par le reverse proxy (Caddy/Nginx) en production
        entete_relais = requete.headers.get("x-forwarded-for")
        if entete_relais:
            ip = entete_relais.split(",")[0].strip()
        elif requete.client:
            ip = requete.client.host
        agent = requete.headers.get("user-agent")

    entree = EntreeJournal(
        horodatage=maintenant(),
        organisation_id=organisation_id,
        utilisateur_id=utilisateur_id,
        email_utilisateur=_tronquer(email_utilisateur, 255),
        action=action.value if isinstance(action, ActionJournal) else action,
        cible=_tronquer(cible, 500),
        investigation_id=investigation_id,
        ip=_tronquer(ip, 45),
        agent_utilisateur=_tronquer(agent, 300),
        detail=detail or {},
        resultat=resultat,
    )
    session.add(entree)
    return entree
