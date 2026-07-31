"""Endpoints d'abonnement : plan actif, quotas consommés, paiement et gestion Stripe."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.facturation.abonnements import abonnement_actif
from app.facturation.quotas import etat_quotas
from app.modeles.enums import RoleMembre
from app.modeles.facturation import Plan
from app.schemas.abonnement import (
    AbonnementSortie,
    DemandeCheckout,
    PlanSortie,
    QuotaSortie,
    UrlSortie,
)
from app.securite.dependances import ContexteRequete, contexte_courant, exiger_role
from app.services.facturation_stripe import ErreurStripe, creer_session_paiement, creer_session_portail

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/abonnement", tags=["Abonnement"])

# Seuil à partir duquel on incite à passer au palier supérieur
SEUIL_ALERTE_QUOTA = 80.0


def _plan_sortie(plan: Plan, plan_actuel_code: str | None = None) -> PlanSortie:
    return PlanSortie(
        code=plan.code,
        nom_affiche=plan.nom_affiche,
        description=plan.description,
        prix_mensuel_cents=plan.prix_mensuel_cents,
        ordre=plan.ordre,
        quota_recherches_mois=plan.quota_recherches_mois,
        quota_enrichissements_mois=plan.quota_enrichissements_mois,
        quota_utilisateurs=plan.quota_utilisateurs,
        quota_investigations_actives=plan.quota_investigations_actives,
        profondeur_pivot_max=plan.profondeur_pivot_max,
        max_points_depart=plan.max_points_depart,
        fonctionnalites=list(plan.fonctionnalites or []),
        est_plan_actuel=plan.code == plan_actuel_code,
    )


@routeur.get("/plans", response_model=list[PlanSortie])
def lister_plans(ctx: ContexteRequete = Depends(contexte_courant)) -> list[PlanSortie]:
    """Tous les paliers disponibles."""
    plans = ctx.session.scalars(
        select(Plan).where(Plan.actif.is_(True)).order_by(Plan.ordre)
    ).all()
    return [_plan_sortie(p, ctx.plan.code) for p in plans]


@routeur.get("", response_model=AbonnementSortie)
def etat_abonnement(ctx: ContexteRequete = Depends(contexte_courant)) -> AbonnementSortie:
    """Plan actif, consommation du mois, et incitation à monter en gamme si utile."""
    abonnement = abonnement_actif(ctx.session, ctx.organisation_id)
    quotas = etat_quotas(ctx.session, ctx.organisation_id, ctx.plan)

    message = None
    for etat in quotas.values():
        if etat.limite and etat.pourcentage >= SEUIL_ALERTE_QUOTA:
            if etat.restant == 0:
                message = (
                    f"Votre quota « {etat.nom} » est épuisé pour ce mois "
                    f"({etat.consomme}/{etat.limite})."
                )
            else:
                message = (
                    f"Vous avez utilisé {etat.pourcentage:.0f} % de votre quota « {etat.nom} » "
                    f"({etat.consomme}/{etat.limite})."
                )
            break

    superieur = ctx.session.scalar(
        select(Plan)
        .where(Plan.actif.is_(True), Plan.ordre > ctx.plan.ordre)
        .order_by(Plan.ordre)
        .limit(1)
    )

    return AbonnementSortie(
        plan=_plan_sortie(ctx.plan, ctx.plan.code),
        statut=abonnement.statut if abonnement else "gratuit",
        periode_debut=abonnement.periode_debut if abonnement else None,
        periode_fin=abonnement.periode_fin if abonnement else None,
        renouvellement_automatique=abonnement.renouvellement_automatique if abonnement else False,
        stripe_lie=bool(abonnement and abonnement.stripe_customer_id),
        quotas=[
            QuotaSortie(
                nom=e.nom, consomme=e.consomme, limite=e.limite,
                restant=e.restant, pourcentage=e.pourcentage,
            )
            for e in quotas.values()
        ],
        message_limite=message,
        plan_superieur=_plan_sortie(superieur, ctx.plan.code) if superieur else None,
    )


@routeur.post("/checkout", response_model=UrlSortie)
def demarrer_paiement(
    demande: DemandeCheckout,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value)),
) -> UrlSortie:
    """Démarre un paiement Stripe pour passer l'organisation au plan demandé.

    L'abonnement n'est activé qu'à réception du webhook `checkout.session.completed`,
    une fois le paiement effectivement confirmé — jamais à cet appel, qui ne fait que
    créer la session vers laquelle rediriger le client.
    """
    plan = ctx.session.scalar(select(Plan).where(Plan.code == demande.code_plan, Plan.actif.is_(True)))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan introuvable.")
    if plan.prix_mensuel_cents == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Le plan gratuit ne nécessite aucun paiement.")

    try:
        url = creer_session_paiement(ctx.organisation, plan, ctx.utilisateur.email)
    except ErreurStripe as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return UrlSortie(url=url)


@routeur.post("/portail", response_model=UrlSortie)
def ouvrir_portail(
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value)),
) -> UrlSortie:
    """Ouvre le portail client Stripe : moyen de paiement, factures, annulation.

    Stripe héberge cette interface — aucune donnée de paiement ne transite par
    Searcher, ni avant ni après cet appel.
    """
    try:
        url = creer_session_portail(ctx.organisation_id, ctx.session)
    except ErreurStripe as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return UrlSortie(url=url)
