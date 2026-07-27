"""Résolution du plan actif d'une organisation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import maintenant
from app.facturation.plans import CODE_PLAN_GRATUIT
from app.modeles.enums import StatutAbonnement
from app.modeles.facturation import Abonnement, Plan


class PlanIntrouvable(RuntimeError):
    """Les plans n'ont pas été initialisés en base (voir app/scripts/initialiser_plans.py)."""


def plan_gratuit(session: Session) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.code == CODE_PLAN_GRATUIT))
    if plan is None:
        raise PlanIntrouvable(
            "Le plan gratuit est absent de la base. "
            "Lancez : python -m app.scripts.initialiser_plans"
        )
    return plan


def abonnement_actif(session: Session, organisation_id: str) -> Abonnement | None:
    """Abonnement en cours de validité, ou None si l'organisation n'en a pas.

    Un abonnement dont la période est terminée est ignoré même si son statut n'a pas
    encore été basculé : la vérification par date évite qu'un client conserve un accès
    payant à cause d'un webhook Gumroad perdu.
    """
    requete = (
        select(Abonnement)
        .where(
            Abonnement.organisation_id == organisation_id,
            Abonnement.statut == StatutAbonnement.ACTIF.value,
        )
        .order_by(Abonnement.periode_debut.desc())
    )
    for abo in session.scalars(requete):
        if abo.periode_fin is None:
            return abo
        fin = abo.periode_fin
        if fin.tzinfo is None:
            fin = fin.replace(tzinfo=timezone.utc)
        if fin > datetime.now(timezone.utc):
            return abo
    return None


def plan_actif(session: Session, organisation_id: str) -> Plan:
    """Plan effectif de l'organisation : celui de son abonnement, sinon le plan gratuit.

    Toute organisation a donc toujours un plan — pas de cas « aucun plan » à gérer
    dans le reste du code.
    """
    abo = abonnement_actif(session, organisation_id)
    if abo is not None and abo.plan is not None and abo.plan.actif:
        return abo.plan
    return plan_gratuit(session)


def expirer_abonnements_echus(session: Session) -> int:
    """Bascule en statut « expiré » les abonnements dont la période est terminée.

    Filet de sécurité exécuté par une tâche planifiée : le statut réel est de toute
    façon recalculé à la volée par `abonnement_actif`.
    """
    requete = select(Abonnement).where(
        Abonnement.statut == StatutAbonnement.ACTIF.value,
        Abonnement.periode_fin.is_not(None),
        Abonnement.periode_fin < maintenant(),
    )
    compte = 0
    for abo in session.scalars(requete):
        abo.statut = StatutAbonnement.EXPIRE.value
        compte += 1
    return compte
