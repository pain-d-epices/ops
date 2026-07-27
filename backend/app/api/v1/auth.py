"""Endpoints d'authentification, d'inscription et de gestion de session."""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import parametres
from app.db.base import maintenant, nouvel_id
from app.db.session import obtenir_session
from app.facturation.abonnements import plan_actif
from app.modeles.enums import ActionJournal, RoleMembre
from app.modeles.organisation import Appartenance, Invitation, Organisation
from app.modeles.utilisateur import JetonRafraichissement, Utilisateur
from app.schemas.auth import (
    DemandeAcceptationCgu,
    DemandeConnexion,
    DemandeInscription,
    OrganisationResumee,
    ReponseConnexion,
    UtilisateurSortie,
)
from app.securite.dependances import (
    NOM_COOKIE_ACCES,
    NOM_COOKIE_RAFRAICHISSEMENT,
    ContexteRequete,
    contexte_courant,
    utilisateur_courant,
)
from app.securite.jetons import creer_jeton_acces
from app.securite.mots_de_passe import (
    MotDePasseInvalide,
    generer_jeton_aleatoire,
    hacher,
    hacher_jeton,
    valider_politique,
    verifier,
)
from app.services.journal import journaliser

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/auth", tags=["Authentification"])

VERSION_CGU = "1.0"
# Après ce nombre d'échecs, le compte est temporairement bloqué (anti-force brute)
TENTATIVES_AVANT_BLOCAGE = 8
DUREE_BLOCAGE_MINUTES = 15


def _slugifier(nom: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", nom.lower()).strip("-")
    return (base or "organisation")[:60]


def _slug_disponible(session: Session, base: str) -> str:
    slug = base
    suffixe = 1
    while session.scalar(select(Organisation.id).where(Organisation.slug == slug)):
        suffixe += 1
        slug = f"{base}-{suffixe}"
    return slug


def _poser_cookies(reponse: Response, jeton_acces: str, jeton_rafraichissement: str) -> None:
    params = parametres()
    securise = params.est_production
    reponse.set_cookie(
        NOM_COOKIE_ACCES, jeton_acces,
        httponly=True,          # inaccessible au JavaScript : protection contre le vol par XSS
        secure=securise,
        samesite="lax",
        max_age=params.duree_jeton_acces_minutes * 60,
        path="/",
    )
    reponse.set_cookie(
        NOM_COOKIE_RAFRAICHISSEMENT, jeton_rafraichissement,
        httponly=True,
        secure=securise,
        samesite="lax",
        max_age=params.duree_jeton_rafraichissement_jours * 86400,
        path="/",
    )


def _creer_jeton_rafraichissement(session: Session, utilisateur: Utilisateur, requete: Request) -> str:
    params = parametres()
    jeton = generer_jeton_aleatoire()
    session.add(
        JetonRafraichissement(
            utilisateur_id=utilisateur.id,
            # Seule l'empreinte est stockée : une fuite de la base ne permet pas
            # de rejouer les sessions.
            jeton_hash=hacher_jeton(jeton),
            expire_le=maintenant() + timedelta(days=params.duree_jeton_rafraichissement_jours),
            cree_le=maintenant(),
            ip_creation=requete.client.host if requete.client else None,
            agent_utilisateur=(requete.headers.get("user-agent") or "")[:300] or None,
        )
    )
    return jeton


def _utilisateur_sortie(session: Session, utilisateur: Utilisateur) -> UtilisateurSortie:
    organisations = []
    for appartenance in utilisateur.appartenances:
        organisation = session.get(Organisation, appartenance.organisation_id)
        if organisation is None:
            continue
        plan = plan_actif(session, organisation.id)
        organisations.append(
            OrganisationResumee(
                id=organisation.id, nom=organisation.nom, slug=organisation.slug,
                role=appartenance.role, plan_code=plan.code, plan_nom=plan.nom_affiche,
            )
        )
    return UtilisateurSortie(
        id=utilisateur.id,
        email=utilisateur.email,
        nom_complet=utilisateur.nom_complet,
        cgu_acceptees=utilisateur.a_accepte_cgu,
        cgu_version_acceptee=utilisateur.cgu_version_acceptee,
        derniere_connexion=utilisateur.derniere_connexion,
        organisations=organisations,
    )


@routeur.post("/inscription", response_model=ReponseConnexion, status_code=status.HTTP_201_CREATED)
def inscription(
    demande: DemandeInscription,
    requete: Request,
    reponse: Response,
    session: Session = Depends(obtenir_session),
) -> ReponseConnexion:
    """Crée un compte, et soit une organisation, soit un rattachement par invitation."""
    email = demande.email.lower().strip()

    if not demande.accepter_cgu:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "L'acceptation des conditions d'utilisation est obligatoire pour créer un compte.",
        )

    if session.scalar(select(Utilisateur.id).where(Utilisateur.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Un compte existe déjà avec cette adresse.")

    try:
        valider_politique(demande.mot_de_passe)
    except MotDePasseInvalide as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    utilisateur = Utilisateur(
        id=nouvel_id(),
        email=email,
        mot_de_passe_hash=hacher(demande.mot_de_passe),
        nom_complet=demande.nom_complet,
        cgu_acceptees_le=maintenant(),
        cgu_version_acceptee=VERSION_CGU,
        derniere_connexion=maintenant(),
    )
    session.add(utilisateur)
    session.flush()

    # --- Rattachement à une organisation ---
    if demande.jeton_invitation:
        invitation = session.scalar(
            select(Invitation).where(Invitation.jeton == demande.jeton_invitation)
        )
        if invitation is None or invitation.revoquee or invitation.acceptee_le is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation invalide ou déjà utilisée.")
        if invitation.expire_le < maintenant():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cette invitation a expiré.")

        organisation_id = invitation.organisation_id
        role = invitation.role
        invitation.acceptee_le = maintenant()
    else:
        nom_organisation = demande.nom_organisation or f"Organisation de {email.split('@')[0]}"
        organisation = Organisation(
            id=nouvel_id(),
            nom=nom_organisation[:150],
            slug=_slug_disponible(session, _slugifier(nom_organisation)),
        )
        session.add(organisation)
        session.flush()
        organisation_id = organisation.id
        role = RoleMembre.ADMIN.value

    session.add(
        Appartenance(utilisateur_id=utilisateur.id, organisation_id=organisation_id, role=role)
    )
    session.flush()

    journaliser(
        session, ActionJournal.INSCRIPTION,
        organisation_id=organisation_id, utilisateur_id=utilisateur.id,
        email_utilisateur=email, requete=requete,
        detail={"cgu_version": VERSION_CGU},
    )

    jeton_acces = creer_jeton_acces(utilisateur.id, organisation_id, role)
    jeton_rafraichissement = _creer_jeton_rafraichissement(session, utilisateur, requete)
    session.commit()
    session.refresh(utilisateur)

    _poser_cookies(reponse, jeton_acces, jeton_rafraichissement)
    return ReponseConnexion(
        utilisateur=_utilisateur_sortie(session, utilisateur),
        organisation_active=organisation_id,
        jeton_acces=jeton_acces,
        expire_dans_secondes=parametres().duree_jeton_acces_minutes * 60,
    )


@routeur.post("/connexion", response_model=ReponseConnexion)
def connexion(
    demande: DemandeConnexion,
    requete: Request,
    reponse: Response,
    session: Session = Depends(obtenir_session),
) -> ReponseConnexion:
    email = demande.email.lower().strip()
    utilisateur = session.scalar(select(Utilisateur).where(Utilisateur.email == email))

    # Message identique que le compte existe ou non : ne pas révéler quelles adresses
    # sont enregistrées sur le service.
    erreur_generique = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Adresse électronique ou mot de passe incorrect."
    )

    if utilisateur is None:
        journaliser(
            session, ActionJournal.CONNEXION_ECHOUEE,
            email_utilisateur=email, requete=requete, resultat="compte inexistant",
        )
        session.commit()
        raise erreur_generique

    if utilisateur.bloque_jusqua and utilisateur.bloque_jusqua > maintenant():
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Trop de tentatives échouées. Réessayez dans quelques minutes.",
        )

    if not utilisateur.actif or not verifier(demande.mot_de_passe, utilisateur.mot_de_passe_hash):
        utilisateur.tentatives_echouees += 1
        if utilisateur.tentatives_echouees >= TENTATIVES_AVANT_BLOCAGE:
            utilisateur.bloque_jusqua = maintenant() + timedelta(minutes=DUREE_BLOCAGE_MINUTES)
            utilisateur.tentatives_echouees = 0
        journaliser(
            session, ActionJournal.CONNEXION_ECHOUEE,
            utilisateur_id=utilisateur.id, email_utilisateur=email,
            requete=requete, resultat="mot de passe incorrect",
        )
        session.commit()
        raise erreur_generique

    utilisateur.tentatives_echouees = 0
    utilisateur.bloque_jusqua = None
    utilisateur.derniere_connexion = maintenant()

    appartenances = utilisateur.appartenances
    if not appartenances:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ce compte n'est rattaché à aucune organisation.")

    if demande.organisation_id:
        choisie = next((a for a in appartenances if a.organisation_id == demande.organisation_id), None)
        if choisie is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation introuvable.")
    else:
        choisie = appartenances[0]

    journaliser(
        session, ActionJournal.CONNEXION,
        organisation_id=choisie.organisation_id, utilisateur_id=utilisateur.id,
        email_utilisateur=email, requete=requete,
    )

    jeton_acces = creer_jeton_acces(utilisateur.id, choisie.organisation_id, choisie.role)
    jeton_rafraichissement = _creer_jeton_rafraichissement(session, utilisateur, requete)
    session.commit()
    session.refresh(utilisateur)

    _poser_cookies(reponse, jeton_acces, jeton_rafraichissement)
    return ReponseConnexion(
        utilisateur=_utilisateur_sortie(session, utilisateur),
        organisation_active=choisie.organisation_id,
        jeton_acces=jeton_acces,
        expire_dans_secondes=parametres().duree_jeton_acces_minutes * 60,
    )


@routeur.post("/rafraichir", response_model=ReponseConnexion)
def rafraichir(
    requete: Request,
    reponse: Response,
    organisation_id: str | None = None,
    session: Session = Depends(obtenir_session),
) -> ReponseConnexion:
    """Renouvelle le jeton d'accès à partir du jeton de rafraîchissement."""
    jeton_brut = requete.cookies.get(NOM_COOKIE_RAFRAICHISSEMENT)
    if not jeton_brut:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée, reconnectez-vous.")

    enregistrement = session.scalar(
        select(JetonRafraichissement).where(
            JetonRafraichissement.jeton_hash == hacher_jeton(jeton_brut)
        )
    )
    if enregistrement is None or enregistrement.revoque or enregistrement.expire_le < maintenant():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée, reconnectez-vous.")

    utilisateur = session.get(Utilisateur, enregistrement.utilisateur_id)
    if utilisateur is None or not utilisateur.actif:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte introuvable ou désactivé.")

    appartenances = utilisateur.appartenances
    if not appartenances:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ce compte n'est rattaché à aucune organisation.")

    choisie = next(
        (a for a in appartenances if a.organisation_id == organisation_id), appartenances[0]
    ) if organisation_id else appartenances[0]

    # Rotation du jeton de rafraîchissement : l'ancien est révoqué à chaque usage,
    # ce qui limite la fenêtre d'exploitation d'un jeton dérobé.
    enregistrement.revoque = True
    jeton_acces = creer_jeton_acces(utilisateur.id, choisie.organisation_id, choisie.role)
    nouveau_rafraichissement = _creer_jeton_rafraichissement(session, utilisateur, requete)
    session.commit()
    session.refresh(utilisateur)

    _poser_cookies(reponse, jeton_acces, nouveau_rafraichissement)
    return ReponseConnexion(
        utilisateur=_utilisateur_sortie(session, utilisateur),
        organisation_active=choisie.organisation_id,
        jeton_acces=jeton_acces,
        expire_dans_secondes=parametres().duree_jeton_acces_minutes * 60,
    )


@routeur.post("/deconnexion", status_code=status.HTTP_204_NO_CONTENT)
def deconnexion(
    requete: Request,
    reponse: Response,
    session: Session = Depends(obtenir_session),
) -> None:
    jeton_brut = requete.cookies.get(NOM_COOKIE_RAFRAICHISSEMENT)
    if jeton_brut:
        enregistrement = session.scalar(
            select(JetonRafraichissement).where(
                JetonRafraichissement.jeton_hash == hacher_jeton(jeton_brut)
            )
        )
        if enregistrement is not None:
            enregistrement.revoque = True
            journaliser(
                session, ActionJournal.DECONNEXION,
                utilisateur_id=enregistrement.utilisateur_id, requete=requete,
            )
            session.commit()

    reponse.delete_cookie(NOM_COOKIE_ACCES, path="/")
    reponse.delete_cookie(NOM_COOKIE_RAFRAICHISSEMENT, path="/")


@routeur.get("/moi", response_model=UtilisateurSortie)
def moi(
    utilisateur: Utilisateur = Depends(utilisateur_courant),
    session: Session = Depends(obtenir_session),
) -> UtilisateurSortie:
    return _utilisateur_sortie(session, utilisateur)


@routeur.post("/cgu", response_model=UtilisateurSortie)
def accepter_cgu(
    demande: DemandeAcceptationCgu,
    requete: Request,
    ctx: ContexteRequete = Depends(contexte_courant),
) -> UtilisateurSortie:
    """Enregistre l'acceptation des conditions d'utilisation.

    Obligatoire avant toute recherche : c'est la trace que l'utilisateur a reconnu
    le cadre légal d'usage de l'outil.
    """
    ctx.utilisateur.cgu_acceptees_le = maintenant()
    ctx.utilisateur.cgu_version_acceptee = demande.version
    journaliser(
        ctx.session, ActionJournal.CGU_ACCEPTEES,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, requete=requete,
        detail={"version": demande.version},
    )
    ctx.session.commit()
    ctx.session.refresh(ctx.utilisateur)
    return _utilisateur_sortie(ctx.session, ctx.utilisateur)
