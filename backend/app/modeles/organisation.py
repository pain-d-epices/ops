"""Organisations (locataires), appartenances et invitations.

L'organisation est l'unité d'isolation du SaaS : toute donnée d'investigation lui
est rattachée et aucune requête ne doit y accéder sans filtrer sur `organisation_id`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, HorodatageMixin, nouvel_id
from app.modeles.enums import ModePivot, RoleMembre, StatutOrganisation

if TYPE_CHECKING:
    from app.modeles.facturation import Abonnement
    from app.modeles.utilisateur import Utilisateur


class Organisation(Base, HorodatageMixin):
    __tablename__ = "organisations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    nom: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    statut: Mapped[str] = mapped_column(String(20), default=StatutOrganisation.ACTIVE.value, nullable=False)

    # --- Préférences propres à l'organisation ---
    # Le mode de pivot est un paramètre par organisation, pas une constante globale.
    # Il reste borné par les fonctionnalités du plan actif (voir facturation/garde.py).
    mode_pivot: Mapped[str] = mapped_column(String(20), default=ModePivot.SUPERVISE.value, nullable=False)
    profondeur_pivot_souhaitee: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Durée de rétention RGPD des investigations, en jours (0 = valeur par défaut du serveur)
    retention_jours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    membres: Mapped[list["Appartenance"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )
    abonnements: Mapped[list["Abonnement"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )
    invitations: Mapped[list["Invitation"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Organisation {self.slug}>"


class Appartenance(Base, HorodatageMixin):
    """Rattachement d'un utilisateur à une organisation, avec son rôle.

    Un utilisateur peut appartenir à plusieurs organisations (cas d'un consultant
    travaillant pour plusieurs clients) ; le rôle est propre à chaque rattachement.
    """

    __tablename__ = "appartenances"
    __table_args__ = (UniqueConstraint("utilisateur_id", "organisation_id", name="uq_appartenance"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    utilisateur_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("utilisateurs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default=RoleMembre.ANALYSTE.value, nullable=False)

    utilisateur: Mapped["Utilisateur"] = relationship(back_populates="appartenances")
    organisation: Mapped[Organisation] = relationship(back_populates="membres")

    def __repr__(self) -> str:
        return f"<Appartenance {self.utilisateur_id}@{self.organisation_id} ({self.role})>"


class Invitation(Base, HorodatageMixin):
    """Invitation d'un nouvel utilisateur à rejoindre une organisation."""

    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    organisation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), default=RoleMembre.ANALYSTE.value, nullable=False)
    jeton: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    invite_par: Mapped[str | None] = mapped_column(String(36), ForeignKey("utilisateurs.id"))
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acceptee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoquee: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    organisation: Mapped[Organisation] = relationship(back_populates="invitations")

    def __repr__(self) -> str:
        return f"<Invitation {self.email} -> {self.organisation_id}>"
