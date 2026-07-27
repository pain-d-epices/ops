"""Schémas de la page « Abonnement »."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlanSortie(BaseModel):
    code: str
    nom_affiche: str
    description: str | None
    prix_mensuel_cents: int
    ordre: int
    quota_recherches_mois: int
    quota_enrichissements_mois: int
    quota_utilisateurs: int
    quota_investigations_actives: int
    profondeur_pivot_max: int
    fonctionnalites: list[str]
    # Adresse d'achat Gumroad, construite à partir de l'identifiant produit configuré
    url_achat: str | None = None
    est_plan_actuel: bool = False


class QuotaSortie(BaseModel):
    nom: str
    consomme: int
    limite: int | None      # None = illimité
    restant: int | None
    pourcentage: float


class AbonnementSortie(BaseModel):
    plan: PlanSortie
    statut: str
    periode_debut: datetime | None
    periode_fin: datetime | None
    renouvellement_automatique: bool
    licence_active: bool
    quotas: list[QuotaSortie]
    # Message d'incitation affiché quand un quota est proche de la limite
    message_limite: str | None = None
    plan_superieur: PlanSortie | None = None


class DemandeActivationLicence(BaseModel):
    """Activation manuelle d'une clé de licence Gumroad.

    Voie de secours indispensable : les webhooks Gumroad ne sont pas réémis en cas
    d'échec, et un client achète souvent avant même d'avoir créé son compte.
    """

    cle_licence: str = Field(min_length=8, max_length=100)
    code_plan: str | None = None   # facultatif : déduit du produit si absent
