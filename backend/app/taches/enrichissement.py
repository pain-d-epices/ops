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
from app.moteur.annulation import est_annulee
from app.services.investigation import (
    enregistrer_enrichissement,
    executer_module,
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
        # Annulée pendant l'attente en file : ne rien enrichir, ne rien enchaîner.
        if est_annulee(investigation_id, session):
            return {"statut": "annulee"}

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

    from app.modeles.investigation import ProfilIdentite

    annulee = False
    for profil_id in candidats:
        # --- Étape 1 : réserver le quota et lire ce qu'il faut (transaction courte) ---
        with portee_session() as session:
            # Chaque profil est un appel réseau : point de reprise avant d'engager le
            # suivant, et avant de consommer un quota qui ne servirait à rien.
            if est_annulee(investigation_id, session):
                annulee = True
                break

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

            url, pseudo, domaine = profil.url, profil.pseudo_sur_le_site, profil.site_domaine

        # --- Étape 2 : interroger le site, HORS transaction ---
        # Un enrichissement dure plusieurs secondes. Garder une connexion PostgreSQL
        # ouverte pendant ce temps saturerait le pool dès que plusieurs organisations
        # enrichissent en parallèle.
        prepare = executer_module(url, pseudo, domaine)

        # --- Étape 3 : enregistrer le résultat (transaction courte) ---
        with portee_session() as session:
            investigation = session.get(Investigation, investigation_id)
            profil = session.get(ProfilIdentite, profil_id)
            if investigation is None or profil is None:
                break
            erreur = enregistrer_enrichissement(session, investigation, profil, prepare)

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
            # Rescorer même après annulation : les profils enrichis avant l'arrêt
            # doivent porter un score cohérent.
            rescorer_investigation(session, investigation)
            annulee = annulee or est_annulee(investigation_id, session)
            if not annulee:
                investigation.progression = max(investigation.progression, 85)
            plan = plan_actif(session, organisation_id)
            pivot_possible = pivot_disponible(plan) and not quota_epuise and not annulee

    if annulee:
        from app.taches.recherche import _cloturer_annulation

        return _cloturer_annulation(investigation_id, organisation_id)

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
    from app.modeles.investigation import ProfilIdentite

    # Étape 1 : vérifications et réservation du quota (transaction courte)
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        profil = session.get(ProfilIdentite, profil_id)
        if investigation is None or profil is None or profil.investigation_id != investigation_id:
            return {"statut": "introuvable"}

        organisation_id = investigation.organisation_id
        plan = plan_actif(session, organisation_id)
        if not plan.possede(MODULES):
            return {"statut": "non_autorise"}

        try:
            consommer_quota(session, organisation_id, plan, "enrichissements")
        except QuotaDepasse as exc:
            return {"statut": "quota_depasse", "message": str(exc)}

        url, pseudo, domaine = profil.url, profil.pseudo_sur_le_site, profil.site_domaine

    # Étape 2 : appel réseau hors transaction (voir executer_module)
    prepare = executer_module(url, pseudo, domaine)

    # Étape 3 : enregistrement (transaction courte)
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        profil = session.get(ProfilIdentite, profil_id)
        if investigation is None or profil is None:
            return {"statut": "introuvable"}
        erreur = enregistrer_enrichissement(session, investigation, profil, prepare)
        rescorer_investigation(session, investigation)

    bus().emettre(
        TypeEvenement.PROFIL_MIS_A_JOUR, investigation_id, organisation_id,
        profil_id=profil_id, enrichi=True, erreur=erreur,
    )
    return {"statut": "ok", "erreur": erreur}
