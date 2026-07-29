"""Modèles SQLAlchemy.

Toutes les classes sont importées ici pour qu'Alembic les découvre automatiquement
lors de la génération des migrations (`alembic revision --autogenerate`).
"""

from app.db.base import Base
from app.modeles.facturation import Abonnement, CompteurUsage, EvenementGumroad, Plan
from app.modeles.graphe import AreteGraphe, NoeudGraphe
from app.modeles.investigation import (
    DonneeExtraite,
    ExecutionRecherche,
    Investigation,
    PointDepart,
    ProfilIdentite,
    PropositionPivot,
    SignalCorrelation,
)
from app.modeles.journal import EntreeJournal
from app.modeles.organisation import Appartenance, Invitation, Organisation
from app.modeles.utilisateur import JetonRafraichissement, Utilisateur

__all__ = [
    "Base",
    "Abonnement",
    "Appartenance",
    "AreteGraphe",
    "CompteurUsage",
    "DonneeExtraite",
    "EntreeJournal",
    "EvenementGumroad",
    "ExecutionRecherche",
    "Investigation",
    "Invitation",
    "JetonRafraichissement",
    "NoeudGraphe",
    "Organisation",
    "Plan",
    "PointDepart",
    "ProfilIdentite",
    "PropositionPivot",
    "SignalCorrelation",
    "Utilisateur",
]
