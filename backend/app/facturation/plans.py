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
#: Accès machine à machine (clé d'API), réservé au palier Entreprise.
#: ATTENTION — **rien n'implémente encore cette fonctionnalité** : ni modèle de clé,
#: ni authentification par clé, ni endpoint qui la vérifie. Le code n'est déclaré ici
#: que pour préparer le terrain. Ne pas l'afficher comme disponible dans la grille
#: commerciale avant de l'avoir construite. Voir docs/acces-api.md.
API_PUBLIQUE = "api"
RETENTION_ETENDUE = "retention_etendue"
MULTI_UTILISATEURS = "multi_utilisateurs"
#: Accès aux comptes trouvés sur des sites à caractère sexuel. Absent du palier
#: gratuit : ces résultats sont filtrés avant enregistrement (voir `maigret_runner`).
SITES_SENSIBLES = "sites_sensibles"

# --- Types de recherche (disponibles dès le palier Starter) ------------------
# Ces codes correspondent au champ `fonctionnalite_requise` des chercheurs : le
# rapprochement est automatique, ajouter un chercheur ne demande pas de toucher ici.
RECHERCHE_DEPUIS_COMPTE = "recherche_depuis_compte"
RECHERCHE_EMAIL = "recherche_email"
RECHERCHE_TELEPHONE = "recherche_telephone"
RECHERCHE_ADRESSE = "recherche_adresse"
RECHERCHE_MULTI_CRITERES = "recherche_multi_criteres"

#: Types de recherche ouverts à tous les paliers payants
RECHERCHES_SPECIALISEES = [
    RECHERCHE_DEPUIS_COMPTE,
    RECHERCHE_EMAIL,
    RECHERCHE_TELEPHONE,
    RECHERCHE_ADRESSE,
    RECHERCHE_MULTI_CRITERES,
]

CODE_PLAN_GRATUIT = "free"

#: Sens de `max_sites_analyses` et `max_points_depart` : 0 signifie « sans limite ».
SANS_LIMITE = 0


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
    #: nombre de points de départ acceptés simultanément dans une même investigation
    max_points_depart: int = 1
    #: nombre maximal de sites analysables par recherche large ; 0 = sans limite
    max_sites_analyses: int = 200


# Ce qui distingue les paliers, dans l'ordre d'importance commerciale :
#
#   |                      | Gratuit      | Starter | Pro      | Entreprise |
#   |----------------------|--------------|---------|----------|------------|
#   | Recherches par mois  | 15           | 100     | 500      | 2500       |
#   | Rebonds (pivot)      | 0            | 2       | 5        | 10         |
#   | Sites par recherche  | 200          | 1000    | tous     | tous       |
#   | Types de recherche   | pseudo, mail | tous    | tous     | tous       |
#   | Sites sensibles      | non          | oui     | oui      | oui        |
#
# Le palier gratuit sert la découverte : il permet de juger la qualité de la
# corrélation sur un pseudonyme ou une adresse, sans ouvrir ce qui fait la valeur
# du produit (modules d'enrichissement, rebond, volume, couverture complète).
PLANS_PAR_DEFAUT: list[DefinitionPlan] = [
    DefinitionPlan(
        code=CODE_PLAN_GRATUIT,
        nom_affiche="Gratuit",
        description=(
            "Découverte : recherche par pseudonyme ou adresse électronique sur les "
            "200 principaux sites, et corrélation de base. Modules d'enrichissement "
            "et rebond non inclus."
        ),
        prix_mensuel_cents=0,
        ordre=0,
        quota_recherches_mois=15,
        quota_enrichissements_mois=0,
        quota_utilisateurs=1,
        quota_investigations_actives=3,
        profondeur_pivot_max=0,
        # Seule la recherche par adresse électronique est ouverte en plus du
        # pseudonyme, ce dernier n'exigeant aucune fonctionnalité (c'est la base).
        # Téléphone, adresse postale, départ depuis un compte et combinaison de
        # plusieurs éléments restent réservés aux paliers payants.
        fonctionnalites=[RECHERCHE_EMAIL],
        max_points_depart=1,
        max_sites_analyses=200,
    ),
    DefinitionPlan(
        code="starter",
        nom_affiche="Starter",
        description=(
            "Pour l'investigateur indépendant : tous les types de recherche, tous les "
            "modules d'enrichissement, rebond supervisé sur deux niveaux, jusqu'à "
            "1000 sites par recherche, export CSV."
        ),
        prix_mensuel_cents=2900,
        ordre=1,
        quota_recherches_mois=100,
        quota_enrichissements_mois=500,
        quota_utilisateurs=3,
        quota_investigations_actives=25,
        profondeur_pivot_max=2,
        # Tous les types de recherche sont ouverts dès ce palier : ce qui distingue
        # les paliers supérieurs, c'est le volume, la profondeur de rebond et la
        # couverture en nombre de sites, pas l'accès aux types de recherche.
        fonctionnalites=[
            MODULES, PIVOT, EXPORT_CSV, MULTI_UTILISATEURS, SITES_SENSIBLES,
            *RECHERCHES_SPECIALISEES,
        ],
        max_points_depart=2,
        max_sites_analyses=1000,
    ),
    DefinitionPlan(
        code="pro",
        nom_affiche="Pro",
        description=(
            "Pour les cabinets et rédactions : recherche sur la totalité des sites, "
            "rebond automatique jusqu'à cinq niveaux, rapports PDF, rétention "
            "étendue."
        ),
        prix_mensuel_cents=9900,
        ordre=2,
        quota_recherches_mois=500,
        quota_enrichissements_mois=5000,
        quota_utilisateurs=10,
        quota_investigations_actives=200,
        profondeur_pivot_max=5,
        # Pas d'accès API à ce palier : l'usage machine à machine est le vecteur le
        # plus direct d'automatisation de masse, donc réservé au palier où le client
        # est identifié et accompagné.
        fonctionnalites=[
            MODULES, PIVOT, PIVOT_AUTOMATIQUE, EXPORT_CSV, EXPORT_PDF,
            RETENTION_ETENDUE, MULTI_UTILISATEURS, SITES_SENSIBLES,
            *RECHERCHES_SPECIALISEES,
        ],
        max_points_depart=5,
        # Recherche maximale : aucune borne sur le nombre de sites analysés.
        max_sites_analyses=SANS_LIMITE,
    ),
    DefinitionPlan(
        code="entreprise",
        nom_affiche="Entreprise",
        description=(
            "Volume élevé, équipes étendues, rebond jusqu'à dix niveaux et "
            "accompagnement dédié."
        ),
        prix_mensuel_cents=29900,
        ordre=3,
        quota_recherches_mois=2500,
        quota_enrichissements_mois=50000,
        quota_utilisateurs=50,
        quota_investigations_actives=2000,
        profondeur_pivot_max=10,
        # Seul palier ouvrant l'accès API — et encore : la fonctionnalité n'est pas
        # construite (voir le commentaire d'`API_PUBLIQUE` plus haut).
        fonctionnalites=[
            MODULES, PIVOT, PIVOT_AUTOMATIQUE, EXPORT_CSV, EXPORT_PDF,
            API_PUBLIQUE, RETENTION_ETENDUE, MULTI_UTILISATEURS, SITES_SENSIBLES,
            *RECHERCHES_SPECIALISEES,
        ],
        # 0 = pas de limite : les investigations complexes de ce palier peuvent
        # partir d'autant d'éléments que nécessaire.
        max_points_depart=SANS_LIMITE,
        max_sites_analyses=SANS_LIMITE,
    ),
]


def definition_par_code(code: str) -> DefinitionPlan | None:
    return next((p for p in PLANS_PAR_DEFAUT if p.code == code), None)
