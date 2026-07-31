"""Schémas d'entrée et de sortie pour l'authentification et les organisations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.modeles.enums import ModePivot, RoleMembre


class DemandeInscription(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(min_length=12, max_length=200)
    nom_complet: str | None = Field(default=None, max_length=150)
    # Création d'une nouvelle organisation, ou rattachement via un jeton d'invitation
    nom_organisation: str | None = Field(default=None, max_length=150)
    jeton_invitation: str | None = None
    # L'acceptation des conditions est exigée dès l'inscription : l'outil traite des
    # données personnelles de tiers, le cadre légal doit être accepté avant tout usage.
    accepter_cgu: bool = False
    # Solution de l'épreuve anti-automatisation, obtenue sur /auth/defi-anti-robot et
    # résolue par le navigateur. Voir app/securite/anti_bot.py.
    preuve_anti_robot: str | None = None


class DemandeConnexion(BaseModel):
    email: EmailStr
    mot_de_passe: str
    organisation_id: str | None = None
    # Fourni au second appel, une fois que le premier a répondu 401 avec
    # code="totp_requis". Un code à 6 chiffres, ou l'un des codes de secours.
    code_totp: str | None = None


class DemandeActivationTotp(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class DemandeDesactivationTotp(BaseModel):
    mot_de_passe: str
    code: str = Field(min_length=6, max_length=8)


class ActivationTotpSortie(BaseModel):
    secret: str
    qr_code_base64: str
    codes_secours: list[str]


class EtatTotpSortie(BaseModel):
    actif: bool
    codes_secours_restants: int


class DemandeAcceptationCgu(BaseModel):
    version: str = "1.0"


class OrganisationResumee(BaseModel):
    id: str
    nom: str
    slug: str
    role: str
    plan_code: str
    plan_nom: str


class UtilisateurSortie(BaseModel):
    id: str
    email: str
    nom_complet: str | None
    cgu_acceptees: bool
    cgu_version_acceptee: str | None
    derniere_connexion: datetime | None
    organisations: list[OrganisationResumee] = []


class ReponseConnexion(BaseModel):
    utilisateur: UtilisateurSortie
    organisation_active: str | None
    # Le jeton d'accès est aussi posé en cookie httpOnly ; il n'est renvoyé dans le
    # corps que pour les intégrations serveur à serveur (plans avec accès API).
    jeton_acces: str
    expire_dans_secondes: int


class DemandeInvitation(BaseModel):
    email: EmailStr
    role: RoleMembre = RoleMembre.ANALYSTE


class InvitationSortie(BaseModel):
    id: str
    email: str
    role: str
    jeton: str
    expire_le: datetime
    acceptee: bool


class MembreSortie(BaseModel):
    utilisateur_id: str
    email: str
    nom_complet: str | None
    role: str
    rejoint_le: datetime


class PreferencesOrganisation(BaseModel):
    nom: str | None = Field(default=None, max_length=150)
    mode_pivot: ModePivot | None = None
    profondeur_pivot_souhaitee: int | None = Field(default=None, ge=0, le=10)
    retention_jours: int | None = Field(default=None, ge=0, le=3650)


class OrganisationSortie(BaseModel):
    id: str
    nom: str
    slug: str
    statut: str
    mode_pivot: str
    profondeur_pivot_souhaitee: int
    retention_jours: int
    # Valeurs réellement appliquées après bornage par le plan et le plafond serveur :
    # l'interface doit afficher ce qui sera fait, pas ce qui a été demandé.
    mode_pivot_effectif: str
    profondeur_pivot_effective: int
    cree_le: datetime
