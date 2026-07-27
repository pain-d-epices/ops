"""Utilisateurs et jetons de rafraîchissement."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, HorodatageMixin, nouvel_id

if TYPE_CHECKING:
    from app.modeles.organisation import Appartenance


class Utilisateur(Base, HorodatageMixin):
    __tablename__ = "utilisateurs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    mot_de_passe_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nom_complet: Mapped[str | None] = mapped_column(String(150))

    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verifie: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Acceptation des conditions d'utilisation : obligatoire avant toute recherche.
    # On conserve la date ET la version acceptée, pour prouver le consentement au cadre légal.
    cgu_acceptees_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cgu_version_acceptee: Mapped[str | None] = mapped_column(String(20))

    # Champ prévu dès maintenant pour la 2FA (TOTP) livrée en v2 : évite une migration plus tard
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_actif: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    derniere_connexion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tentatives_echouees: Mapped[int] = mapped_column(default=0, nullable=False)
    bloque_jusqua: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    appartenances: Mapped[list["Appartenance"]] = relationship(
        back_populates="utilisateur", cascade="all, delete-orphan"
    )
    jetons: Mapped[list["JetonRafraichissement"]] = relationship(
        back_populates="utilisateur", cascade="all, delete-orphan"
    )

    @property
    def a_accepte_cgu(self) -> bool:
        return self.cgu_acceptees_le is not None

    def __repr__(self) -> str:
        return f"<Utilisateur {self.email}>"


class JetonRafraichissement(Base):
    """Jeton de rafraîchissement stocké en base (haché) pour permettre la révocation.

    Un JWT seul ne peut pas être révoqué avant son expiration ; conserver le jeton de
    rafraîchissement en base permet de déconnecter réellement une session compromise.
    """

    __tablename__ = "jetons_rafraichissement"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    utilisateur_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("utilisateurs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jeton_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoque: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_creation: Mapped[str | None] = mapped_column(String(45))
    agent_utilisateur: Mapped[str | None] = mapped_column(String(300))

    utilisateur: Mapped[Utilisateur] = relationship(back_populates="jetons")
