"""Définition des paliers d'abonnement.

Ce fichier ne sert qu'à **initialiser** la table `plans` (script d'amorçage).
Une fois en base, les quotas se modifient directement en base ou via l'interface
d'administration : le code métier lit toujours le plan depuis la base, jamais d'ici.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Codes de fonctionnalités ------------------------------------------------
# Utilisés par le décorateur @exiger_fonctionnalite(...) sur les endpoints.
MODULES = "modules"                        # modules de recherche spécifiques par site
PIVOT = "pivot"                            # pivot (au moins en mode supervisé)
PIVOT_AUTOMATIQUE = "pivot_automatique"    # pivot sans validation humaine
EXPORT_CSV = "export_csv"
EXPORT_PDF = "export_pdf"
API_PUBLIQUE = "api"
RETENTION_ETENDUE = "retention_etendue"
MULTI_UTILISATEURS = "multi_utilisateurs"

CODE_PLAN_GRATUIT = "free"


@dataclass
class DefinitionPlan:
    code: str
    nom_affiche: str
    description: str
    prix_mensuel_cents: int
    ordre: int
    quota_recherches_mois: int
    quota_enrichissements_mois: int
    quota_utilisateurs: int
    quota_investigations_actives: int
    profondeur_pivot_max: int
    fonctionnalites: list[str] = field(default_factory=list)


# Le palier gratuit est volontairement limité : recherche Maigret + corrélation
# de base uniquement. Les modules et le pivot — le vrai différenciateur du produit —
# sont réservés aux plans payants.
PLANS_PAR_DEFAUT: list[DefinitionPlan] = [
    DefinitionPlan(
        code=CODE_PLAN_GRATUIT,
        nom_affiche="Gratuit",
        description=(
            "Découverte : recherche de pseudonyme sur les principaux sites et corrélation "
            "de base. Modules d'enrichissement et pivot non inclus."
        ),
        prix_mensuel_cents=0,
        ordre=0,
        quota_recherches_mois=5,
        quota_enrichissements_mois=0,
        quota_utilisateurs=1,
        quota_investigations_actives=3,
        profondeur_pivot_max=0,
        fonctionnalites=[],
    ),
    DefinitionPlan(
        code="starter",
        nom_affiche="Starter",
        description=(
            "Pour l'investigateur indépendant : modules d'enrichissement par site, "
            "pivot supervisé sur un niveau, export CSV."
        ),
        prix_mensuel_cents=2900,
        ordre=1,
        quota_recherches_mois=50,
        quota_enrichissements_mois=500,
        quota_utilisateurs=3,
        quota_investigations_actives=25,
        profondeur_pivot_max=1,
        fonctionnalites=[MODULES, PIVOT, EXPORT_CSV, MULTI_UTILISATEURS],
    ),
    DefinitionPlan(
        code="pro",
        nom_affiche="Pro",
        description=(
            "Pour les cabinets et rédactions : pivot automatique jusqu'à trois niveaux, "
            "rapports PDF, accès API, rétention étendue."
        ),
        prix_mensuel_cents=9900,
        ordre=2,
        quota_recherches_mois=300,
        quota_enrichissements_mois=5000,
        quota_utilisateurs=10,
        quota_investigations_actives=200,
        profondeur_pivot_max=3,
        fonctionnalites=[
            MODULES, PIVOT, PIVOT_AUTOMATIQUE, EXPORT_CSV, EXPORT_PDF,
            API_PUBLIQUE, RETENTION_ETENDUE, MULTI_UTILISATEURS,
        ],
    ),
    DefinitionPlan(
        code="entreprise",
        nom_affiche="Entreprise",
        description=(
            "Volume élevé, équipes étendues, profondeur de pivot maximale et "
            "accompagnement dédié."
        ),
        prix_mensuel_cents=29900,
        ordre=3,
        quota_recherches_mois=2000,
        quota_enrichissements_mois=50000,
        quota_utilisateurs=50,
        quota_investigations_actives=2000,
        profondeur_pivot_max=4,
        fonctionnalites=[
            MODULES, PIVOT, PIVOT_AUTOMATIQUE, EXPORT_CSV, EXPORT_PDF,
            API_PUBLIQUE, RETENTION_ETENDUE, MULTI_UTILISATEURS,
        ],
    ),
]


def definition_par_code(code: str) -> DefinitionPlan | None:
    return next((p for p in PLANS_PAR_DEFAUT if p.code == code), None)
