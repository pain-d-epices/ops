"""Tâches de recherche : exécution de Maigret et enchaînement du cycle d'investigation.

Cycle complet d'un niveau :
    Maigret -> enregistrement des profils -> corrélation -> enrichissement (si le plan
    l'inclut) -> nouvelle corrélation -> détection des pivots -> relance éventuelle.

Chaque étape revérifie le plan de l'organisation : un abonnement peut expirer entre
la mise en file d'une tâche et son exécution effective.
"""

from __future__ import annotations

import logging

from app.db.base import maintenant
from app.db.session import portee_session
from app.facturation.abonnements import plan_actif
from app.facturation.plans import MODULES
from app.infra.evenements import TypeEvenement, bus
from app.modeles.enums import StatutInvestigation
from app.modeles.investigation import ExecutionRecherche, Investigation
from app.moteur.maigret_runner import OptionsRecherche, runner
from app.services.investigation import (
    enregistrer_resultats_maigret,
    rescorer_investigation,
)
from app.taches.celery_app import celery_app

journal = logging.getLogger(__name__)


@celery_app.task(name="app.taches.recherche.lancer_investigation")
def lancer_investigation(investigation_id: str) -> dict:
    """Point d'entrée : traite tous les points de départ de l'investigation.

    Les points de départ autres que le pseudonyme (adresse électronique, téléphone,
    compte, adresse postale) sont traités en premier : ils sont rapides et livrent
    souvent des pseudonymes supplémentaires, qui enrichissent la recherche large qui
    suit au lieu d'attendre un rebond.
    """
    from app.modeles.enums import TypePointDepart
    from app.modeles.investigation import PointDepart
    from app.services.points_depart import traiter_point_depart

    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            journal.warning("Investigation %s introuvable", investigation_id)
            return {"statut": "introuvable"}

        investigation.statut = StatutInvestigation.EN_COURS.value
        investigation.demarree_le = maintenant()
        investigation.etape_courante = "Analyse des éléments fournis"
        investigation.progression = 1
        pseudo = investigation.pseudo_initial
        organisation_id = investigation.organisation_id

        points = (
            session.query(PointDepart)
            .filter(PointDepart.investigation_id == investigation_id)
            .order_by(PointDepart.created_at)
            .all()
        )
        # Le pseudonyme principal est traité à part, par la recherche large ci-dessous
        points_specialises = [
            p.id for p in points if p.type != TypePointDepart.PSEUDO.value
        ]

    bus().emettre(
        TypeEvenement.ETAPE, investigation_id, organisation_id,
        etape="Analyse des éléments fournis", progression=1,
    )

    # --- Points de départ spécialisés ---
    pseudos_decouverts: list[str] = []
    for point_id in points_specialises:
        with portee_session() as session:
            investigation = session.get(Investigation, investigation_id)
            point = session.get(PointDepart, point_id)
            if investigation is None or point is None:
                continue

            plan = plan_actif(session, organisation_id)
            options = dict(investigation.options or {})
            options["extraction_activee"] = plan.possede(MODULES)

            bilan = traiter_point_depart(session, investigation, point, plan, options)
            if bilan.erreur:
                journal.info("Point de départ %s : %s", point.type, bilan.erreur)

            # Un pseudonyme découvert (partie locale d'une adresse, pseudo extrait
            # d'une URL de compte) alimente la recherche large qui suit.
            from app.modeles.enums import TypeDonnee
            from app.modeles.investigation import DonneeExtraite

            for donnee in (
                session.query(DonneeExtraite)
                .filter(
                    DonneeExtraite.investigation_id == investigation_id,
                    DonneeExtraite.type == TypeDonnee.PSEUDO_ALT.value,
                )
                .all()
            ):
                if donnee.valeur not in pseudos_decouverts:
                    pseudos_decouverts.append(donnee.valeur)

        bus().emettre(
            TypeEvenement.ETAPE, investigation_id, organisation_id,
            etape=f"Élément analysé : {bilan.comptes_trouves} compte(s) trouvé(s)",
            progression=5,
        )

    # --- Recherche large sur le pseudonyme principal ---
    resultat = executer_recherche(
        investigation_id=investigation_id,
        pseudo=pseudo,
        profondeur=0,
        profil_origine_id=None,
        proposition_id=None,
    )
    # Le pseudonyme principal est traité par la recherche large ci-dessus, et non par
    # `traiter_point_depart` : son point de départ resterait donc « en attente » dans
    # l'interface. On y reporte l'issue réelle pour que tous les éléments fournis
    # affichent un état cohérent.
    with portee_session() as session:
        point_pseudo = (
            session.query(PointDepart)
            .filter(
                PointDepart.investigation_id == investigation_id,
                PointDepart.type == TypePointDepart.PSEUDO.value,
            )
            .order_by(PointDepart.created_at)
            .first()
        )
        if point_pseudo is not None:
            reussie = resultat.get("statut") == "ok"
            point_pseudo.statut = "termine" if reussie else "erreur"
            point_pseudo.nb_comptes_trouves = int(resultat.get("profils_crees") or 0) + int(
                resultat.get("profils_existants") or 0
            )
            point_pseudo.message_erreur = (
                None if reussie else str(resultat.get("message") or "Recherche interrompue.")[:500]
            )
            point_pseudo.traite_le = maintenant()

    resultat["points_depart_traites"] = len(points_specialises)
    resultat["pseudos_decouverts"] = pseudos_decouverts[:10]
    return resultat


@celery_app.task(name="app.taches.recherche.executer_recherche")
def executer_recherche(
    investigation_id: str,
    pseudo: str,
    profondeur: int = 0,
    profil_origine_id: str | None = None,
    proposition_id: str | None = None,
) -> dict:
    """Exécute Maigret pour un pseudonyme, à un niveau de profondeur donné."""
    # --- Préparation : création de la trace d'exécution -------------------
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            return {"statut": "introuvable"}

        organisation_id = investigation.organisation_id
        plan = plan_actif(session, organisation_id)
        options_investigation = investigation.options or {}

        execution = ExecutionRecherche(
            investigation_id=investigation.id,
            organisation_id=organisation_id,
            pseudo_recherche=pseudo,
            profondeur=profondeur,
            declenchee_par_profil_id=profil_origine_id,
            statut="en_cours",
        )
        session.add(execution)
        session.flush()
        execution_id = execution.id

        # L'extraction d'informations par Maigret recouvre la fonctionnalité payante
        # « modules » : elle est désactivée pour les organisations en plan gratuit.
        extraction_autorisee = plan.possede(MODULES)
        options_maigret = OptionsRecherche.depuis_config(
            top_sites=options_investigation.get("top_sites"),
            sites_exclus=options_investigation.get("sites_exclus") or [],
            extraction_activee=extraction_autorisee,
        )

    # --- Exécution de Maigret (hors transaction : c'est long) -------------
    def progression(scannes: int, total: int, message: str) -> None:
        pourcentage = min(70, int(scannes * 70 / max(total, 1)))
        bus().emettre(
            TypeEvenement.PROGRESSION, investigation_id, organisation_id,
            progression=pourcentage, message=message, pseudo=pseudo, profondeur=profondeur,
        )

    resultat = runner().lancer(pseudo, options_maigret, rappel=progression)

    # --- Enregistrement ---------------------------------------------------
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        execution = session.get(ExecutionRecherche, execution_id)
        if investigation is None or execution is None:
            return {"statut": "introuvable"}

        execution.nb_sites_scannes = resultat.nb_sites_scannes
        execution.nb_sites_total = resultat.nb_sites_total
        execution.duree_secondes = resultat.duree_secondes
        execution.resultat_brut = {"sites": [s.brut for s in resultat.comptes_trouves]}

        if not resultat.reussie and not resultat.comptes_trouves:
            execution.statut = "erreur"
            execution.message_erreur = resultat.erreur
            investigation.statut = StatutInvestigation.ERREUR.value
            investigation.message_erreur = resultat.erreur
            investigation.terminee_le = maintenant()
            bus().emettre(
                TypeEvenement.ERREUR, investigation_id, organisation_id, message=resultat.erreur
            )
            return {"statut": "erreur", "message": resultat.erreur}

        execution.statut = "terminee"
        # Un résultat partiel (délai dépassé) reste exploitable : on le signale sans
        # jeter les comptes déjà trouvés.
        if resultat.erreur:
            execution.message_erreur = resultat.erreur

        bilan = enregistrer_resultats_maigret(
            session, investigation, execution, resultat,
            profondeur=profondeur, profil_origine_id=profil_origine_id,
        )
        investigation.nb_recherches_effectuees += 1
        investigation.etape_courante = "Analyse de corrélation"
        investigation.progression = max(investigation.progression, 75)
        rescorer_investigation(session, investigation)

        if proposition_id:
            from app.modeles.investigation import PropositionPivot

            proposition = session.get(PropositionPivot, proposition_id)
            if proposition is not None:
                proposition.execution_id = execution_id

        plan = plan_actif(session, organisation_id)
        modules_autorises = plan.possede(MODULES)

    bus().emettre(
        TypeEvenement.RECHERCHE_TERMINEE, investigation_id, organisation_id,
        pseudo=pseudo, profondeur=profondeur,
        profils_crees=bilan.profils_crees, progression=75,
    )

    # --- Suite du cycle ---------------------------------------------------
    if modules_autorises:
        from app.taches.enrichissement import enrichir_investigation

        enrichir_investigation.apply_async(
            kwargs={"investigation_id": investigation_id, "profondeur": profondeur}, queue="enrichissement"
        )
    else:
        # Palier gratuit : ni enrichissement ni pivot, l'investigation s'arrête ici.
        finaliser_investigation.apply_async(
            kwargs={"investigation_id": investigation_id}, queue="enrichissement"
        )

    return {
        "statut": "ok",
        "profils_crees": bilan.profils_crees,
        "profils_existants": bilan.profils_existants,
        "duree": resultat.duree_secondes,
    }


@celery_app.task(name="app.taches.recherche.finaliser_investigation")
def finaliser_investigation(investigation_id: str) -> dict:
    """Clôt l'investigation et notifie le frontend."""
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            return {"statut": "introuvable"}

        rescorer_investigation(session, investigation)
        investigation.statut = StatutInvestigation.TERMINEE.value
        investigation.progression = 100
        investigation.etape_courante = "Terminée"
        investigation.terminee_le = maintenant()
        organisation_id = investigation.organisation_id
        resume = {
            "profils_trouves": investigation.nb_profils_trouves,
            "profils_confirmes": investigation.nb_profils_confirmes,
            "recherches": investigation.nb_recherches_effectuees,
        }

    bus().emettre(
        TypeEvenement.INVESTIGATION_TERMINEE, investigation_id, organisation_id,
        progression=100, **resume,
    )
    return {"statut": "terminee", **resume}
