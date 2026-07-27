"""Endpoints d'abonnement : plan actif, quotas consommés, activation de licence Gumroad."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.config import parametres
from app.facturation.abonnements import abonnement_actif
from app.facturation.quotas import etat_quotas
from app.modeles.enums import ActionJournal, RoleMembre
from app.modeles.facturation import Plan
from app.schemas.abonnement import (
    AbonnementSortie,
    DemandeActivationLicence,
    PlanSortie,
    QuotaSortie,
)
from app.securite.dependances import ContexteRequete, contexte_courant, exiger_role
from app.services.gumroad import (
    ErreurGumroad,
    LicenceInvalide,
    activer_abonnement,
    verifier_licence,
)
from app.services.journal import journaliser

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/abonnement", tags=["Abonnement"])

# Seuil à partir duquel on incite à passer au palier supérieur
SEUIL_ALERTE_QUOTA = 80.0


def _plan_sortie(plan: Plan, plan_actuel_code: str | None = None) -> PlanSortie:
    url_achat = None
    if plan.gumroad_product_id:
        # Gumroad propose une URL d'achat directe par produit ; l'identifiant est
        # configuré dans le .env (GUMROAD_PRODUITS).
        url_achat = f"https://gumroad.com/l/{plan.gumroad_product_id}"

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
        fonctionnalites=list(plan.fonctionnalites or []),
        url_achat=url_achat,
        est_plan_actuel=plan.code == plan_actuel_code,
    )


@routeur.get("/plans", response_model=list[PlanSortie])
def lister_plans(ctx: ContexteRequete = Depends(contexte_courant)) -> list[PlanSortie]:
    """Tous les paliers disponibles, avec le lien d'achat Gumroad correspondant."""
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
        licence_active=bool(abonnement and abonnement.gumroad_license_key),
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


@routeur.post("/licence", response_model=AbonnementSortie)
def activer_licence(
    demande: DemandeActivationLicence,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value)),
) -> AbonnementSortie:
    """Active un abonnement à partir d'une clé de licence Gumroad.

    Voie principale d'activation : le webhook Gumroad ne suffit pas, car il n'est pas
    réémis en cas d'échec et l'achat précède souvent la création du compte.
    """
    if not parametres().gumroad_access_token and not demande.code_plan:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "La vérification des licences n'est pas configurée sur ce serveur.",
        )

    # Déterminer le produit à vérifier : soit le plan demandé, soit un essai sur
    # chacun des produits configurés.
    plans_candidats = ctx.session.scalars(
        select(Plan).where(Plan.actif.is_(True), Plan.gumroad_product_id.is_not(None))
    ).all()
    if demande.code_plan:
        plans_candidats = [p for p in plans_candidats if p.code == demande.code_plan]

    if not plans_candidats:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Aucun produit Gumroad n'est associé à un plan sur ce serveur.",
        )

    derniere_erreur = "Clé de licence non reconnue."
    for plan in plans_candidats:
        try:
            achat = verifier_licence(plan.gumroad_product_id or "", demande.cle_licence)
        except LicenceInvalide as exc:
            derniere_erreur = str(exc)
            continue
        except ErreurGumroad as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

        activer_abonnement(
            ctx.session,
            ctx.organisation,
            plan,
            cle_licence=demande.cle_licence,
            gumroad_product_id=plan.gumroad_product_id,
            gumroad_sale_id=achat.get("sale_id") or achat.get("id"),
            email_acheteur=achat.get("email"),
        )
        journaliser(
            ctx.session, ActionJournal.PLAN_CHANGE,
            organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
            email_utilisateur=ctx.utilisateur.email, requete=requete,
            detail={"plan": plan.code, "source": "licence_manuelle"},
        )
        ctx.session.commit()

        # Le contexte a été construit avec l'ancien plan : le rafraîchir pour que la
        # réponse reflète immédiatement le nouvel abonnement.
        from app.facturation.abonnements import plan_actif

        ctx.plan = plan_actif(ctx.session, ctx.organisation_id)
        return etat_abonnement(ctx)

    raise HTTPException(status.HTTP_400_BAD_REQUEST, derniere_erreur)
