"""Tâches d'enrichissement : application des modules de site aux profils retenus.

Réservé aux plans incluant la fonctionnalité « modules ». La vérification est refaite
ici et non seulement à l'appel de l'API : entre la mise en file et l'exécution, un
abonnement a pu expirer.
"""

from __future__ import annotations

import logging

from app.config import config_metier
from app.db.session import portee_session
from app.facturation.abonnements import plan_actif
from app.facturation.garde import pivot_disponible
from app.facturation.plans import MODULES
from app.facturation.quotas import QuotaDepasse, consommer_quota
from app.infra.evenements import TypeEvenement, bus
from app.modeles.investigation import Investigation
from app.services.investigation import (
    enrichir_profil,
    profils_a_enrichir,
    rescorer_investigation,
)
from app.taches.celery_app import celery_app

journal = logging.getLogger(__name__)


@celery_app.task(name="app.taches.enrichissement.enrichir_investigation")
def enrichir_investigation(investigation_id: str, profondeur: int = 0) -> dict:
    """Enrichit les profils crédibles de l'investigation, puis enchaîne sur le pivot."""
    conf = config_metier()
    score_minimal = int(conf.obtenir("correlation.score_minimal_pivot", 50))

    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            return {"statut": "introuvable"}

        organisation_id = investigation.organisation_id
        plan = plan_actif(session, organisation_id)

        if not plan.possede(MODULES):
            journal.info(
                "Enrichissement ignoré pour l'investigation %s : plan %s sans la fonctionnalité modules",
                investigation_id, plan.code,
            )
            _terminer(investigation_id)
            return {"statut": "non_autorise"}

        candidats = [p.id for p in profils_a_enrichir(session, investigation, score_minimal)]
        investigation.etape_courante = f"Enrichissement de {len(candidats)} profil(s)"

    bus().emettre(
        TypeEvenement.ETAPE, investigation_id, organisation_id,
        etape=f"Enrichissement de {len(candidats)} profil(s)", progression=80,
    )

    enrichis = 0
    quota_epuise = False

    for profil_id in candidats:
        # Une session par profil : un module lent ou en erreur ne doit pas maintenir
        # une transaction ouverte sur toute la durée de l'enrichissement.
        with portee_session() as session:
            investigation = session.get(Investigation, investigation_id)
            if investigation is None:
                break

            from app.modeles.investigation import ProfilIdentite

            profil = session.get(ProfilIdentite, profil_id)
            if profil is None:
                continue

            plan = plan_actif(session, organisation_id)
            try:
                consommer_quota(session, organisation_id, plan, "enrichissements")
            except QuotaDepasse as exc:
                journal.info("Quota d'enrichissements épuisé pour l'organisation %s", organisation_id)
                bus().emettre(
                    TypeEvenement.ETAPE, investigation_id, organisation_id,
                    etape=str(exc), quota_epuise=True,
                )
                quota_epuise = True
                break

            erreur = enrichir_profil(session, investigation, profil)
            if erreur is None:
                enrichis += 1
            bus().emettre(
                TypeEvenement.PROFIL_MIS_A_JOUR, investigation_id, organisation_id,
                profil_id=profil_id, enrichi=True, erreur=erreur,
            )

    # Les données fraîchement extraites changent les scores : il faut rescorer avant
    # de décider quels profils peuvent servir de point de pivot.
    pivot_possible = False
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is not None:
            rescorer_investigation(session, investigation)
            investigation.progression = max(investigation.progression, 85)
            plan = plan_actif(session, organisation_id)
            pivot_possible = pivot_disponible(plan) and not quota_epuise

    if pivot_possible:
        from app.taches.pivot import detecter_et_pivoter

        detecter_et_pivoter.apply_async(
            kwargs={"investigation_id": investigation_id, "profondeur_source": profondeur},
            queue="pivot",
        )
    else:
        _terminer(investigation_id)

    return {"statut": "ok", "profils_enrichis": enrichis, "quota_epuise": quota_epuise}


def _terminer(investigation_id: str) -> None:
    from app.taches.recherche import finaliser_investigation

    finaliser_investigation.apply_async(
        kwargs={"investigation_id": investigation_id}, queue="enrichissement"
    )


@celery_app.task(name="app.taches.enrichissement.enrichir_profil_unique")
def enrichir_profil_unique(investigation_id: str, profil_id: str) -> dict:
    """Enrichissement d'un seul profil, déclenché manuellement depuis l'interface."""
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            return {"statut": "introuvable"}

        from app.modeles.investigation import ProfilIdentite

        profil = session.get(ProfilIdentite, profil_id)
        if profil is None or profil.investigation_id != investigation_id:
            return {"statut": "introuvable"}

        plan = plan_actif(session, investigation.organisation_id)
        if not plan.possede(MODULES):
            return {"statut": "non_autorise"}

        try:
            consommer_quota(session, investigation.organisation_id, plan, "enrichissements")
        except QuotaDepasse as exc:
            return {"statut": "quota_depasse", "message": str(exc)}

        erreur = enrichir_profil(session, investigation, profil)
        rescorer_investigation(session, investigation)
        organisation_id = investigation.organisation_id

    bus().emettre(
        TypeEvenement.PROFIL_MIS_A_JOUR, investigation_id, organisation_id,
        profil_id=profil_id, enrichi=True, erreur=erreur,
    )
    return {"statut": "ok", "erreur": erreur}
