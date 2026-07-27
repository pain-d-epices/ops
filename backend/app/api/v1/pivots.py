"""Endpoints du pivot : consultation et validation des propositions (mode supervisé)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.db.base import maintenant
from app.facturation.garde import FonctionnaliteIndisponible, exiger_fonctionnalite, pivot_disponible
from app.facturation.plans import PIVOT
from app.modeles.enums import ActionJournal, RoleMembre, StatutPropositionPivot
from app.modeles.investigation import Investigation, PropositionPivot
from app.schemas.investigation import DemandeDecisionPivot, PropositionSortie
from app.securite.dependances import ContexteRequete, contexte_courant, exiger_role
from app.services.journal import journaliser

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/investigations/{investigation_id}/pivots", tags=["Pivots"])


def _investigation(ctx: ContexteRequete, investigation_id: str) -> Investigation:
    investigation = ctx.session.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id,
            Investigation.organisation_id == ctx.organisation_id,
        )
    )
    if investigation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation introuvable.")
    return investigation


def _sortie(proposition: PropositionPivot) -> PropositionSortie:
    return PropositionSortie(
        id=proposition.id,
        type_pivot=proposition.type_pivot,
        valeur=proposition.valeur,
        action=proposition.action,
        libelle=proposition.libelle,
        profondeur_cible=proposition.profondeur_cible,
        statut=proposition.statut,
        profil_source_id=proposition.profil_source_id,
        cree_le=proposition.created_at,
        decidee_le=proposition.decidee_le,
    )


@routeur.get("", response_model=list[PropositionSortie])
def lister_propositions(
    investigation_id: str,
    ctx: ContexteRequete = Depends(contexte_courant),
    statut: str | None = Query(default=None),
) -> list[PropositionSortie]:
    _investigation(ctx, investigation_id)
    requete = select(PropositionPivot).where(
        PropositionPivot.investigation_id == investigation_id,
        PropositionPivot.organisation_id == ctx.organisation_id,
    )
    if statut:
        requete = requete.where(PropositionPivot.statut == statut)
    requete = requete.order_by(PropositionPivot.created_at.desc())
    return [_sortie(p) for p in ctx.session.scalars(requete)]


@routeur.post("/{proposition_id}/decision", response_model=PropositionSortie)
def decider(
    investigation_id: str,
    proposition_id: str,
    demande: DemandeDecisionPivot,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ANALYSTE.value)),
) -> PropositionSortie:
    """Accepte ou refuse une proposition de pivot (mode supervisé).

    Accepter déclenche une nouvelle recherche, qui consomme du quota : c'est bien
    une décision, pas un simple affichage.
    """
    investigation = _investigation(ctx, investigation_id)

    try:
        exiger_fonctionnalite(ctx.plan, PIVOT)
    except FonctionnaliteIndisponible as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    if not pivot_disponible(ctx.plan):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Le pivot n'est pas disponible avec le plan {ctx.plan.nom_affiche}.",
        )

    proposition = ctx.session.scalar(
        select(PropositionPivot).where(
            PropositionPivot.id == proposition_id,
            PropositionPivot.investigation_id == investigation_id,
            PropositionPivot.organisation_id == ctx.organisation_id,
        )
    )
    if proposition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposition introuvable.")
    if proposition.statut != StatutPropositionPivot.EN_ATTENTE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cette proposition a déjà été traitée (statut : {proposition.statut}).",
        )

    # La profondeur autorisée est revérifiée au moment de la décision : le plan de
    # l'organisation a pu changer depuis la création de la proposition.
    from app.facturation.garde import profondeur_pivot_autorisee

    profondeur_max = profondeur_pivot_autorisee(
        ctx.plan, ctx.organisation, (investigation.options or {}).get("profondeur")
    )
    if demande.accepter and proposition.profondeur_cible > profondeur_max:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Ce pivot dépasse la profondeur maximale autorisée par votre plan ({profondeur_max}).",
        )

    proposition.statut = (
        StatutPropositionPivot.ACCEPTEE.value if demande.accepter else StatutPropositionPivot.REFUSEE.value
    )
    proposition.decidee_par = ctx.utilisateur.id
    proposition.decidee_le = maintenant()

    journaliser(
        ctx.session, ActionJournal.PIVOT_DECIDE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=proposition.valeur,
        investigation_id=investigation_id, requete=requete,
        detail={"accepte": demande.accepter, "type": proposition.type_pivot},
    )
    ctx.session.commit()

    if demande.accepter:
        from app.taches.pivot import executer_proposition_pivot

        executer_proposition_pivot.apply_async(
            kwargs={"investigation_id": investigation_id, "proposition_id": proposition_id},
            queue="pivot",
        )

    ctx.session.refresh(proposition)
    return _sortie(proposition)
