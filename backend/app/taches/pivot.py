"""Tâches de pivot : détection des rebonds possibles et relance contrôlée.

En mode automatique, les pivots retenus déclenchent directement de nouvelles
recherches. En mode supervisé, ils sont enregistrés comme propositions et attendent
la validation d'un analyste — aucune requête n'est émise entre-temps.
"""

from __future__ import annotations

import logging

from app.config import config_metier
from app.db.session import portee_session
from app.facturation.abonnements import plan_actif
from app.facturation.garde import pivot_disponible
from app.facturation.quotas import QuotaDepasse, consommer_quota
from app.infra.evenements import TypeEvenement, bus
from app.modeles.enums import TypeDonnee, TypeNoeud
from app.modeles.investigation import Investigation, PropositionPivot
from app.modeles.organisation import Organisation
from app.moteur.annulation import est_annulee
from app.moteur.pivot.detecteur import ACTION_ENRICHISSEMENT, ACTION_RECHERCHE, DetecteurPivot
from app.moteur.pivot.orchestrateur import OrchestrateurPivot
from app.services.investigation import (
    collecter_donnees_pivotables,
    marquer_donnees_pivotees,
    relier_pivot_dans_graphe,
)
from app.taches.celery_app import celery_app

journal = logging.getLogger(__name__)

# Type de nœud à créer dans le graphe selon la nature du pivot
NOEUD_PAR_TYPE_PIVOT = {
    TypeDonnee.PSEUDO_ALT.value: TypeNoeud.PSEUDO_ALT,
    TypeDonnee.EMAIL.value: TypeNoeud.EMAIL,
    TypeDonnee.NOM_REEL.value: TypeNoeud.NOM,
    TypeDonnee.LIEN_EXTERNE.value: TypeNoeud.LIEN,
}


@celery_app.task(name="app.taches.pivot.detecter_et_pivoter")
def detecter_et_pivoter(investigation_id: str, profondeur_source: int = 0) -> dict:
    """Détecte les pivots possibles à ce niveau et applique la politique de l'organisation."""
    score_minimal = int(config_metier().obtenir("correlation.score_minimal_pivot", 50))
    a_lancer: list[dict] = []
    en_attente = 0

    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            return {"statut": "introuvable"}

        # Le rebond est l'étape la plus coûteuse (il relance des recherches
        # complètes) : ne jamais l'engager sur une investigation arrêtée.
        if est_annulee(investigation_id, session):
            return {"statut": "annulee"}

        organisation = session.get(Organisation, investigation.organisation_id)
        plan = plan_actif(session, investigation.organisation_id)
        organisation_id = investigation.organisation_id

        if organisation is None or not pivot_disponible(plan):
            _terminer(investigation_id)
            return {"statut": "non_autorise"}

        orchestrateur = OrchestrateurPivot(session, investigation, organisation, plan)
        detecteur = DetecteurPivot(valeurs_deja_explorees=orchestrateur.valeurs_deja_explorees())

        candidates = collecter_donnees_pivotables(session, investigation, score_minimal)
        pivots = detecteur.detecter(candidates)

        if not pivots:
            journal.info("Aucun pivot exploitable pour l'investigation %s", investigation_id)
            _terminer(investigation_id)
            return {"statut": "aucun_pivot"}

        decision = orchestrateur.arbitrer(pivots, profondeur_source)

        # Toute proposition retenue apparaît dans le graphe, même si son exécution
        # attend une validation : l'analyste voit ce qui a été découvert avant de décider.
        for proposition in decision.a_executer + decision.en_attente:
            type_noeud = NOEUD_PAR_TYPE_PIVOT.get(proposition.type_pivot, TypeNoeud.PSEUDO_ALT)
            relier_pivot_dans_graphe(
                session, investigation, proposition.profil_source_id,
                proposition.valeur, type_noeud, proposition.libelle,
            )

        marquer_donnees_pivotees(
            session,
            [p.donnee_source_id for p in decision.a_executer + decision.en_attente if p.donnee_source_id],
        )

        a_lancer = [
            {
                "id": p.id,
                "valeur": p.valeur,
                "action": p.action,
                "profondeur_cible": p.profondeur_cible,
                "profil_source_id": p.profil_source_id,
                "libelle": p.libelle,
            }
            for p in decision.a_executer
        ]
        en_attente = len(decision.en_attente)
        ignores = [{"valeur": p.valeur, "raison": raison} for p, raison in decision.ignores]

    for proposition in a_lancer:
        bus().emettre(
            TypeEvenement.PIVOT_PROPOSE, investigation_id, organisation_id,
            proposition_id=proposition["id"], libelle=proposition["libelle"], automatique=True,
        )
    if en_attente:
        bus().emettre(
            TypeEvenement.PIVOT_PROPOSE, investigation_id, organisation_id,
            en_attente=en_attente, automatique=False,
        )

    if not a_lancer:
        # Mode supervisé : l'investigation est close pour l'instant. Elle reprendra
        # si l'analyste valide une proposition.
        _terminer(investigation_id)
        return {"statut": "en_attente_validation", "propositions": en_attente, "ignores": ignores}

    for proposition in a_lancer:
        executer_proposition_pivot.apply_async(
            kwargs={"investigation_id": investigation_id, "proposition_id": proposition["id"]},
            queue="pivot",
        )

    return {"statut": "ok", "lances": len(a_lancer), "en_attente": en_attente, "ignores": ignores}


@celery_app.task(name="app.taches.pivot.executer_proposition_pivot")
def executer_proposition_pivot(investigation_id: str, proposition_id: str) -> dict:
    """Exécute un pivot validé (automatiquement ou par un analyste)."""
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        proposition = session.get(PropositionPivot, proposition_id)
        if investigation is None or proposition is None:
            return {"statut": "introuvable"}
        if proposition.investigation_id != investigation_id:
            # Ne jamais exécuter une proposition appartenant à une autre investigation
            return {"statut": "incoherent"}

        # Un rebond validé puis annulé ne doit pas consommer de quota ni partir.
        if est_annulee(investigation_id, session):
            return {"statut": "annulee"}

        organisation_id = investigation.organisation_id
        plan = plan_actif(session, organisation_id)
        if not pivot_disponible(plan):
            return {"statut": "non_autorise"}

        # Un pivot consomme le quota de recherches : c'est une recherche complète.
        try:
            consommer_quota(session, organisation_id, plan, "pivots")
        except QuotaDepasse as exc:
            bus().emettre(
                TypeEvenement.ETAPE, investigation_id, organisation_id,
                etape=str(exc), quota_epuise=True,
            )
            _terminer(investigation_id)
            return {"statut": "quota_depasse", "message": str(exc)}

        action = proposition.action
        valeur = proposition.valeur
        profondeur = proposition.profondeur_cible
        profil_source_id = proposition.profil_source_id

    if action == ACTION_RECHERCHE:
        from app.taches.recherche import executer_recherche

        executer_recherche.apply_async(
            kwargs={
                "investigation_id": investigation_id,
                "pseudo": valeur,
                "profondeur": profondeur,
                "profil_origine_id": profil_source_id,
                "proposition_id": proposition_id,
            },
            queue="recherche",
        )
        return {"statut": "recherche_lancee", "pseudo": valeur}

    if action == ACTION_ENRICHISSEMENT:
        # Le lien pointe vers un site couvert par un module : inutile de relancer
        # Maigret, on interroge directement le site concerné.
        enrichir_lien_direct.apply_async(
            kwargs={
                "investigation_id": investigation_id,
                "proposition_id": proposition_id,
            },
            queue="enrichissement",
        )
        return {"statut": "enrichissement_lance", "url": valeur}

    return {"statut": "action_inconnue", "action": action}


@celery_app.task(name="app.taches.pivot.enrichir_lien_direct")
def enrichir_lien_direct(investigation_id: str, proposition_id: str) -> dict:
    """Interroge directement un site à partir d'un lien découvert dans un profil."""
    from app.modeles.enums import StatutMaigret
    from app.moteur.maigret_runner import ResultatRecherche, ResultatSite
    from app.services.investigation import (
        domaine_de,
        enregistrer_resultats_maigret,
        rescorer_investigation,
    )

    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        proposition = session.get(PropositionPivot, proposition_id)
        if investigation is None or proposition is None:
            return {"statut": "introuvable"}

        if est_annulee(investigation_id, session):
            return {"statut": "annulee"}

        from app.modeles.investigation import ExecutionRecherche
        from app.modules.registre import module_pour_domaine

        domaine = domaine_de(proposition.valeur)
        module = module_pour_domaine(domaine)
        if module is None:
            return {"statut": "aucun_module"}

        pseudo = module.pseudo_depuis_url(proposition.valeur) or proposition.valeur

        execution = ExecutionRecherche(
            investigation_id=investigation.id,
            organisation_id=investigation.organisation_id,
            pseudo_recherche=pseudo,
            profondeur=proposition.profondeur_cible,
            declenchee_par_profil_id=proposition.profil_source_id,
            statut="terminee",
            nb_sites_scannes=1,
            nb_sites_total=1,
        )
        session.add(execution)
        session.flush()

        # On fabrique un résultat Maigret équivalent pour réutiliser tout le chemin
        # d'enregistrement habituel (profil, graphe, corrélation) sans le dupliquer.
        resultat = ResultatRecherche(
            pseudo=pseudo,
            sites=[
                ResultatSite(
                    site_nom=module.libelle or module.nom,
                    site_domaine=domaine,
                    url=proposition.valeur,
                    pseudo=pseudo,
                    statut=StatutMaigret.TROUVE,
                    brut={"origine": "pivot_lien_direct", "proposition_id": proposition_id},
                )
            ],
            nb_sites_total=1,
            nb_sites_scannes=1,
        )

        enregistrer_resultats_maigret(
            session, investigation, execution, resultat,
            profondeur=proposition.profondeur_cible,
            profil_origine_id=proposition.profil_source_id,
        )
        proposition.execution_id = execution.id
        rescorer_investigation(session, investigation)
        profondeur = proposition.profondeur_cible

    from app.taches.enrichissement import enrichir_investigation

    enrichir_investigation.apply_async(
        kwargs={"investigation_id": investigation_id, "profondeur": profondeur},
        queue="enrichissement",
    )
    return {"statut": "ok"}


def _terminer(investigation_id: str) -> None:
    from app.taches.recherche import finaliser_investigation

    finaliser_investigation.apply_async(
        kwargs={"investigation_id": investigation_id}, queue="enrichissement"
    )
