"""Modèles de facturation : plans, abonnements Gumroad, compteurs d'usage.

Volontairement découplés du reste du code métier : ajuster un palier consiste à
modifier une ligne de la table `plans`, jamais à toucher à la logique applicative.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, HorodatageMixin, nouvel_id

if TYPE_CHECKING:
    from app.modeles.organisation import Organisation

TypeJson = JSON().with_variant(JSONB(), "postgresql")


class Plan(Base, HorodatageMixin):
    """Un palier d'abonnement : quotas et fonctionnalités activées."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)   # free, starter, pro, entreprise
    nom_affiche: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    prix_mensuel_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ordre: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # pour l'affichage et l'upsell

    # --- Quotas ---
    quota_recherches_mois: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    quota_enrichissements_mois: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quota_utilisateurs: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    quota_investigations_actives: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    profondeur_pivot_max: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- Fonctionnalités activées ---
    # Liste de codes : ["modules", "pivot", "pivot_automatique", "export_pdf", "api", "retention_etendue"]
    fonctionnalites: Mapped[list[str]] = mapped_column(TypeJson, default=list, nullable=False)

    # Identifiant du produit Gumroad correspondant (null pour le palier gratuit)
    gumroad_product_id: Mapped[str | None] = mapped_column(String(100))

    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    abonnements: Mapped[list["Abonnement"]] = relationship(back_populates="plan")

    def possede(self, fonctionnalite: str) -> bool:
        return fonctionnalite in (self.fonctionnalites or [])

    def __repr__(self) -> str:
        return f"<Plan {self.code}>"


class Abonnement(Base, HorodatageMixin):
    """Lien entre une organisation et son plan actif.

    Une organisation possède exactement un abonnement actif à un instant donné ;
    l'historique est conservé (les anciens passent en statut expiré/annulé).
    """

    __tablename__ = "abonnements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    organisation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("plans.id"), nullable=False)

    statut: Mapped[str] = mapped_column(String(20), default="actif", nullable=False, index=True)
    periode_debut: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    periode_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renouvellement_automatique: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Rattachement Gumroad ---
    # Gumroad est "merchant of record" : il encaisse et gère la TVA. Le lien avec une
    # organisation se fait par clé de licence, vérifiable à tout moment via son API.
    gumroad_license_key: Mapped[str | None] = mapped_column(String(100), index=True)
    gumroad_product_id: Mapped[str | None] = mapped_column(String(100))
    gumroad_sale_id: Mapped[str | None] = mapped_column(String(100))
    gumroad_email_acheteur: Mapped[str | None] = mapped_column(String(255))
    derniere_verification: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organisation: Mapped["Organisation"] = relationship(back_populates="abonnements")
    plan: Mapped[Plan] = relationship(back_populates="abonnements")

    def __repr__(self) -> str:
        return f"<Abonnement org={self.organisation_id} statut={self.statut}>"


class CompteurUsage(Base, HorodatageMixin):
    """Consommation mensuelle d'une organisation.

    Une ligne par organisation et par période (format "AAAA-MM"). L'incrémentation
    passe par un UPSERT atomique afin qu'un client ne puisse pas dépasser son quota
    en lançant plusieurs recherches simultanément.
    """

    __tablename__ = "compteurs_usage"
    __table_args__ = (UniqueConstraint("organisation_id", "periode", name="uq_compteur_org_periode"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    organisation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    periode: Mapped[str] = mapped_column(String(7), nullable=False)  # "2026-07"

    compteur_recherches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compteur_enrichissements: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compteur_pivots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compteur_exports: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    detail: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)

    def __repr__(self) -> str:
        return f"<CompteurUsage {self.organisation_id} {self.periode}>"


class EvenementGumroad(Base):
    """Journal brut des webhooks Gumroad reçus.

    Conservé tel quel : indispensable pour rejouer un événement mal traité et pour
    prouver l'historique d'un abonnement en cas de litige avec un client.
    """

    __tablename__ = "evenements_gumroad"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    type_evenement: Mapped[str] = mapped_column(String(50), nullable=False)   # sale, refund, cancellation...
    gumroad_sale_id: Mapped[str | None] = mapped_column(String(100), index=True)
    gumroad_license_key: Mapped[str | None] = mapped_column(String(100), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    charge_utile: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)
    traite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    erreur_traitement: Mapped[str | None] = mapped_column(String(1000))
    recu_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
