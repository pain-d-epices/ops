"""Endpoints d'investigation : création, suivi, consultation, suppression, export."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select

from app.config import config_metier
from app.db.base import maintenant
from app.facturation.garde import mode_pivot_effectif, profondeur_pivot_autorisee
from app.facturation.plans import EXPORT_CSV
from app.facturation.quotas import QuotaDepasse, consommer_quota, rembourser_quota
from app.modeles.enums import (
    ActionJournal,
    RoleMembre,
    StatutInvestigation,
    StatutPropositionPivot,
)
from app.modeles.graphe import AreteGraphe, NoeudGraphe
from app.modeles.investigation import (
    DonneeExtraite,
    Investigation,
    ProfilIdentite,
    PropositionPivot,
)
from app.modeles.utilisateur import Utilisateur
from app.schemas.investigation import (
    DemandeInvestigation,
    InvestigationDetaillee,
    InvestigationResumee,
)
from app.securite.dependances import ContexteRequete, contexte_courant, exiger_cgu, exiger_role
from app.services.journal import journaliser

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/investigations", tags=["Investigations"])


def _recuperer(ctx: ContexteRequete, investigation_id: str) -> Investigation:
    """Charge une investigation en garantissant qu'elle appartient à l'organisation.

    Le filtre sur `organisation_id` est le point de contrôle de l'isolation entre
    clients : il ne doit jamais être omis, même quand l'identifiant semble suffire.
    """
    investigation = ctx.session.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id,
            Investigation.organisation_id == ctx.organisation_id,
        )
    )
    if investigation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation introuvable.")
    return investigation


def _resume(investigation: Investigation) -> InvestigationResumee:
    return InvestigationResumee(
        id=investigation.id,
        titre=investigation.titre,
        pseudo_initial=investigation.pseudo_initial,
        statut=investigation.statut,
        progression=investigation.progression,
        etape_courante=investigation.etape_courante,
        nb_profils_trouves=investigation.nb_profils_trouves,
        nb_profils_confirmes=investigation.nb_profils_confirmes,
        nb_recherches_effectuees=investigation.nb_recherches_effectuees,
        cree_le=investigation.created_at,
        terminee_le=investigation.terminee_le,
        supprimer_apres=investigation.supprimer_apres,
    )


@routeur.post("", response_model=InvestigationDetaillee, status_code=status.HTTP_201_CREATED)
def creer_investigation(
    demande: DemandeInvestigation,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_cgu),
) -> InvestigationDetaillee:
    """Crée une investigation et met la recherche en file d'attente."""
    if not ctx.a_le_role(RoleMembre.ANALYSTE.value):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Votre rôle ne permet pas de lancer une recherche.")

    # Limite du nombre d'investigations en cours, pour éviter qu'un client ne sature
    # les workers partagés avec des dizaines de recherches simultanées.
    actives = ctx.session.scalar(
        select(func.count(Investigation.id)).where(
            Investigation.organisation_id == ctx.organisation_id,
            Investigation.statut.in_(
                [StatutInvestigation.EN_ATTENTE.value, StatutInvestigation.EN_COURS.value]
            ),
        )
    )
    if (actives or 0) >= ctx.plan.quota_investigations_actives:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Vous avez déjà {actives} investigation(s) en cours, "
            f"soit le maximum du plan {ctx.plan.nom_affiche}.",
        )

    try:
        consommer_quota(ctx.session, ctx.organisation_id, ctx.plan, "recherches")
    except QuotaDepasse as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc

    # Les options envoyées par le client sont systématiquement bornées côté serveur.
    profondeur = profondeur_pivot_autorisee(ctx.plan, ctx.organisation, demande.profondeur_pivot)
    mode = mode_pivot_effectif(
        ctx.plan, ctx.organisation, demande.mode_pivot.value if demande.mode_pivot else None
    )
    top_sites_max = int(config_metier().obtenir("maigret.top_sites", 500))
    top_sites = min(demande.top_sites or top_sites_max, 3000)

    jours_retention = ctx.organisation.retention_jours or int(
        config_metier().obtenir("retention.jours_defaut", 90)
    )

    investigation = Investigation(
        organisation_id=ctx.organisation_id,
        cree_par=ctx.utilisateur.id,
        titre=demande.titre,
        pseudo_initial=demande.pseudo.strip(),
        variantes=[v.strip() for v in demande.variantes if v.strip()],
        options={
            "profondeur": profondeur,
            "mode_pivot": mode,
            "top_sites": top_sites,
            "sites_exclus": demande.sites_exclus,
            "plan_au_lancement": ctx.plan.code,
        },
        statut=StatutInvestigation.EN_ATTENTE.value,
        supprimer_apres=maintenant() + timedelta(days=jours_retention),
    )
    ctx.session.add(investigation)
    ctx.session.flush()

    journaliser(
        ctx.session, ActionJournal.INVESTIGATION_CREEE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=investigation.pseudo_initial,
        investigation_id=investigation.id, requete=requete,
        detail={"profondeur": profondeur, "mode_pivot": mode, "plan": ctx.plan.code},
    )
    ctx.session.commit()

    try:
        from app.taches.recherche import lancer_investigation

        lancer_investigation.apply_async(
            kwargs={"investigation_id": investigation.id}, queue="recherche"
        )
    except Exception as exc:  # noqa: BLE001
        # File de tâches injoignable : rendre le quota consommé plutôt que de le
        # facturer au client pour une recherche qui n'a jamais démarré.
        journal.exception("Mise en file impossible pour l'investigation %s", investigation.id)
        investigation.statut = StatutInvestigation.ERREUR.value
        investigation.message_erreur = "Le service de traitement est momentanément indisponible."
        rembourser_quota(ctx.session, ctx.organisation_id, "recherches")
        ctx.session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Le service de traitement est momentanément indisponible. Réessayez dans un instant.",
        ) from exc

    return _detail(ctx, investigation)


@routeur.get("", response_model=list[InvestigationResumee])
def lister_investigations(
    ctx: ContexteRequete = Depends(contexte_courant),
    statut: str | None = Query(default=None),
    limite: int = Query(default=50, ge=1, le=200),
    decalage: int = Query(default=0, ge=0),
) -> list[InvestigationResumee]:
    requete = select(Investigation).where(Investigation.organisation_id == ctx.organisation_id)
    if statut:
        requete = requete.where(Investigation.statut == statut)
    requete = requete.order_by(Investigation.created_at.desc()).limit(limite).offset(decalage)
    return [_resume(i) for i in ctx.session.scalars(requete)]


def _detail(ctx: ContexteRequete, investigation: Investigation) -> InvestigationDetaillee:
    nb_noeuds = ctx.session.scalar(
        select(func.count(NoeudGraphe.id)).where(NoeudGraphe.investigation_id == investigation.id)
    )
    nb_aretes = ctx.session.scalar(
        select(func.count(AreteGraphe.id)).where(AreteGraphe.investigation_id == investigation.id)
    )
    nb_propositions = ctx.session.scalar(
        select(func.count(PropositionPivot.id)).where(
            PropositionPivot.investigation_id == investigation.id,
            PropositionPivot.statut == StatutPropositionPivot.EN_ATTENTE.value,
        )
    )
    auteur = ctx.session.get(Utilisateur, investigation.cree_par) if investigation.cree_par else None

    base = _resume(investigation)
    return InvestigationDetaillee(
        **base.model_dump(),
        variantes=investigation.variantes or [],
        options=investigation.options or {},
        message_erreur=investigation.message_erreur,
        cree_par_email=auteur.email if auteur else None,
        nb_noeuds=nb_noeuds or 0,
        nb_aretes=nb_aretes or 0,
        nb_propositions_en_attente=nb_propositions or 0,
    )


@routeur.get("/{investigation_id}", response_model=InvestigationDetaillee)
def obtenir_investigation(
    investigation_id: str,
    ctx: ContexteRequete = Depends(contexte_courant),
) -> InvestigationDetaillee:
    return _detail(ctx, _recuperer(ctx, investigation_id))


@routeur.delete("/{investigation_id}", status_code=status.HTTP_204_NO_CONTENT)
def supprimer_investigation(
    investigation_id: str,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ANALYSTE.value)),
) -> None:
    """Supprime définitivement une investigation et toutes ses données associées.

    Suppression réelle et non archivage : c'est ce qu'exige un droit à l'effacement
    exercé par une personne figurant dans les résultats.
    """
    investigation = _recuperer(ctx, investigation_id)
    journaliser(
        ctx.session, ActionJournal.INVESTIGATION_SUPPRIMEE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=investigation.pseudo_initial,
        investigation_id=investigation.id, requete=requete,
    )
    ctx.session.delete(investigation)
    ctx.session.commit()


@routeur.post("/{investigation_id}/relancer-correlation", response_model=InvestigationDetaillee)
def relancer_correlation(
    investigation_id: str,
    ctx: ContexteRequete = Depends(contexte_courant),
) -> InvestigationDetaillee:
    """Recalcule les scores sans relancer aucune requête réseau.

    Utile après ajustement des poids dans config.yaml, ou après qu'un analyste a
    marqué des faux positifs : les règles croisées changent alors pour tout le monde.
    """
    from app.services.investigation import rescorer_investigation

    investigation = _recuperer(ctx, investigation_id)
    rescorer_investigation(ctx.session, investigation)
    ctx.session.commit()
    return _detail(ctx, investigation)


@routeur.get("/{investigation_id}/export")
def exporter(
    investigation_id: str,
    requete: Request,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    ctx: ContexteRequete = Depends(contexte_courant),
) -> Response:
    """Exporte les résultats en JSON (complet) ou CSV (tableau des profils)."""
    investigation = _recuperer(ctx, investigation_id)

    if format == "csv" and not ctx.plan.possede(EXPORT_CSV):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"L'export CSV n'est pas inclus dans le plan {ctx.plan.nom_affiche}.",
        )

    profils = ctx.session.scalars(
        select(ProfilIdentite)
        .where(ProfilIdentite.investigation_id == investigation.id)
        .order_by(ProfilIdentite.score_confiance.desc())
    ).all()

    journaliser(
        ctx.session, ActionJournal.EXPORT,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=investigation.pseudo_initial,
        investigation_id=investigation.id, requete=requete, detail={"format": format},
    )
    ctx.session.commit()

    nom_fichier = f"investigation_{investigation.pseudo_initial}_{investigation.id[:8]}"

    if format == "csv":
        tampon = io.StringIO()
        redacteur = csv.writer(tampon, delimiter=";")   # point-virgule : ouverture directe dans Excel FR
        redacteur.writerow(
            ["Site", "Domaine", "URL", "Pseudonyme", "Score", "Niveau", "Verdict", "Profondeur", "Enrichi"]
        )
        for profil in profils:
            redacteur.writerow([
                profil.site_nom, profil.site_domaine, profil.url, profil.pseudo_sur_le_site,
                profil.score_confiance, profil.niveau, profil.verdict_manuel or "",
                profil.profondeur, "oui" if profil.enrichi else "non",
            ])
        return Response(
            content="﻿" + tampon.getvalue(),   # BOM UTF-8 pour les accents dans Excel
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nom_fichier}.csv"'},
        )

    donnees = ctx.session.scalars(
        select(DonneeExtraite).where(DonneeExtraite.investigation_id == investigation.id)
    ).all()
    par_profil: dict[str, list[dict]] = {}
    for donnee in donnees:
        par_profil.setdefault(donnee.profil_id, []).append(
            {"type": donnee.type, "valeur": donnee.valeur, "source": donnee.module_source}
        )

    contenu = {
        "investigation": {
            "id": investigation.id,
            "pseudo_initial": investigation.pseudo_initial,
            "variantes": investigation.variantes,
            "statut": investigation.statut,
            "options": investigation.options,
            "cree_le": investigation.created_at.isoformat() if investigation.created_at else None,
            "terminee_le": investigation.terminee_le.isoformat() if investigation.terminee_le else None,
        },
        "profils": [
            {
                "site": p.site_nom, "url": p.url, "pseudo": p.pseudo_sur_le_site,
                "score": p.score_confiance, "niveau": p.niveau, "verdict": p.verdict_manuel,
                "profondeur": p.profondeur, "donnees_extraites": par_profil.get(p.id, []),
            }
            for p in profils
        ],
        "avertissement": (
            "Ces résultats sont des estimations probabilistes et non des certitudes. "
            "Ils doivent être vérifiés avant toute utilisation, et leur exploitation "
            "relève de la responsabilité de l'utilisateur dans le cadre légal applicable."
        ),
    }
    return Response(
        content=json.dumps(contenu, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}.json"'},
    )
