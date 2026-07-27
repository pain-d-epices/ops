"""Accès au graphe de relations.

**Seule** couche qui connaît les tables `noeuds_graphe` et `aretes_graphe`. Le reste
du code manipule le graphe à travers ce dépôt : une migration ultérieure vers une
base graphe dédiée (Neo4j) se limiterait à réécrire ce fichier.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modeles.enums import TypeArete, TypeNoeud
from app.modeles.graphe import AreteGraphe, NoeudGraphe
from app.moteur.correlation.base import normaliser

journal = logging.getLogger(__name__)


@dataclass
class NoeudExporte:
    """Nœud tel qu'il est envoyé au frontend."""

    id: str
    type: str
    libelle: str
    score: int
    profondeur: int
    profil_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class AreteExportee:
    id: str
    source: str
    cible: str
    type: str
    libelle: str | None
    poids: float


@dataclass
class GrapheExporte:
    noeuds: list[NoeudExporte] = field(default_factory=list)
    aretes: list[AreteExportee] = field(default_factory=list)

    def vers_dict(self) -> dict[str, Any]:
        return {
            "noeuds": [n.__dict__ for n in self.noeuds],
            "aretes": [a.__dict__ for a in self.aretes],
        }


def cle_unicite(type_noeud: TypeNoeud | str, libelle: str) -> str:
    """Clé de déduplication d'un nœud.

    Les URLs et adresses électroniques sont comparées en minuscules brutes ; le reste
    passe par la normalisation générale (sans accents ni ponctuation).
    """
    type_valeur = type_noeud.value if isinstance(type_noeud, TypeNoeud) else type_noeud
    if type_valeur in (TypeNoeud.COMPTE.value, TypeNoeud.EMAIL.value, TypeNoeud.LIEN.value):
        return libelle.strip().lower()[:500]
    return normaliser(libelle)[:500] or libelle.strip().lower()[:500]


class DepotGraphe:
    """Opérations de lecture et d'écriture sur le graphe d'une investigation."""

    def __init__(self, session: Session, investigation_id: str, organisation_id: str):
        self.session = session
        self.investigation_id = investigation_id
        self.organisation_id = organisation_id

    # --- Écriture ----------------------------------------------------------

    def obtenir_ou_creer_noeud(
        self,
        type_noeud: TypeNoeud | str,
        libelle: str,
        *,
        score: int = 0,
        profondeur: int = 0,
        profil_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> NoeudGraphe:
        """Crée le nœud s'il n'existe pas, sinon met à jour ses attributs.

        La déduplication est le mécanisme central de la visualisation : quand deux
        comptes différents mènent au même email, ils pointent vers **un seul** nœud,
        et c'est cette convergence qui fait apparaître le lien à l'écran.
        """
        type_valeur = type_noeud.value if isinstance(type_noeud, TypeNoeud) else type_noeud
        cle = cle_unicite(type_valeur, libelle)

        noeud = self.session.scalar(
            select(NoeudGraphe).where(
                NoeudGraphe.investigation_id == self.investigation_id,
                NoeudGraphe.type == type_valeur,
                NoeudGraphe.cle_unicite == cle,
            )
        )

        if noeud is None:
            noeud = NoeudGraphe(
                investigation_id=self.investigation_id,
                organisation_id=self.organisation_id,
                type=type_valeur,
                libelle=libelle[:300],
                cle_unicite=cle,
                profil_id=profil_id,
                score=score,
                profondeur=profondeur,
                meta=meta or {},
            )
            self.session.add(noeud)
            self.session.flush()
            return noeud

        # Mise à jour : on garde la profondeur la plus faible (chemin le plus court
        # depuis le pseudonyme initial) et le score le plus élevé.
        if score > noeud.score:
            noeud.score = score
        if profondeur < noeud.profondeur:
            noeud.profondeur = profondeur
        if profil_id and not noeud.profil_id:
            noeud.profil_id = profil_id
        if meta:
            noeud.meta = {**(noeud.meta or {}), **meta}
        return noeud

    def creer_arete(
        self,
        source: NoeudGraphe | str,
        cible: NoeudGraphe | str,
        type_arete: TypeArete | str,
        *,
        libelle: str | None = None,
        poids: float = 1.0,
        meta: dict[str, Any] | None = None,
    ) -> AreteGraphe | None:
        """Crée une arête si elle n'existe pas déjà. Ignore les boucles sur soi-même."""
        source_id = source if isinstance(source, str) else source.id
        cible_id = cible if isinstance(cible, str) else cible.id
        if source_id == cible_id:
            return None

        type_valeur = type_arete.value if isinstance(type_arete, TypeArete) else type_arete
        existante = self.session.scalar(
            select(AreteGraphe).where(
                AreteGraphe.investigation_id == self.investigation_id,
                AreteGraphe.source_id == source_id,
                AreteGraphe.cible_id == cible_id,
                AreteGraphe.type == type_valeur,
            )
        )
        if existante is not None:
            if libelle and not existante.libelle:
                existante.libelle = libelle[:300]
            return existante

        arete = AreteGraphe(
            investigation_id=self.investigation_id,
            organisation_id=self.organisation_id,
            source_id=source_id,
            cible_id=cible_id,
            type=type_valeur,
            libelle=libelle[:300] if libelle else None,
            poids=poids,
            meta=meta or {},
        )
        self.session.add(arete)
        self.session.flush()
        return arete

    def mettre_a_jour_score_profil(self, profil_id: str, score: int) -> None:
        """Répercute le score d'un profil sur son nœud (couleur et taille à l'affichage)."""
        noeud = self.session.scalar(
            select(NoeudGraphe).where(
                NoeudGraphe.investigation_id == self.investigation_id,
                NoeudGraphe.profil_id == profil_id,
            )
        )
        if noeud is not None:
            noeud.score = score

    # --- Lecture -----------------------------------------------------------

    def exporter(self, score_minimal: int = 0, types_exclus: set[str] | None = None) -> GrapheExporte:
        """Graphe complet, filtrable par score et par type de nœud.

        Une arête n'est conservée que si ses deux extrémités le sont : sinon le
        frontend recevrait des arêtes pointant dans le vide.
        """
        types_exclus = types_exclus or set()

        noeuds = self.session.scalars(
            select(NoeudGraphe).where(
                NoeudGraphe.investigation_id == self.investigation_id,
                NoeudGraphe.organisation_id == self.organisation_id,
            )
        ).all()

        retenus = [
            n
            for n in noeuds
            if n.type not in types_exclus
            # Les nœuds d'information (email, pseudo…) n'ont pas de score propre :
            # ils ne doivent pas disparaître quand on filtre sur la confiance.
            and (n.type != TypeNoeud.COMPTE.value or n.score >= score_minimal)
        ]
        identifiants = {n.id for n in retenus}

        aretes = self.session.scalars(
            select(AreteGraphe).where(
                AreteGraphe.investigation_id == self.investigation_id,
                AreteGraphe.organisation_id == self.organisation_id,
            )
        ).all()

        return GrapheExporte(
            noeuds=[
                NoeudExporte(
                    id=n.id, type=n.type, libelle=n.libelle, score=n.score,
                    profondeur=n.profondeur, profil_id=n.profil_id, meta=n.meta or {},
                )
                for n in retenus
            ],
            aretes=[
                AreteExportee(
                    id=a.id, source=a.source_id, cible=a.cible_id,
                    type=a.type, libelle=a.libelle, poids=a.poids,
                )
                for a in aretes
                if a.source_id in identifiants and a.cible_id in identifiants
            ],
        )

    def compter(self) -> tuple[int, int]:
        noeuds = self.session.scalars(
            select(NoeudGraphe.id).where(NoeudGraphe.investigation_id == self.investigation_id)
        ).all()
        aretes = self.session.scalars(
            select(AreteGraphe.id).where(AreteGraphe.investigation_id == self.investigation_id)
        ).all()
        return len(noeuds), len(aretes)
