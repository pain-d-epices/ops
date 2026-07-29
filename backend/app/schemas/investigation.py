"""Schémas d'entrée et de sortie des investigations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modeles.enums import ModePivot, VerdictManuel


class PointDepartEntree(BaseModel):
    """Un élément fourni au lancement. Le type peut être omis : il est alors deviné."""

    valeur: str = Field(min_length=2, max_length=500)
    type: str | None = None


class PointDepartSortie(BaseModel):
    id: str
    type: str
    valeur: str
    statut: str
    message_erreur: str | None
    nb_comptes_trouves: int
    detail: dict[str, Any] = {}


class TypeRechercheSortie(BaseModel):
    """Un type de point de départ proposé à la saisie, et son accessibilité."""

    type: str
    libelle: str
    exemple: str
    autorise: bool
    #: motif du refus quand le plan ne couvre pas ce type
    motif: str | None = None


class TypesRechercheSortie(BaseModel):
    types: list[TypeRechercheSortie]
    #: nombre d'éléments de départ acceptés, pseudonyme compris ; 0 = illimité
    max_points_depart: int


class DemandeInvestigation(BaseModel):
    pseudo: str = Field(min_length=2, max_length=200)
    # Éléments complémentaires : adresse électronique, téléphone, compte, adresse.
    # Leur nombre est borné par le plan de l'organisation.
    points_depart: list[PointDepartEntree] = Field(default_factory=list, max_length=20)
    variantes: list[str] = Field(default_factory=list, max_length=5)
    titre: str | None = Field(default=None, max_length=200)
    # Ces trois options sont des souhaits : le serveur les borne selon le plan actif.
    profondeur_pivot: int | None = Field(default=None, ge=0, le=10)
    mode_pivot: ModePivot | None = None
    top_sites: int | None = Field(default=None, ge=10, le=3000)
    sites_exclus: list[str] = Field(default_factory=list, max_length=100)


class InvestigationResumee(BaseModel):
    id: str
    titre: str | None
    pseudo_initial: str
    statut: str
    progression: int
    etape_courante: str | None
    nb_profils_trouves: int
    nb_profils_confirmes: int
    nb_recherches_effectuees: int
    cree_le: datetime
    terminee_le: datetime | None
    supprimer_apres: datetime | None


class InvestigationDetaillee(InvestigationResumee):
    variantes: list[str]
    options: dict[str, Any]
    message_erreur: str | None
    cree_par_email: str | None = None
    nb_noeuds: int = 0
    nb_aretes: int = 0
    nb_propositions_en_attente: int = 0
    points_depart: list[PointDepartSortie] = []


class SignalSortie(BaseModel):
    regle: str
    score_regle: float
    poids: float
    contribution_points: float
    explication: str
    detail: dict[str, Any] = {}


class DonneeSortie(BaseModel):
    id: str
    type: str
    valeur: str
    module_source: str
    confiance_extraction: float
    pivotee: bool
    meta: dict[str, Any] = {}


class ProfilResume(BaseModel):
    id: str
    site_nom: str
    site_domaine: str
    url: str
    pseudo_sur_le_site: str
    score_confiance: int
    niveau: str
    verdict_manuel: str | None
    profondeur: int
    enrichi: bool
    module_utilise: str | None


class ProfilDetaille(ProfilResume):
    statut_maigret: str
    decouvert_par_profil_id: str | None
    erreur_enrichissement: str | None
    # Date du verdict manuel : l'interface l'affiche pour dater la vérification humaine
    verdict_le: datetime | None = None
    enrichi_le: datetime | None = None
    donnees_maigret: dict[str, Any] = {}
    donnees_extraites: list[DonneeSortie] = []
    # Détail du calcul du score : permet à l'analyste de contester une conclusion
    # plutôt que de la subir.
    signaux: list[SignalSortie] = []


class DemandeVerdict(BaseModel):
    verdict: VerdictManuel | None = None   # None = annuler un verdict précédent


class PropositionSortie(BaseModel):
    id: str
    type_pivot: str
    valeur: str
    action: str
    libelle: str
    profondeur_cible: int
    statut: str
    profil_source_id: str | None
    cree_le: datetime
    decidee_le: datetime | None


class DemandeDecisionPivot(BaseModel):
    accepter: bool


class NoeudSortie(BaseModel):
    id: str
    type: str
    libelle: str
    score: int
    profondeur: int
    profil_id: str | None
    meta: dict[str, Any] = {}


class AreteSortie(BaseModel):
    id: str
    source: str
    cible: str
    type: str
    libelle: str | None
    poids: float


class GrapheSortie(BaseModel):
    investigation_id: str
    noeuds: list[NoeudSortie]
    aretes: list[AreteSortie]
