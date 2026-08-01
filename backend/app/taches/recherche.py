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
from app.facturation.plans import MODULES, RECHERCHE_ETENDUE
from app.infra.evenements import TypeEvenement, bus
from app.modeles.enums import StatutInvestigation
from app.modeles.investigation import ExecutionRecherche, Investigation
from app.moteur.annulation import est_annulee
from app.moteur.maigret_runner import OptionsRecherche, runner
from app.services.investigation import (
    enregistrer_resultats_maigret,
    rescorer_investigation,
)
from app.taches.celery_app import celery_app

journal = logging.getLogger(__name__)


def _cloturer_annulation(
    investigation_id: str, organisation_id: str, execution_id: str | None = None
) -> dict:
    """Clôt proprement une recherche interrompue en cours d'exécution.

    Les comptes déjà enregistrés sont **conservés** : l'analyste qui arrête une
    recherche trop longue veut garder ce qu'elle a déjà trouvé, pas repartir de rien.
    Seule l'exécution en cours est marquée comme interrompue, et rien n'est mis en
    file derrière elle.
    """
    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is not None:
            # Rescorer avant de clore : les profils partiels doivent porter un score
            # cohérent, sans quoi ils s'afficheraient tous à zéro.
            rescorer_investigation(session, investigation)
            investigation.statut = StatutInvestigation.ANNULEE.value
            investigation.etape_courante = "Arrêtée à votre demande"
            investigation.terminee_le = maintenant()
        if execution_id:
            execution = session.get(ExecutionRecherche, execution_id)
            if execution is not None and execution.statut == "en_cours":
                execution.statut = "interrompue"
                execution.message_erreur = "Interrompue à la demande de l'utilisateur."

    bus().emettre(
        TypeEvenement.INVESTIGATION_TERMINEE, investigation_id, organisation_id,
        statut=StatutInvestigation.ANNULEE.value, annulee=True,
        etape="Arrêtée à votre demande",
    )
    journal.info("Investigation %s clôturée après annulation", investigation_id)
    return {"statut": "annulee"}


def _arret_demande(investigation_id: str) -> bool:
    """Point de reprise partagé par toutes les étapes du cycle.

    Consulté à l'entrée de chaque tâche et avant chaque enchaînement : une
    investigation annulée ne doit ni poursuivre son étape courante, ni mettre la
    suivante en file. Voir `app/moteur/annulation.py` pour le mécanisme.
    """
    with portee_session() as session:
        return est_annulee(investigation_id, session)


@celery_app.task(name="app.taches.recherche.lancer_investigation")
def lancer_investigation(investigation_id: str) -> dict:
    """Point d'entrée : traite tous les points de départ de l'investigation.

    L'élément principal n'est plus forcément un pseudonyme : l'analyste peut démarrer
    d'une adresse électronique, d'un téléphone, d'un compte ou d'une adresse postale.
    Les points de départ autres qu'un pseudonyme sont traités en premier : ils sont
    rapides et livrent souvent des pseudonymes supplémentaires, qui alimentent la
    recherche large qui suit au lieu d'attendre un rebond.

    Quand aucun pseudonyme n'est fourni ni découvert, la recherche large (Maigret)
    est simplement sautée : l'investigation se termine avec les seuls résultats des
    chercheurs spécialisés, plutôt que de lancer Maigret sur une valeur qui n'est pas
    un nom d'utilisateur plausible.
    """
    from app.modeles.enums import TypePointDepart
    from app.modeles.investigation import PointDepart
    from app.services.points_depart import (
        BilanPointDepart,
        enregistrer_point_depart,
        executer_chercheur,
        marquer_point_en_cours,
    )

    with portee_session() as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            journal.warning("Investigation %s introuvable", investigation_id)
            return {"statut": "introuvable"}

        # Annulation possible dès l'attente en file, avant tout traitement.
        if est_annulee(investigation_id, session):
            journal.info("Investigation %s annulée avant démarrage", investigation_id)
            return {"statut": "annulee"}

        investigation.statut = StatutInvestigation.EN_COURS.value
        investigation.demarree_le = maintenant()
        investigation.etape_courante = "Analyse des éléments fournis"
        investigation.progression = 1
        organisation_id = investigation.organisation_id

        points = (
            session.query(PointDepart)
            .filter(PointDepart.investigation_id == investigation_id)
            .order_by(PointDepart.created_at)
            .all()
        )
        # Le premier point enregistré est toujours l'élément principal (voir
        # `_enregistrer_points_depart`), quel que soit son type.
        type_principal = points[0].type if points else TypePointDepart.PSEUDO.value
        pseudo = investigation.pseudo_initial
        # Un pseudonyme est traité par la recherche large ci-dessous, jamais par
        # `traiter_point_depart` : il n'y a donc jamais lieu de le retraiter ici.
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
        # Chaque élément est un appel réseau : on rend la main entre deux.
        if _arret_demande(investigation_id):
            journal.info("Investigation %s annulée pendant les points de départ", investigation_id)
            return {"statut": "annulee", "pseudos_decouverts": pseudos_decouverts[:10]}
        # --- Étape 1 : vérifier le droit et marquer « en cours » (transaction courte) ---
        with portee_session() as session:
            investigation = session.get(Investigation, investigation_id)
            point = session.get(PointDepart, point_id)
            if investigation is None or point is None:
                continue

            plan = plan_actif(session, organisation_id)
            options = dict(investigation.options or {})
            options["extraction_activee"] = plan.possede(MODULES)

            motif_refus = marquer_point_en_cours(session, point, plan)
            type_point, valeur_point = point.type, point.valeur

        if motif_refus is not None:
            journal.info("Point de départ %s refusé : %s", type_point, motif_refus)
            bilan = BilanPointDepart(erreur=motif_refus)
        else:
            # --- Étape 2 : interroger les sources, HORS transaction ---
            # Une recherche par adresse électronique dure plusieurs minutes : garder
            # une connexion PostgreSQL ouverte pendant ce temps saturerait le pool dès
            # que quelques investigations tournent en parallèle. Même règle que pour
            # l'enrichissement (voir `executer_module`).
            resultat_chercheur = executer_chercheur(type_point, valeur_point, options)

            # --- Étape 3 : enregistrer le résultat (transaction courte) ---
            with portee_session() as session:
                investigation = session.get(Investigation, investigation_id)
                point = session.get(PointDepart, point_id)
                if investigation is None or point is None:
                    continue

                bilan = enregistrer_point_depart(session, investigation, point, resultat_chercheur)
                if bilan.erreur:
                    journal.info("Point de départ %s : %s", type_point, bilan.erreur)

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

    # --- Recherche large : sur le pseudonyme fourni, ou à défaut sur le premier
    # pseudonyme découvert par un chercheur spécialisé (partie locale d'une adresse,
    # pseudo extrait d'une URL de compte…). Si l'élément principal n'est pas un
    # pseudonyme et qu'aucun n'a été découvert, il n'y a simplement rien à chercher
    # plus largement.
    pseudo_recherche_large = (
        pseudo if type_principal == TypePointDepart.PSEUDO.value
        else (pseudos_decouverts[0] if pseudos_decouverts else None)
    )

    if pseudo_recherche_large:
        resultat = executer_recherche(
            investigation_id=investigation_id,
            pseudo=pseudo_recherche_large,
            profondeur=0,
            profil_origine_id=None,
            proposition_id=None,
        )
        # Le pseudonyme est traité par la recherche large ci-dessus, et non par
        # `traiter_point_depart` : son point de départ resterait donc « en attente »
        # dans l'interface. On y reporte l'issue réelle pour un état cohérent.
        # (Un pseudonyme simplement découvert, sans point de départ propre, n'a
        # naturellement rien à mettre à jour ici.)
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
    else:
        # Rien à chercher plus largement : on finalise directement avec les seuls
        # résultats des chercheurs spécialisés, en reprenant la même suite que
        # `executer_recherche` (corrélation, puis enrichissement ou finalisation).
        with portee_session() as session:
            investigation = session.get(Investigation, investigation_id)
            if investigation is not None:
                rescorer_investigation(session, investigation)
                investigation.etape_courante = "Analyse de corrélation"
                investigation.progression = max(investigation.progression, 75)
                plan = plan_actif(session, organisation_id)
                modules_autorises = plan.possede(MODULES)
            else:
                modules_autorises = False

        if modules_autorises:
            from app.taches.enrichissement import enrichir_investigation

            enrichir_investigation.apply_async(
                kwargs={"investigation_id": investigation_id, "profondeur": 0}, queue="enrichissement"
            )
        else:
            finaliser_investigation.apply_async(
                kwargs={"investigation_id": investigation_id}, queue="enrichissement"
            )

        resultat = {"statut": "ok", "profils_crees": 0, "profils_existants": 0, "duree": 0.0}

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

        # Une annulation pendant l'attente en file doit empêcher le départ : sans ce
        # contrôle, annuler pendant un rebond lancerait quand même la recherche suivante.
        if est_annulee(investigation_id, session):
            journal.info("Recherche « %s » annulée avant démarrage", pseudo)
            return {"statut": "annulee"}

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
        # Recherche web (DuckDuckGo) et dark web (Ahmia) : sources complémentaires,
        # ouvertes à partir du même palier que les modules d'enrichissement.
        recherche_etendue_autorisee = plan.possede(RECHERCHE_ETENDUE)
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

    # Le drapeau d'arrêt est consulté sans session : la surveillance interroge chaque
    # seconde pendant plusieurs minutes, et cette portion s'exécute volontairement
    # hors transaction (voir `annulation.est_annulee`).
    resultat = runner().lancer(
        pseudo, options_maigret, rappel=progression,
        doit_arreter=lambda: est_annulee(investigation_id),
    )

    if resultat.interrompu:
        return _cloturer_annulation(investigation_id, organisation_id, execution_id)

    # --- Sources complémentaires : recherche web et dark web ---------------
    # Même pseudonyme, hors transaction comme Maigret ci-dessus (ce sont aussi des
    # appels réseau). Un résultat trouvé ici alimente le pipeline existant
    # (corrélation, graphe) exactement comme un compte Maigret : aucun code séparé.
    if recherche_etendue_autorisee:
        from app.moteur.sources.base import cle_compte
        from app.moteur.sources.registre import sources_disponibles

        # Déduplication sur le **compte** et non sur l'adresse : Maigret renvoie
        # `www.github.com/torvalds` là où la recherche web trouve
        # `github.com/torvalds/linux`. Deux adresses, un seul compte — comparer les
        # URL entières les faisait apparaître en double dans les résultats.
        urls_connues = {cle_compte(site.url) for site in resultat.sites}
        for source in sources_disponibles():
            # Chaque source est un appel réseau distinct : point de reprise entre deux.
            if est_annulee(investigation_id):
                return _cloturer_annulation(investigation_id, organisation_id, execution_id)
            complement = source.rechercher(pseudo)
            resultat.nb_sites_total += complement.nb_resultats_bruts
            resultat.nb_sites_scannes += complement.nb_resultats_bruts
            for site in complement.sites:
                cle = cle_compte(site.url)
                if cle in urls_connues:
                    continue
                resultat.sites.append(site)
                urls_connues.add(cle)
            if complement.erreur:
                journal.info(
                    "Source « %s » indisponible pour « %s » : %s", source.nom, pseudo, complement.erreur
                )

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
        # Annulation survenue pendant l'enregistrement : les résultats viennent d'être
        # sauvegardés, mais rien ne doit être mis en file derrière.
        annulee = est_annulee(investigation_id, session)

    if annulee:
        return _cloturer_annulation(investigation_id, organisation_id, execution_id)

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

        # Une tâche de finalisation peut arriver après l'annulation (elle était déjà
        # en file). Elle ne doit pas repeindre l'investigation en « terminée » :
        # l'utilisateur l'a arrêtée, l'interface doit continuer de le dire.
        if investigation.statut == StatutInvestigation.ANNULEE.value:
            journal.info("Finalisation ignorée : investigation %s annulée", investigation_id)
            return {"statut": "annulee"}

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
