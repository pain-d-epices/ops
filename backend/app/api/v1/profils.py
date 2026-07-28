"""Endpoints des profils : liste triable, détail explicable, verdict manuel, enrichissement."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.db.base import maintenant
from app.facturation.garde import FonctionnaliteIndisponible, exiger_fonctionnalite
from app.facturation.plans import MODULES
from app.modeles.enums import ActionJournal, RoleMembre
from app.modeles.investigation import (
    DonneeExtraite,
    Investigation,
    ProfilIdentite,
    SignalCorrelation,
)
from app.schemas.investigation import (
    DemandeVerdict,
    DonneeSortie,
    ProfilDetaille,
    ProfilResume,
    SignalSortie,
)
from app.securite.dependances import ContexteRequete, contexte_courant, exiger_role
from app.services.journal import journaliser

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/investigations/{investigation_id}/profils", tags=["Profils"])


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


def _profil(ctx: ContexteRequete, investigation_id: str, profil_id: str) -> ProfilIdentite:
    profil = ctx.session.scalar(
        select(ProfilIdentite).where(
            ProfilIdentite.id == profil_id,
            ProfilIdentite.investigation_id == investigation_id,
            ProfilIdentite.organisation_id == ctx.organisation_id,
        )
    )
    if profil is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable.")
    return profil


def _resume(profil: ProfilIdentite) -> ProfilResume:
    return ProfilResume(
        id=profil.id,
        site_nom=profil.site_nom,
        site_domaine=profil.site_domaine,
        url=profil.url,
        pseudo_sur_le_site=profil.pseudo_sur_le_site,
        score_confiance=profil.score_confiance,
        niveau=profil.niveau,
        verdict_manuel=profil.verdict_manuel,
        profondeur=profil.profondeur,
        enrichi=profil.enrichi,
        module_utilise=profil.module_utilise,
    )


@routeur.get("", response_model=list[ProfilResume])
def lister_profils(
    investigation_id: str,
    ctx: ContexteRequete = Depends(contexte_courant),
    score_minimal: int = Query(default=0, ge=0, le=100),
    niveau: str | None = Query(default=None),
    inclure_faux_positifs: bool = Query(default=False),
    tri: str = Query(default="score", pattern="^(score|site|profondeur)$"),
) -> list[ProfilResume]:
    """Vue tableau des profils, filtrable et triable — alternative au graphe."""
    _investigation(ctx, investigation_id)

    requete = select(ProfilIdentite).where(
        ProfilIdentite.investigation_id == investigation_id,
        ProfilIdentite.organisation_id == ctx.organisation_id,
        ProfilIdentite.score_confiance >= score_minimal,
    )
    if niveau:
        requete = requete.where(ProfilIdentite.niveau == niveau)
    if not inclure_faux_positifs:
        requete = requete.where(
            (ProfilIdentite.verdict_manuel.is_(None)) | (ProfilIdentite.verdict_manuel != "faux_positif")
        )

    colonnes = {
        "score": ProfilIdentite.score_confiance.desc(),
        "site": ProfilIdentite.site_nom.asc(),
        "profondeur": ProfilIdentite.profondeur.asc(),
    }
    requete = requete.order_by(colonnes[tri])
    return [_resume(p) for p in ctx.session.scalars(requete)]


@routeur.get("/{profil_id}", response_model=ProfilDetaille)
def obtenir_profil(
    investigation_id: str,
    profil_id: str,
    ctx: ContexteRequete = Depends(contexte_courant),
) -> ProfilDetaille:
    """Fiche complète d'un profil, avec le détail du calcul de son score."""
    _investigation(ctx, investigation_id)
    profil = _profil(ctx, investigation_id, profil_id)

    donnees = ctx.session.scalars(
        select(DonneeExtraite).where(DonneeExtraite.profil_id == profil.id)
    ).all()
    signaux = ctx.session.scalars(
        select(SignalCorrelation)
        .where(SignalCorrelation.profil_id == profil.id)
        .order_by(SignalCorrelation.contribution_points.desc())
    ).all()

    return ProfilDetaille(
        **_resume(profil).model_dump(),
        statut_maigret=profil.statut_maigret,
        decouvert_par_profil_id=profil.decouvert_par_profil_id,
        erreur_enrichissement=profil.erreur_enrichissement,
        verdict_le=profil.verdict_le,
        enrichi_le=profil.enrichi_le,
        donnees_maigret=profil.donnees_maigret or {},
        donnees_extraites=[
            DonneeSortie(
                id=d.id, type=d.type, valeur=d.valeur, module_source=d.module_source,
                confiance_extraction=d.confiance_extraction, pivotee=d.pivotee, meta=d.meta or {},
            )
            for d in donnees
        ],
        signaux=[
            SignalSortie(
                regle=s.regle, score_regle=s.score_regle, poids=s.poids,
                contribution_points=s.contribution_points, explication=s.explication,
                detail=s.detail or {},
            )
            for s in signaux
        ],
    )


@routeur.post("/{profil_id}/verdict", response_model=ProfilResume)
def definir_verdict(
    investigation_id: str,
    profil_id: str,
    demande: DemandeVerdict,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ANALYSTE.value)),
) -> ProfilResume:
    """Valide ou rejette manuellement un profil.

    Le verdict humain prime sur le score calculé, et modifie le score des autres
    profils : un profil rejeté cesse de servir de point de comparaison aux règles
    croisées. L'ensemble est donc rescoré dans la foulée.
    """
    investigation = _investigation(ctx, investigation_id)
    profil = _profil(ctx, investigation_id, profil_id)

    profil.verdict_manuel = demande.verdict.value if demande.verdict else None
    profil.verdict_par = ctx.utilisateur.id
    profil.verdict_le = maintenant()

    from app.services.investigation import rescorer_investigation

    rescorer_investigation(ctx.session, investigation)

    journaliser(
        ctx.session, ActionJournal.PROFIL_VERDICT,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=profil.url,
        investigation_id=investigation_id, requete=requete,
        detail={"verdict": profil.verdict_manuel},
    )
    ctx.session.commit()
    ctx.session.refresh(profil)
    return _resume(profil)


@routeur.post("/{profil_id}/enrichir", status_code=status.HTTP_202_ACCEPTED)
def enrichir(
    investigation_id: str,
    profil_id: str,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ANALYSTE.value)),
) -> dict:
    """Déclenche l'enrichissement d'un profil précis (fonctionnalité payante)."""
    _investigation(ctx, investigation_id)
    profil = _profil(ctx, investigation_id, profil_id)

    try:
        exiger_fonctionnalite(ctx.plan, MODULES)
    except FonctionnaliteIndisponible as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    from app.modules.registre import module_pour_domaine

    module = module_pour_domaine(profil.site_domaine)
    if module is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Aucun module d'enrichissement ne couvre le site {profil.site_nom} pour le moment.",
        )

    journaliser(
        ctx.session, ActionJournal.ENRICHISSEMENT_LANCE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=profil.url,
        investigation_id=investigation_id, requete=requete, detail={"module": module.nom},
    )
    ctx.session.commit()

    from app.taches.enrichissement import enrichir_profil_unique

    enrichir_profil_unique.apply_async(
        kwargs={"investigation_id": investigation_id, "profil_id": profil_id},
        queue="enrichissement",
    )
    return {"statut": "en_cours", "module": module.nom}
