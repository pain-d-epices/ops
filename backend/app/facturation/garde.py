"""Gardes de fonctionnalité et de quota.

Ces vérifications s'appliquent **côté serveur** et sont dupliquées dans les tâches
Celery : masquer un bouton dans le frontend n'est pas une protection, et un abonnement
peut expirer entre le lancement d'une tâche et son exécution.
"""

from __future__ import annotations

from app.facturation.plans import PIVOT, PIVOT_AUTOMATIQUE, SITES_SENSIBLES
from app.modeles.enums import ModePivot
from app.modeles.facturation import Plan
from app.modeles.organisation import Organisation

#: Taille de la base de sites de Maigret, arrondie au millier supérieur. Sert de
#: borne concrète lorsqu'un plan annonce « sans limite » : au-delà, il n'y a plus
#: de site à interroger.
TOTALITE_DES_SITES = 3000

#: Plancher : en dessous, une recherche n'a plus d'intérêt.
MINIMUM_SITES = 10


class FonctionnaliteIndisponible(Exception):
    """La fonctionnalité demandée n'est pas incluse dans le plan actif."""

    def __init__(self, fonctionnalite: str, plan: Plan):
        self.fonctionnalite = fonctionnalite
        self.code_plan = plan.code
        self.nom_plan = plan.nom_affiche
        super().__init__(
            f"La fonctionnalité « {fonctionnalite} » n'est pas incluse dans le plan "
            f"{plan.nom_affiche}. Passez à un palier supérieur pour y accéder."
        )


def exiger_fonctionnalite(plan: Plan, fonctionnalite: str) -> None:
    """Lève FonctionnaliteIndisponible si le plan ne couvre pas la fonctionnalité."""
    if not plan.possede(fonctionnalite):
        raise FonctionnaliteIndisponible(fonctionnalite, plan)


def profondeur_pivot_autorisee(plan: Plan, organisation: Organisation, demandee: int | None = None) -> int:
    """Profondeur de pivot réellement appliquée.

    Trois bornes successives, dans cet ordre :
      1. ce que demande l'utilisateur,
      2. ce que permet son plan,
      3. le plafond dur du serveur (config.yaml), qu'aucun plan ne peut dépasser.

    La valeur envoyée par le frontend est ainsi toujours réduite côté serveur : un
    client qui modifierait la requête ne peut pas s'octroyer une profondeur supérieure.
    """
    from app.config import config_metier

    plafond_serveur = int(config_metier().obtenir("pivot.profondeur_plafond_serveur", 4))
    if demandee is None:
        demandee = organisation.profondeur_pivot_souhaitee
    return max(0, min(int(demandee), plan.profondeur_pivot_max, plafond_serveur))


def mode_pivot_effectif(plan: Plan, organisation: Organisation, demande: str | None = None) -> str:
    """Mode de pivot réellement appliqué, en tenant compte du plan.

    Une organisation configurée en mode automatique mais dont le plan ne l'inclut pas
    est ramenée au mode supervisé plutôt que refusée : le pivot reste utilisable,
    simplement avec une validation manuelle.
    """
    souhaite = demande or organisation.mode_pivot
    if souhaite == ModePivot.AUTOMATIQUE.value and not plan.possede(PIVOT_AUTOMATIQUE):
        return ModePivot.SUPERVISE.value
    return souhaite


def pivot_disponible(plan: Plan) -> bool:
    return plan.possede(PIVOT) and plan.profondeur_pivot_max > 0


def sites_analysables(plan: Plan, demandes: int | None = None) -> int:
    """Nombre de sites réellement analysés par une recherche large.

    Même principe que `profondeur_pivot_autorisee` : ce que demande l'utilisateur est
    borné par son plan, jamais l'inverse. Un plan à `max_sites_analyses` nul signifie
    « recherche maximale », donc la totalité de la base.

    Sans demande explicite, on retient la valeur par défaut du serveur — elle-même
    ramenée au plafond du plan, sans quoi le palier gratuit obtiendrait 500 sites en
    ne précisant rien.
    """
    from app.config import config_metier

    if demandes is None:
        demandes = int(config_metier().obtenir("maigret.top_sites", 500))
    plafond_plan = plan.max_sites_analyses or TOTALITE_DES_SITES
    return max(MINIMUM_SITES, min(int(demandes), plafond_plan, TOTALITE_DES_SITES))


def sites_sensibles_autorises(plan: Plan) -> bool:
    """Le plan donne-t-il accès aux comptes trouvés sur des sites à caractère sexuel ?

    Le palier gratuit en est exclu : ces résultats sont écartés à la lecture du
    rapport de Maigret, donc jamais enregistrés (voir `maigret_runner`).
    """
    return plan.possede(SITES_SENSIBLES)
