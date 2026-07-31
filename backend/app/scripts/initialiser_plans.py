"""Amorçage des paliers d'abonnement en base.

Idempotent : relancer le script met à jour les plans existants sans créer de doublon.
Exécuté automatiquement au démarrage du conteneur API (voir docker-compose.yml).

    python -m app.scripts.initialiser_plans
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import parametres
from app.db.session import portee_session
from app.facturation.plans import PLANS_PAR_DEFAUT
from app.modeles.facturation import Plan

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
journal = logging.getLogger("initialiser_plans")


def initialiser_plans() -> None:
    correspondance_stripe = {
        code_plan: id_prix
        for id_prix, code_plan in parametres().correspondance_prix_stripe.items()
    }

    with portee_session() as session:
        for definition in PLANS_PAR_DEFAUT:
            plan = session.scalar(select(Plan).where(Plan.code == definition.code))
            if plan is None:
                plan = Plan(code=definition.code)
                session.add(plan)
                journal.info("Création du plan « %s »", definition.code)
            else:
                journal.info("Mise à jour du plan « %s »", definition.code)

            plan.nom_affiche = definition.nom_affiche
            plan.description = definition.description
            plan.prix_mensuel_cents = definition.prix_mensuel_cents
            plan.ordre = definition.ordre
            plan.quota_recherches_mois = definition.quota_recherches_mois
            plan.quota_enrichissements_mois = definition.quota_enrichissements_mois
            plan.quota_utilisateurs = definition.quota_utilisateurs
            plan.quota_investigations_actives = definition.quota_investigations_actives
            plan.profondeur_pivot_max = definition.profondeur_pivot_max
            plan.max_points_depart = definition.max_points_depart
            plan.max_sites_analyses = definition.max_sites_analyses
            plan.fonctionnalites = list(definition.fonctionnalites)
            plan.actif = True
            # L'identifiant de prix Stripe vient du .env : il diffère entre
            # l'environnement de test et la production.
            plan.stripe_price_id = correspondance_stripe.get(definition.code)

    journal.info("Plans initialisés (%d paliers).", len(PLANS_PAR_DEFAUT))


if __name__ == "__main__":
    initialiser_plans()
