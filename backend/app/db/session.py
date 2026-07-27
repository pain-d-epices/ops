"""Gestion des sessions de base de données.

Choix d'architecture : SQLAlchemy **synchrone** partout.
Les tâches Celery sont synchrones par nature ; utiliser le mode asynchrone uniquement
côté API imposerait de maintenir deux couches d'accès aux données en parallèle.
FastAPI exécute les endpoints déclarés en `def` (et non `async def`) dans un pool de
threads, ce qui rend ce choix parfaitement viable et nettement plus simple à opérer.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import parametres

_params = parametres()

moteur = create_engine(
    _params.dsn,
    pool_pre_ping=True,      # vérifie la connexion avant usage (évite les erreurs après coupure réseau)
    pool_size=10,
    max_overflow=20,
    echo=False,
    future=True,
)

FabriqueSession = sessionmaker(bind=moteur, autoflush=False, expire_on_commit=False, class_=Session)


def obtenir_session() -> Iterator[Session]:
    """Dépendance FastAPI : fournit une session et la ferme à la fin de la requête."""
    session = FabriqueSession()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def portee_session() -> Iterator[Session]:
    """Contexte transactionnel pour les tâches Celery et les scripts.

    Valide la transaction en sortie normale, annule tout en cas d'exception.
    """
    session = FabriqueSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
