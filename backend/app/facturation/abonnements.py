"""Résolution du plan actif d'une organisation, et gestion des abonnements.

Volontairement indépendant du fournisseur de paiement (Stripe) : ce module ne connaît
que la notion d'abonnement actif/résilié, jamais les identifiants Stripe eux-mêmes en
dehors des colonnes où les stocker. Le code métier (quotas, garde-fous par plan) reste
ainsi valable même si le fournisseur change un jour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.base import maintenant
from app.facturation.plans import CODE_PLAN_GRATUIT
from app.modeles.enums import StatutAbonnement
from app.modeles.facturation import Abonnement, Plan
from app.modeles.organisation import Organisation


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


def activer_abonnement(
    session: Session,
    organisation: Organisation,
    plan: Plan,
    *,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    stripe_price_id: str | None = None,
    duree_jours: int = 31,
) -> Abonnement:
    """Active un plan pour une organisation et clôt l'abonnement précédent.

    Une organisation n'a jamais deux abonnements actifs simultanément : l'ancien passe
    en « annulé », ce qui évite toute ambiguïté sur le plan réellement applicable.

    `duree_jours` n'est qu'une estimation initiale de la fin de période : l'échéance
    réelle arrive ensuite par webhook (`customer.subscription.updated`), qui la
    corrige. Sans ce filet, une organisation resterait sur le plan gratuit entre le
    paiement et le premier webhook de renouvellement.
    """
    anciens = session.scalars(
        select(Abonnement).where(
            Abonnement.organisation_id == organisation.id,
            Abonnement.statut == StatutAbonnement.ACTIF.value,
        )
    ).all()
    for ancien in anciens:
        ancien.statut = StatutAbonnement.ANNULE.value

    debut = maintenant()
    abonnement = Abonnement(
        organisation_id=organisation.id,
        plan_id=plan.id,
        statut=StatutAbonnement.ACTIF.value,
        periode_debut=debut,
        periode_fin=debut + timedelta(days=duree_jours),
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        stripe_price_id=stripe_price_id or plan.stripe_price_id,
        derniere_verification=debut,
    )
    session.add(abonnement)
    return abonnement


def resilier_abonnements(
    session: Session, *, stripe_customer_id: str | None = None, stripe_subscription_id: str | None = None
) -> int:
    """Passe en « annulé » les abonnements correspondant à un client ou une
    souscription Stripe. Rend le nombre d'abonnements résiliés."""
    if not stripe_customer_id and not stripe_subscription_id:
        return 0

    conditions = []
    if stripe_customer_id:
        conditions.append(Abonnement.stripe_customer_id == stripe_customer_id)
    if stripe_subscription_id:
        conditions.append(Abonnement.stripe_subscription_id == stripe_subscription_id)

    abonnements = session.scalars(
        select(Abonnement).where(
            Abonnement.statut == StatutAbonnement.ACTIF.value,
            or_(*conditions),
        )
    ).all()
    for abo in abonnements:
        abo.statut = StatutAbonnement.ANNULE.value
        abo.periode_fin = maintenant()
    return len(abonnements)
