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
    #: points de départ simultanés, pseudonyme compris ; 0 = illimité
    max_points_depart: int = 1
    fonctionnalites: list[str]
    est_plan_actuel: bool = False


class QuotaSortie(BaseModel):
    nom: str
    consomme: int
    limite: int | None      # None = illimité
    restant: int | None
    pourcentage: float


class AbonnementSortie(BaseModel):
    #: Instance autohébergée : il n'y a ni palier à comparer, ni abonnement à gérer.
    #: L'interface s'en sert pour ne pas afficher de vocabulaire commercial.
    mode_autoheberge: bool
    plan: PlanSortie
    statut: str
    periode_debut: datetime | None
    periode_fin: datetime | None
    renouvellement_automatique: bool
    # Un client Stripe est lié dès la première session de paiement (voir /checkout) ;
    # sert à décider si le portail de gestion (moyen de paiement, factures) est proposable.
    stripe_lie: bool
    quotas: list[QuotaSortie]
    # Message d'incitation affiché quand un quota est proche de la limite
    message_limite: str | None = None
    plan_superieur: PlanSortie | None = None


class DemandeCheckout(BaseModel):
    """Démarre un paiement Stripe pour passer au plan demandé."""

    code_plan: str = Field(min_length=1, max_length=50)


class UrlSortie(BaseModel):
    """URL de redirection Stripe (session de paiement ou portail client)."""

    url: str
