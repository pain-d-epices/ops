"""Orchestration du pivot : décide quoi relancer, jusqu'où, et sous quel contrôle.

Quatre garde-fous cumulatifs, dans cet ordre :
  1. la fonctionnalité « pivot » doit être incluse dans le plan de l'organisation ;
  2. la profondeur est bornée par le plan, lui-même borné par le plafond serveur ;
  3. le nombre total de recherches déclenchées par investigation est plafonné ;
  4. les valeurs déjà explorées sont mémorisées, ce qui interdit les cycles.

Sans ces limites, une seule investigation pourrait générer des milliers de requêtes
sortantes — coût d'infrastructure incontrôlé et bannissement assuré des sites cibles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import config_metier
from app.db.base import maintenant
from app.facturation.garde import mode_pivot_effectif, pivot_disponible, profondeur_pivot_autorisee
from app.modeles.enums import ModePivot, StatutPropositionPivot
from app.modeles.facturation import Plan
from app.modeles.investigation import Investigation, PropositionPivot
from app.modeles.organisation import Organisation
from app.moteur.pivot.detecteur import Pivot

journal = logging.getLogger(__name__)


@dataclass
class DecisionPivot:
    """Résultat de l'arbitrage pour un lot de pivots détectés."""

    a_executer: list[PropositionPivot]      # à lancer immédiatement (mode automatique)
    en_attente: list[PropositionPivot]      # à soumettre à l'analyste (mode supervisé)
    ignores: list[tuple[Pivot, str]]        # (pivot, raison) — affiché pour transparence

    @property
    def total_retenus(self) -> int:
        return len(self.a_executer) + len(self.en_attente)


class OrchestrateurPivot:
    def __init__(
        self,
        session: Session,
        investigation: Investigation,
        organisation: Organisation,
        plan: Plan,
    ):
        self.session = session
        self.investigation = investigation
        self.organisation = organisation
        self.plan = plan

        conf = config_metier().section("pivot")
        self.max_recherches = int(conf.get("max_recherches_par_investigation", 25))

        options = investigation.options or {}
        self.profondeur_max = profondeur_pivot_autorisee(plan, organisation, options.get("profondeur"))
        self.mode = mode_pivot_effectif(plan, organisation, options.get("mode_pivot"))

    # --- État courant ------------------------------------------------------

    def valeurs_deja_explorees(self) -> set[str]:
        """Valeurs déjà proposées ou exécutées, pour ne jamais repartir en boucle."""
        propositions = self.session.scalars(
            select(PropositionPivot).where(
                PropositionPivot.investigation_id == self.investigation.id
            )
        ).all()
        explorees = {f"{p.action}:{p.valeur_normalisee}" for p in propositions}

        # Le pseudonyme initial et ses variantes comptent comme déjà explorés
        from app.moteur.correlation.base import normaliser_pseudo
        from app.moteur.pivot.detecteur import ACTION_RECHERCHE

        for pseudo in [self.investigation.pseudo_initial, *(self.investigation.variantes or [])]:
            explorees.add(f"{ACTION_RECHERCHE}:{normaliser_pseudo(pseudo)}")
        return explorees

    def budget_restant(self) -> int:
        """Nombre de recherches supplémentaires encore autorisées pour cette investigation."""
        executees = self.session.scalars(
            select(PropositionPivot.id).where(
                PropositionPivot.investigation_id == self.investigation.id,
                PropositionPivot.statut.in_(
                    [StatutPropositionPivot.ACCEPTEE.value, StatutPropositionPivot.AUTOMATIQUE.value]
                ),
            )
        ).all()
        return max(0, self.max_recherches - len(executees))

    # --- Arbitrage ---------------------------------------------------------

    def arbitrer(self, pivots: list[Pivot], profondeur_source: int) -> DecisionPivot:
        """Applique les garde-fous et crée les propositions correspondantes."""
        a_executer: list[PropositionPivot] = []
        en_attente: list[PropositionPivot] = []
        ignores: list[tuple[Pivot, str]] = []

        if not pivot_disponible(self.plan):
            return DecisionPivot([], [], [(p, "pivot non inclus dans le plan actif") for p in pivots])

        profondeur_cible = profondeur_source + 1
        if profondeur_cible > self.profondeur_max:
            motif = (
                f"profondeur maximale atteinte ({self.profondeur_max} "
                f"pour le plan {self.plan.nom_affiche})"
            )
            return DecisionPivot([], [], [(p, motif) for p in pivots])

        budget = self.budget_restant()
        if budget <= 0:
            motif = f"plafond de {self.max_recherches} recherches atteint pour cette investigation"
            return DecisionPivot([], [], [(p, motif) for p in pivots])

        automatique = self.mode == ModePivot.AUTOMATIQUE.value

        for pivot in pivots:
            if len(a_executer) + len(en_attente) >= budget:
                ignores.append((pivot, "budget de recherches de l'investigation épuisé"))
                continue

            proposition = PropositionPivot(
                investigation_id=self.investigation.id,
                organisation_id=self.investigation.organisation_id,
                profil_source_id=pivot.profil_source_id,
                donnee_source_id=pivot.donnee_source_id,
                type_pivot=pivot.type_pivot,
                valeur=pivot.valeur[:500],
                valeur_normalisee=pivot.valeur_normalisee[:500],
                action=pivot.action,
                profondeur_cible=profondeur_cible,
                libelle=pivot.libelle[:300],
                statut=(
                    StatutPropositionPivot.AUTOMATIQUE.value
                    if automatique
                    else StatutPropositionPivot.EN_ATTENTE.value
                ),
                decidee_le=maintenant() if automatique else None,
            )
            self.session.add(proposition)

            if automatique:
                a_executer.append(proposition)
            else:
                en_attente.append(proposition)

        self.session.flush()
        journal.info(
            "Investigation %s : %d pivot(s) à exécuter, %d en attente de validation, %d ignoré(s)",
            self.investigation.id, len(a_executer), len(en_attente), len(ignores),
        )
        return DecisionPivot(a_executer, en_attente, ignores)

    def accepter(self, proposition: PropositionPivot, utilisateur_id: str) -> None:
        """Validation manuelle d'une proposition (mode supervisé)."""
        proposition.statut = StatutPropositionPivot.ACCEPTEE.value
        proposition.decidee_par = utilisateur_id
        proposition.decidee_le = maintenant()

    def refuser(self, proposition: PropositionPivot, utilisateur_id: str) -> None:
        proposition.statut = StatutPropositionPivot.REFUSEE.value
        proposition.decidee_par = utilisateur_id
        proposition.decidee_le = maintenant()
