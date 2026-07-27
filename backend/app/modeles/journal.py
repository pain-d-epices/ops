"""Journal d'accès : qui a lancé quelle recherche, sur quelle cible, et quand.

Table volontairement en écriture seule (jamais de mise à jour ni de suppression hors
purge planifiée). C'est la pièce à fournir en cas de contrôle RGPD ou de litige sur
l'usage abusif du service par un client.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, nouvel_id

TypeJson = JSON().with_variant(JSONB(), "postgresql")


class EntreeJournal(Base):
    __tablename__ = "journal_acces"
    __table_args__ = (
        Index("ix_journal_org_date", "organisation_id", "horodatage"),
        Index("ix_journal_action_date", "action", "horodatage"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    organisation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    utilisateur_id: Mapped[str | None] = mapped_column(String(36), index=True)
    email_utilisateur: Mapped[str | None] = mapped_column(String(255))  # conservé même si le compte est supprimé

    action: Mapped[str] = mapped_column(String(60), nullable=False)
    # Sujet de l'action : le pseudonyme recherché, l'identifiant d'investigation, l'email invité...
    cible: Mapped[str | None] = mapped_column(String(500))
    investigation_id: Mapped[str | None] = mapped_column(String(36), index=True)

    ip: Mapped[str | None] = mapped_column(String(45))
    agent_utilisateur: Mapped[str | None] = mapped_column(String(300))
    detail: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)
    resultat: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<EntreeJournal {self.action} {self.cible}>"
