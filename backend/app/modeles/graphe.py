"""Graphe de relations, stocké en PostgreSQL sous forme de nœuds et d'arêtes.

L'accès passe systématiquement par `app.moteur.graphe.depot.DepotGraphe`, seule
couche qui connaît ces tables. Une éventuelle migration vers une base graphe
dédiée (Neo4j) ne toucherait donc que ce dépôt, pas le code métier.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, HorodatageMixin, nouvel_id

TypeJson = JSON().with_variant(JSONB(), "postgresql")


class NoeudGraphe(Base, HorodatageMixin):
    __tablename__ = "noeuds_graphe"
    __table_args__ = (
        # Deux profils qui mènent au même email ne créent qu'un seul nœud : c'est ce
        # rapprochement qui fait apparaître visuellement les liens entre comptes.
        UniqueConstraint("investigation_id", "type", "cle_unicite", name="uq_noeud_investigation"),
        Index("ix_noeuds_org_investigation", "organisation_id", "investigation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    type: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(String(300), nullable=False)
    cle_unicite: Mapped[str] = mapped_column(String(500), nullable=False)  # libellé normalisé

    # Référence vers le profil correspondant, pour les nœuds de type "compte"
    profil_id: Mapped[str | None] = mapped_column(String(36), index=True)

    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # pilote couleur et taille à l'affichage
    profondeur: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)

    def __repr__(self) -> str:
        return f"<NoeudGraphe {self.type}:{self.libelle[:30]}>"


class AreteGraphe(Base, HorodatageMixin):
    __tablename__ = "aretes_graphe"
    __table_args__ = (
        UniqueConstraint("investigation_id", "source_id", "cible_id", "type", name="uq_arete_investigation"),
        Index("ix_aretes_org_investigation", "organisation_id", "investigation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("noeuds_graphe.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cible_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("noeuds_graphe.id", ondelete="CASCADE"), nullable=False, index=True
    )

    type: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str | None] = mapped_column(String(300))   # "email trouvé dans la bio"
    poids: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)

    def __repr__(self) -> str:
        return f"<AreteGraphe {self.source_id} -{self.type}-> {self.cible_id}>"
