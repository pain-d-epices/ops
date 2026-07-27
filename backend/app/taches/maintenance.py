"""Tâches planifiées : conformité RGPD et hygiène de la base.

La purge automatique n'est pas un confort : conserver indéfiniment des données
d'identification de tiers qui n'ont pas consenti à leur collecte est précisément ce
que le RGPD interdit. La durée de rétention est configurable par organisation.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.config import config_metier
from app.db.base import maintenant
from app.db.session import portee_session
from app.facturation.abonnements import expirer_abonnements_echus
from app.modeles.enums import ActionJournal
from app.modeles.investigation import Investigation
from app.modeles.journal import EntreeJournal
from app.modeles.organisation import Organisation
from app.services.journal import journaliser
from app.taches.celery_app import celery_app

journal = logging.getLogger(__name__)


@celery_app.task(name="app.taches.maintenance.purger_investigations_expirees")
def purger_investigations_expirees() -> dict:
    """Supprime les investigations dont la date de rétention est dépassée.

    La suppression est en cascade : profils, données extraites, signaux, nœuds et
    arêtes disparaissent avec l'investigation. Seule l'entrée de journal subsiste,
    car la traçabilité des accès relève d'une obligation distincte.
    """
    supprimees = 0
    with portee_session() as session:
        expirees = session.scalars(
            select(Investigation).where(
                Investigation.supprimer_apres.is_not(None),
                Investigation.supprimer_apres < maintenant(),
            )
        ).all()

        for investigation in expirees:
            journaliser(
                session,
                ActionJournal.PURGE_RETENTION,
                organisation_id=investigation.organisation_id,
                cible=investigation.pseudo_initial,
                investigation_id=investigation.id,
                resultat="Purge automatique au terme de la durée de rétention.",
            )
            session.delete(investigation)
            supprimees += 1

    if supprimees:
        journal.info("Purge RGPD : %d investigation(s) supprimée(s)", supprimees)
    return {"investigations_supprimees": supprimees}


@celery_app.task(name="app.taches.maintenance.purger_journaux_anciens")
def purger_journaux_anciens() -> dict:
    """Supprime les entrées de journal au-delà de la durée légale de conservation."""
    jours = int(config_metier().obtenir("retention.jours_journaux", 365))
    limite = maintenant() - timedelta(days=jours)

    with portee_session() as session:
        resultat = session.execute(delete(EntreeJournal).where(EntreeJournal.horodatage < limite))
        supprimees = resultat.rowcount or 0

    if supprimees:
        journal.info("Purge des journaux : %d entrée(s) de plus de %d jours", supprimees, jours)
    return {"entrees_supprimees": supprimees}


@celery_app.task(name="app.taches.maintenance.expirer_abonnements")
def expirer_abonnements() -> dict:
    """Bascule les abonnements dont la période est échue.

    Filet de sécurité : le plan effectif est de toute façon recalculé par date à
    chaque requête, donc un abonnement échu ne donne aucun accès même avant passage
    de cette tâche.
    """
    with portee_session() as session:
        nombre = expirer_abonnements_echus(session)
    if nombre:
        journal.info("%d abonnement(s) passé(s) en expiré", nombre)
    return {"abonnements_expires": nombre}


@celery_app.task(name="app.taches.maintenance.appliquer_retention")
def appliquer_retention(organisation_id: str) -> dict:
    """Recalcule les dates de purge des investigations d'une organisation.

    Appelée après modification de la durée de rétention dans les préférences.
    """
    defaut = int(config_metier().obtenir("retention.jours_defaut", 90))
    mises_a_jour = 0

    with portee_session() as session:
        organisation = session.get(Organisation, organisation_id)
        if organisation is None:
            return {"statut": "introuvable"}

        jours = organisation.retention_jours or defaut
        investigations = session.scalars(
            select(Investigation).where(Investigation.organisation_id == organisation_id)
        ).all()

        for investigation in investigations:
            base = investigation.terminee_le or investigation.created_at
            if base is None:
                continue
            investigation.supprimer_apres = base + timedelta(days=jours)
            mises_a_jour += 1

    return {"investigations_mises_a_jour": mises_a_jour, "jours": jours}
