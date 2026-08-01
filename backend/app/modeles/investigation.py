"""Modèles d'investigation : recherches, profils trouvés, données extraites, pivots."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, HorodatageMixin, nouvel_id
from app.modeles.enums import (
    NiveauConfiance,
    StatutInvestigation,
    StatutPropositionPivot,
)

if TYPE_CHECKING:
    pass

TypeJson = JSON().with_variant(JSONB(), "postgresql")


class Investigation(Base, HorodatageMixin):
    """Une enquête sur un pseudonyme : point d'entrée de tout le reste."""

    __tablename__ = "investigations"
    __table_args__ = (Index("ix_investigations_org_statut", "organisation_id", "statut"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    organisation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cree_par: Mapped[str | None] = mapped_column(String(36), ForeignKey("utilisateurs.id", ondelete="SET NULL"))

    titre: Mapped[str | None] = mapped_column(String(200))
    pseudo_initial: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    # Variantes de pseudo saisies par l'utilisateur en plus du pseudo principal
    variantes: Mapped[list[str]] = mapped_column(TypeJson, default=list, nullable=False)

    # Options figées au lancement : profondeur retenue (après application du plafond),
    # mode de pivot effectif, sites exclus, nombre de sites à scanner.
    options: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)

    statut: Mapped[str] = mapped_column(
        String(20), default=StatutInvestigation.EN_ATTENTE.value, nullable=False, index=True
    )
    progression: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0-100
    etape_courante: Mapped[str | None] = mapped_column(String(200))
    message_erreur: Mapped[str | None] = mapped_column(Text)

    demarree_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Date au-delà de laquelle la purge automatique RGPD supprimera l'investigation
    supprimer_apres: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # Compteurs dénormalisés : évitent un COUNT() sur chaque affichage de liste
    nb_profils_trouves: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_profils_confirmes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_recherches_effectuees: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    points_depart: Mapped[list[PointDepart]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )
    executions: Mapped[list[ExecutionRecherche]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )
    profils: Mapped[list[ProfilIdentite]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )
    propositions_pivot: Mapped[list[PropositionPivot]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Investigation {self.pseudo_initial} ({self.statut})>"


class PointDepart(Base, HorodatageMixin):
    """Un élément fourni par l'analyste au lancement de l'investigation.

    Le pseudonyme initial reste stocké sur l'investigation pour compatibilité, mais
    une investigation peut désormais démarrer avec plusieurs éléments de natures
    différentes : un pseudonyme, l'adresse d'un compte, une adresse électronique, un
    numéro… Fournis ensemble, ils se corroborent dès le premier tour au lieu
    d'attendre un rebond.
    """

    __tablename__ = "points_depart"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    type: Mapped[str] = mapped_column(String(20), nullable=False)   # voir TypePointDepart
    valeur: Mapped[str] = mapped_column(String(500), nullable=False)
    valeur_normalisee: Mapped[str] = mapped_column(String(500), nullable=False)

    statut: Mapped[str] = mapped_column(String(20), default="en_attente", nullable=False)
    message_erreur: Mapped[str | None] = mapped_column(String(500))
    nb_comptes_trouves: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    traite_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)

    investigation: Mapped[Investigation] = relationship(back_populates="points_depart")

    def __repr__(self) -> str:
        return f"<PointDepart {self.type}={self.valeur[:30]}>"


class ExecutionRecherche(Base, HorodatageMixin):
    """Une exécution de Maigret. Il y en a une par pseudo recherché, pivots compris."""

    __tablename__ = "executions_recherche"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    pseudo_recherche: Mapped[str] = mapped_column(String(200), nullable=False)
    profondeur: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Profil à l'origine de cette recherche (null pour la recherche initiale)
    declenchee_par_profil_id: Mapped[str | None] = mapped_column(String(36))

    statut: Mapped[str] = mapped_column(String(20), default="en_attente", nullable=False)
    nb_sites_scannes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_sites_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duree_secondes: Mapped[float | None] = mapped_column(Float)
    message_erreur: Mapped[str | None] = mapped_column(Text)

    # Sortie Maigret conservée intacte : permet de rejouer la corrélation après
    # ajustement des règles de scoring, sans relancer la recherche réseau.
    resultat_brut: Mapped[dict[str, Any] | None] = mapped_column(TypeJson)

    investigation: Mapped[Investigation] = relationship(back_populates="executions")


class ProfilIdentite(Base, HorodatageMixin):
    """Un compte trouvé sur un site, avec son score de corrélation."""

    __tablename__ = "profils_identite"
    __table_args__ = (
        UniqueConstraint("investigation_id", "url", name="uq_profil_investigation_url"),
        Index("ix_profils_org_investigation", "organisation_id", "investigation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    execution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("executions_recherche.id", ondelete="SET NULL")
    )

    site_nom: Mapped[str] = mapped_column(String(150), nullable=False)
    site_domaine: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    pseudo_sur_le_site: Mapped[str] = mapped_column(String(200), nullable=False)
    statut_maigret: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- Corrélation ---
    score_confiance: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    niveau: Mapped[str] = mapped_column(String(20), default=NiveauConfiance.FAIBLE.value, nullable=False)
    verdict_manuel: Mapped[str | None] = mapped_column(String(20))
    verdict_par: Mapped[str | None] = mapped_column(String(36))
    verdict_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Généalogie (traçabilité du pivot) ---
    profondeur: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decouvert_par_profil_id: Mapped[str | None] = mapped_column(String(36))

    # --- Enrichissement ---
    enrichi: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enrichi_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    module_utilise: Mapped[str | None] = mapped_column(String(100))
    erreur_enrichissement: Mapped[str | None] = mapped_column(String(500))

    donnees_maigret: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)

    investigation: Mapped[Investigation] = relationship(back_populates="profils")
    donnees_extraites: Mapped[list[DonneeExtraite]] = relationship(
        back_populates="profil", cascade="all, delete-orphan"
    )
    signaux: Mapped[list[SignalCorrelation]] = relationship(
        back_populates="profil", cascade="all, delete-orphan"
    )

    @property
    def est_rejete(self) -> bool:
        return self.verdict_manuel == "faux_positif"

    def __repr__(self) -> str:
        return f"<ProfilIdentite {self.site_nom}/{self.pseudo_sur_le_site} {self.score_confiance}>"


class DonneeExtraite(Base, HorodatageMixin):
    """Une information extraite d'un profil par un module de site."""

    __tablename__ = "donnees_extraites"
    __table_args__ = (
        Index("ix_donnees_investigation_type", "investigation_id", "type"),
        Index("ix_donnees_valeur_norm", "investigation_id", "valeur_normalisee"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    #: Compte dont l'information a été extraite. **Nul** quand elle provient d'un point
    #: de départ et non d'un profil : le nom derrière une adresse Gravatar ou
    #: l'opérateur d'un numéro décrivent la personne recherchée, pas un compte trouvé.
    #: L'exiger faisait perdre ces informations lorsque aucun compte n'était trouvé.
    profil_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("profils_identite.id", ondelete="CASCADE"), nullable=True, index=True
    )
    investigation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    organisation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    type: Mapped[str] = mapped_column(String(30), nullable=False)
    valeur: Mapped[str] = mapped_column(Text, nullable=False)
    # Version normalisée (minuscules, sans accents ni ponctuation) : sert à comparer
    # et dédupliquer deux valeurs équivalentes écrites différemment.
    valeur_normalisee: Mapped[str] = mapped_column(String(500), nullable=False)

    module_source: Mapped[str] = mapped_column(String(100), nullable=False)
    confiance_extraction: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)

    # Cette donnée a-t-elle déjà servi de point de pivot ? (anti-boucle)
    pivotee: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    profil: Mapped[ProfilIdentite | None] = relationship(back_populates="donnees_extraites")

    def __repr__(self) -> str:
        return f"<DonneeExtraite {self.type}={self.valeur[:40]}>"


class SignalCorrelation(Base):
    """Contribution d'une règle de corrélation au score d'un profil.

    Rend le score explicable : l'utilisateur voit « 87 % parce que pseudo exact (+40),
    avatar identique à GitHub (+30), lien croisé (+17) ». Sans cette traçabilité, l'outil
    serait une boîte noire dont les conclusions ne pourraient pas être contestées —
    inacceptable quand la sortie sert à identifier une personne réelle.
    """

    __tablename__ = "signaux_correlation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    profil_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("profils_identite.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    regle: Mapped[str] = mapped_column(String(60), nullable=False)
    score_regle: Mapped[float] = mapped_column(Float, nullable=False)      # 0..1 (peut être négatif : pénalité)
    poids: Mapped[float] = mapped_column(Float, nullable=False)
    contribution_points: Mapped[float] = mapped_column(Float, nullable=False)  # points sur 100
    explication: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(TypeJson, default=dict, nullable=False)
    calcule_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    profil: Mapped[ProfilIdentite] = relationship(back_populates="signaux")


class PropositionPivot(Base, HorodatageMixin):
    """Un pivot possible détecté à partir d'une donnée extraite.

    En mode supervisé, la proposition attend une validation humaine.
    En mode automatique, elle est créée avec le statut « automatique » et exécutée
    immédiatement — la trace reste conservée dans les deux cas.
    """

    __tablename__ = "propositions_pivot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nouvel_id)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profil_source_id: Mapped[str | None] = mapped_column(String(36))
    donnee_source_id: Mapped[str | None] = mapped_column(String(36))

    type_pivot: Mapped[str] = mapped_column(String(30), nullable=False)   # pseudo_alt, email, lien_externe...
    valeur: Mapped[str] = mapped_column(String(500), nullable=False)
    valeur_normalisee: Mapped[str] = mapped_column(String(500), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)       # recherche_maigret, enrichissement_direct
    profondeur_cible: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    libelle: Mapped[str] = mapped_column(String(300), nullable=False)     # "email trouvé dans la bio GitHub"

    statut: Mapped[str] = mapped_column(
        String(20), default=StatutPropositionPivot.EN_ATTENTE.value, nullable=False, index=True
    )
    decidee_par: Mapped[str | None] = mapped_column(String(36))
    decidee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_id: Mapped[str | None] = mapped_column(String(36))  # exécution créée si acceptée

    investigation: Mapped[Investigation] = relationship(back_populates="propositions_pivot")

    def __repr__(self) -> str:
        return f"<PropositionPivot {self.type_pivot}={self.valeur[:30]} ({self.statut})>"
