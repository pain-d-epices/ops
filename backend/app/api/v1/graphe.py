"""Endpoint du graphe de relations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.modeles.investigation import Investigation
from app.moteur.graphe.depot import DepotGraphe
from app.schemas.investigation import AreteSortie, GrapheSortie, NoeudSortie
from app.securite.dependances import ContexteRequete, contexte_courant

routeur = APIRouter(prefix="/investigations/{investigation_id}/graphe", tags=["Graphe"])


@routeur.get("", response_model=GrapheSortie)
def obtenir_graphe(
    investigation_id: str,
    ctx: ContexteRequete = Depends(contexte_courant),
    score_minimal: int = Query(default=0, ge=0, le=100),
    types_exclus: str | None = Query(
        default=None, description="Types de nœuds à masquer, séparés par des virgules"
    ),
) -> GrapheSortie:
    """Graphe complet de l'investigation, filtrable par score et par type de nœud."""
    investigation = ctx.session.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id,
            Investigation.organisation_id == ctx.organisation_id,
        )
    )
    if investigation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation introuvable.")

    exclus = {t.strip() for t in (types_exclus or "").split(",") if t.strip()}
    depot = DepotGraphe(ctx.session, investigation.id, ctx.organisation_id)
    graphe = depot.exporter(score_minimal=score_minimal, types_exclus=exclus)

    return GrapheSortie(
        investigation_id=investigation.id,
        noeuds=[
            NoeudSortie(
                id=n.id, type=n.type, libelle=n.libelle, score=n.score,
                profondeur=n.profondeur, profil_id=n.profil_id, meta=n.meta,
            )
            for n in graphe.noeuds
        ],
        aretes=[
            AreteSortie(
                id=a.id, source=a.source, cible=a.cible,
                type=a.type, libelle=a.libelle, poids=a.poids,
            )
            for a in graphe.aretes
        ],
    )
