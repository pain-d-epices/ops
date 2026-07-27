"""Endpoints d'organisation : préférences, membres, invitations."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select

from app.db.base import maintenant
from app.facturation.garde import mode_pivot_effectif, profondeur_pivot_autorisee
from app.modeles.enums import ActionJournal, RoleMembre
from app.modeles.organisation import Appartenance, Invitation
from app.modeles.utilisateur import Utilisateur
from app.schemas.auth import (
    DemandeInvitation,
    InvitationSortie,
    MembreSortie,
    OrganisationSortie,
    PreferencesOrganisation,
)
from app.securite.dependances import ContexteRequete, contexte_courant, exiger_role
from app.securite.mots_de_passe import generer_jeton_aleatoire
from app.services.journal import journaliser

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/organisation", tags=["Organisation"])

DUREE_INVITATION_JOURS = 14


def _sortie(ctx: ContexteRequete) -> OrganisationSortie:
    organisation = ctx.organisation
    return OrganisationSortie(
        id=organisation.id,
        nom=organisation.nom,
        slug=organisation.slug,
        statut=organisation.statut,
        mode_pivot=organisation.mode_pivot,
        profondeur_pivot_souhaitee=organisation.profondeur_pivot_souhaitee,
        retention_jours=organisation.retention_jours,
        # Ce que le serveur appliquera réellement, une fois bornée par le plan :
        # l'interface doit montrer l'effet réel du réglage, pas le souhait exprimé.
        mode_pivot_effectif=mode_pivot_effectif(ctx.plan, organisation),
        profondeur_pivot_effective=profondeur_pivot_autorisee(ctx.plan, organisation),
        cree_le=organisation.created_at,
    )


@routeur.get("", response_model=OrganisationSortie)
def obtenir_organisation(ctx: ContexteRequete = Depends(contexte_courant)) -> OrganisationSortie:
    return _sortie(ctx)


@routeur.patch("", response_model=OrganisationSortie)
def modifier_preferences(
    demande: PreferencesOrganisation,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value)),
) -> OrganisationSortie:
    """Modifie les préférences de l'organisation (mode de pivot, rétention, nom).

    Les valeurs sont enregistrées telles que demandées, même si le plan actuel ne les
    permet pas encore : elles s'appliqueront automatiquement après montée en gamme,
    sans que le client ait à reconfigurer.
    """
    organisation = ctx.organisation
    if demande.nom is not None:
        organisation.nom = demande.nom.strip()[:150]
    if demande.mode_pivot is not None:
        organisation.mode_pivot = demande.mode_pivot.value
    if demande.profondeur_pivot_souhaitee is not None:
        organisation.profondeur_pivot_souhaitee = demande.profondeur_pivot_souhaitee

    retention_modifiee = False
    if demande.retention_jours is not None and demande.retention_jours != organisation.retention_jours:
        organisation.retention_jours = demande.retention_jours
        retention_modifiee = True

    ctx.session.commit()
    ctx.session.refresh(organisation)

    if retention_modifiee:
        # Répercuter la nouvelle durée sur les investigations existantes
        try:
            from app.taches.maintenance import appliquer_retention

            appliquer_retention.apply_async(
                kwargs={"organisation_id": organisation.id}, queue="maintenance"
            )
        except Exception:  # noqa: BLE001
            journal.warning("Recalcul des dates de rétention non planifié (file indisponible)")

    return _sortie(ctx)


@routeur.get("/membres", response_model=list[MembreSortie])
def lister_membres(ctx: ContexteRequete = Depends(contexte_courant)) -> list[MembreSortie]:
    appartenances = ctx.session.scalars(
        select(Appartenance).where(Appartenance.organisation_id == ctx.organisation_id)
    ).all()

    membres = []
    for appartenance in appartenances:
        utilisateur = ctx.session.get(Utilisateur, appartenance.utilisateur_id)
        if utilisateur is None:
            continue
        membres.append(
            MembreSortie(
                utilisateur_id=utilisateur.id,
                email=utilisateur.email,
                nom_complet=utilisateur.nom_complet,
                role=appartenance.role,
                rejoint_le=appartenance.created_at,
            )
        )
    return membres


@routeur.post("/invitations", response_model=InvitationSortie, status_code=status.HTTP_201_CREATED)
def inviter(
    demande: DemandeInvitation,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value)),
) -> InvitationSortie:
    """Invite un utilisateur à rejoindre l'organisation, dans la limite du plan."""
    membres_actuels = ctx.session.scalar(
        select(func.count(Appartenance.id)).where(
            Appartenance.organisation_id == ctx.organisation_id
        )
    ) or 0
    invitations_en_cours = ctx.session.scalar(
        select(func.count(Invitation.id)).where(
            Invitation.organisation_id == ctx.organisation_id,
            Invitation.acceptee_le.is_(None),
            Invitation.revoquee.is_(False),
            Invitation.expire_le > maintenant(),
        )
    ) or 0

    # Les invitations en attente comptent dans le quota : sinon un client pourrait
    # dépasser sa limite d'utilisateurs en invitant tout le monde d'un coup.
    if membres_actuels + invitations_en_cours >= ctx.plan.quota_utilisateurs:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Le plan {ctx.plan.nom_affiche} est limité à {ctx.plan.quota_utilisateurs} "
            f"utilisateur(s). Passez à un palier supérieur pour agrandir votre équipe.",
        )

    email = demande.email.lower().strip()
    deja_membre = ctx.session.scalar(
        select(Appartenance)
        .join(Utilisateur, Utilisateur.id == Appartenance.utilisateur_id)
        .where(Appartenance.organisation_id == ctx.organisation_id, Utilisateur.email == email)
    )
    if deja_membre is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cette personne fait déjà partie de l'organisation.")

    invitation = Invitation(
        organisation_id=ctx.organisation_id,
        email=email,
        role=demande.role.value,
        jeton=generer_jeton_aleatoire(32),
        invite_par=ctx.utilisateur.id,
        expire_le=maintenant() + timedelta(days=DUREE_INVITATION_JOURS),
    )
    ctx.session.add(invitation)

    journaliser(
        ctx.session, ActionJournal.MEMBRE_INVITE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=email, requete=requete,
        detail={"role": demande.role.value},
    )
    ctx.session.commit()
    ctx.session.refresh(invitation)

    # L'envoi du courriel d'invitation n'est pas encore branché : le jeton est
    # renvoyé pour que l'administrateur transmette le lien lui-même.
    return InvitationSortie(
        id=invitation.id, email=invitation.email, role=invitation.role,
        jeton=invitation.jeton, expire_le=invitation.expire_le, acceptee=False,
    )


@routeur.get("/invitations", response_model=list[InvitationSortie])
def lister_invitations(
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value)),
) -> list[InvitationSortie]:
    invitations = ctx.session.scalars(
        select(Invitation)
        .where(Invitation.organisation_id == ctx.organisation_id, Invitation.revoquee.is_(False))
        .order_by(Invitation.created_at.desc())
    ).all()
    return [
        InvitationSortie(
            id=i.id, email=i.email, role=i.role, jeton=i.jeton,
            expire_le=i.expire_le, acceptee=i.acceptee_le is not None,
        )
        for i in invitations
    ]


@routeur.delete("/membres/{utilisateur_id}", status_code=status.HTTP_204_NO_CONTENT)
def retirer_membre(
    utilisateur_id: str,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value)),
) -> None:
    appartenance = ctx.session.scalar(
        select(Appartenance).where(
            Appartenance.utilisateur_id == utilisateur_id,
            Appartenance.organisation_id == ctx.organisation_id,
        )
    )
    if appartenance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable.")

    # Une organisation sans administrateur deviendrait ingérable : on refuse de
    # retirer le dernier.
    if appartenance.role == RoleMembre.ADMIN.value:
        autres_admins = ctx.session.scalar(
            select(func.count(Appartenance.id)).where(
                Appartenance.organisation_id == ctx.organisation_id,
                Appartenance.role == RoleMembre.ADMIN.value,
                Appartenance.utilisateur_id != utilisateur_id,
            )
        ) or 0
        if autres_admins == 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Impossible de retirer le dernier administrateur de l'organisation.",
            )

    journaliser(
        ctx.session, ActionJournal.MEMBRE_RETIRE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=utilisateur_id, requete=requete,
    )
    ctx.session.delete(appartenance)
    ctx.session.commit()


@routeur.delete("/donnees", status_code=status.HTTP_202_ACCEPTED)
def supprimer_donnees_organisation(
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value)),
) -> dict:
    """Supprime toutes les investigations de l'organisation (droit à l'effacement).

    Le compte et l'organisation subsistent ; seules les données d'investigation
    disparaissent, ainsi que les identités de tiers qu'elles contiennent.
    """
    from app.modeles.investigation import Investigation

    investigations = ctx.session.scalars(
        select(Investigation).where(Investigation.organisation_id == ctx.organisation_id)
    ).all()
    nombre = len(investigations)
    for investigation in investigations:
        ctx.session.delete(investigation)

    journaliser(
        ctx.session, ActionJournal.SUPPRESSION_ORGANISATION,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, requete=requete,
        detail={"investigations_supprimees": nombre},
    )
    ctx.session.commit()
    return {"investigations_supprimees": nombre}
