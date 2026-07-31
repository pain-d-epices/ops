"""Endpoints d'authentification, d'inscription et de gestion de session."""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import config_metier, parametres
from app.db.base import maintenant, nouvel_id
from app.db.session import obtenir_session
from app.facturation.abonnements import plan_actif
from app.infra.limiteur_entrant import (
    adresse_client,
    exiger_debit,
    limiteur_entrant,
)
from app.modeles.enums import ActionJournal, RoleMembre
from app.modeles.organisation import Appartenance, Invitation, Organisation
from app.modeles.utilisateur import JetonRafraichissement, Utilisateur
from app.schemas.auth import (
    ActivationTotpSortie,
    DemandeAcceptationCgu,
    DemandeActivationTotp,
    DemandeConnexion,
    DemandeDesactivationTotp,
    DemandeInscription,
    EtatTotpSortie,
    OrganisationResumee,
    ReponseConnexion,
    UtilisateurSortie,
)
from app.securite.anti_bot import PreuveInvalide, creer_defi, verifier_preuve
from app.securite.dependances import (
    NOM_COOKIE_ACCES,
    NOM_COOKIE_RAFRAICHISSEMENT,
    ContexteRequete,
    contexte_courant,
    utilisateur_courant,
)
from app.securite.domaines_jetables import est_domaine_jetable
from app.securite.jetons import creer_jeton_acces
from app.securite.mots_de_passe import (
    MotDePasseInvalide,
    generer_jeton_aleatoire,
    hacher,
    hacher_jeton,
    valider_politique,
    verifier,
)
from app.securite.totp import (
    TotpRequis,
    chiffrer_secret,
    code_valide,
    dechiffrer_secret,
    generer_codes_secours,
    generer_secret,
    qr_code_base64,
    uri_provisionnement,
)
from app.services.journal import journaliser

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/auth", tags=["Authentification"])

VERSION_CGU = "1.0"
# Après ce nombre d'échecs, le compte est temporairement bloqué (anti-force brute)
TENTATIVES_AVANT_BLOCAGE = 8
DUREE_BLOCAGE_MINUTES = 15

#: Plafond par défaut de créations d'organisation depuis une même adresse IP, par
#: 24 heures. Le palier gratuit offrant 15 recherches par mois, sans ce plafond un
#: script obtiendrait un volume illimité en multipliant les comptes.
COMPTES_PAR_IP_PAR_JOUR = 3
FENETRE_COMPTES_SECONDES = 24 * 3600


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


def _verifier_totp(utilisateur: Utilisateur, code: str | None) -> bool:
    """Valide un code TOTP, ou à défaut un code de secours (qui est alors consommé
    sur l'objet ; l'appelant reste responsable du commit)."""
    if not code:
        return False
    secret = dechiffrer_secret(utilisateur.totp_secret or "")
    if secret and code_valide(secret, code):
        return True

    empreinte = hacher_jeton(code.strip())
    if empreinte in (utilisateur.totp_codes_secours or []):
        utilisateur.totp_codes_secours = [
            c for c in utilisateur.totp_codes_secours if c != empreinte
        ]
        return True
    return False


def _verifier_plafond_creation(requete: Request, email: str, session: Session) -> None:
    """Refuse la création d'une organisation de plus depuis une IP trop active.

    Le compteur est incrémenté même quand la création finit par échouer pour une autre
    raison : sinon, un script sonderait les adresses déjà prises sans jamais consommer
    son plafond.
    """
    if not config_metier().obtenir("anti_abus.actif", True):
        return
    plafond = int(
        config_metier().obtenir("anti_abus.comptes_par_ip_par_jour", COMPTES_PAR_IP_PAR_JOUR)
    )
    if plafond <= 0:
        return

    ip = adresse_client(requete)
    total = limiteur_entrant().compter("inscription", ip, FENETRE_COMPTES_SECONDES)
    if total > plafond:
        journal.warning(
            "Plafond de création de comptes atteint depuis %s (%d tentatives) — refus pour %s",
            ip, total, email,
        )
        journaliser(
            session, ActionJournal.CONNEXION_ECHOUEE,
            email_utilisateur=email, requete=requete,
            resultat="plafond de création de comptes par IP atteint",
        )
        session.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Trop de comptes ont été créés depuis cette connexion aujourd'hui. "
            "Réessayez demain, ou contactez-nous si vous équipez une équipe.",
        )


@routeur.get("/defi-anti-robot", dependencies=[Depends(exiger_debit("defi"))])
def defi_anti_robot() -> dict:
    """Fournit l'épreuve à résoudre avant de pouvoir créer un compte.

    Le formulaire d'inscription la demande au chargement et la résout en arrière-plan,
    de sorte que l'utilisateur n'attend jamais : la solution est prête avant qu'il ait
    fini de saisir son mot de passe. Voir `app/securite/anti_bot.py` pour le principe.
    """
    defi = creer_defi()
    return {
        "algorithm": defi.algorithm,
        "challenge": defi.challenge,
        "salt": defi.salt,
        "signature": defi.signature,
        "maxnumber": defi.maxnumber,
    }


@routeur.post(
    "/inscription",
    response_model=ReponseConnexion,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exiger_debit("inscription"))],
)
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

    # --- Protections anti-automatisation ---
    # Contrôlées avant toute écriture, et avant même l'unicité de l'adresse : cette
    # route est la porte d'entrée du palier gratuit, donc la cible naturelle d'un
    # script cherchant à multiplier les quotas.
    try:
        verifier_preuve(demande.preuve_anti_robot)
    except PreuveInvalide as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if est_domaine_jetable(email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Les adresses électroniques jetables ne sont pas acceptées. "
            "Utilisez une adresse permanente.",
        )

    # Le plafond ne porte que sur la création d'une **organisation** : rejoindre une
    # organisation existante sur invitation n'ouvre aucun quota supplémentaire, et
    # plusieurs collègues partagent souvent la même adresse IP.
    if not demande.jeton_invitation:
        _verifier_plafond_creation(requete, email, session)

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


@routeur.post(
    "/connexion",
    response_model=ReponseConnexion,
    # Le verrou par compte (8 échecs) ne protège pas d'un balayage de nombreuses
    # adresses depuis une même origine : chaque compte reste sous son seuil. La limite
    # par IP couvre ce cas.
    dependencies=[Depends(exiger_debit("connexion"))],
)
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

    if utilisateur.totp_actif:
        if not _verifier_totp(utilisateur, demande.code_totp):
            manque_code = not demande.code_totp
            # Un code manquant n'est pas une tentative échouée (c'est le premier appel,
            # celui qui déclenche l'affichage du champ de code côté client) : seul un
            # code présent mais faux compte pour le verrou anti-force-brute.
            if not manque_code:
                utilisateur.tentatives_echouees += 1
                if utilisateur.tentatives_echouees >= TENTATIVES_AVANT_BLOCAGE:
                    utilisateur.bloque_jusqua = maintenant() + timedelta(minutes=DUREE_BLOCAGE_MINUTES)
                    utilisateur.tentatives_echouees = 0
            journaliser(
                session, ActionJournal.CONNEXION_ECHOUEE,
                utilisateur_id=utilisateur.id, email_utilisateur=email,
                requete=requete, resultat="code de vérification à deux facteurs invalide",
            )
            session.commit()
            if manque_code:
                raise TotpRequis()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code de vérification incorrect.")
        session.commit()  # persiste la consommation d'un éventuel code de secours

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


# --- Authentification à deux facteurs (TOTP) --------------------------------


@routeur.get("/2fa", response_model=EtatTotpSortie)
def etat_totp(utilisateur: Utilisateur = Depends(utilisateur_courant)) -> EtatTotpSortie:
    return EtatTotpSortie(
        actif=utilisateur.totp_actif,
        codes_secours_restants=len(utilisateur.totp_codes_secours or []),
    )


@routeur.post("/2fa/activer", response_model=ActivationTotpSortie)
def activer_totp(
    ctx: ContexteRequete = Depends(contexte_courant),
) -> ActivationTotpSortie:
    """Démarre l'activation : génère un secret et des codes de secours, mais
    n'active rien tant que `/2fa/confirmer` n'a pas vérifié un code réel.

    Rappeler cette route avant confirmation régénère secret et codes, sans effet de
    bord : rien n'était encore actif.
    """
    if ctx.utilisateur.totp_actif:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "La double authentification est déjà active. Désactivez-la avant d'en "
            "reconfigurer une nouvelle.",
        )

    secret = generer_secret()
    codes_secours = generer_codes_secours()

    ctx.utilisateur.totp_secret = chiffrer_secret(secret)
    ctx.utilisateur.totp_codes_secours = [hacher_jeton(c) for c in codes_secours]
    ctx.session.commit()

    return ActivationTotpSortie(
        secret=secret,
        qr_code_base64=qr_code_base64(uri_provisionnement(secret, ctx.utilisateur.email)),
        codes_secours=codes_secours,
    )


@routeur.post("/2fa/confirmer", response_model=EtatTotpSortie)
def confirmer_totp(
    demande: DemandeActivationTotp,
    requete: Request,
    ctx: ContexteRequete = Depends(contexte_courant),
) -> EtatTotpSortie:
    """Confirme l'activation démarrée par `/2fa/activer` avec un code réellement
    généré par l'application d'authentification."""
    if ctx.utilisateur.totp_actif:
        raise HTTPException(status.HTTP_409_CONFLICT, "La double authentification est déjà active.")

    secret = dechiffrer_secret(ctx.utilisateur.totp_secret or "")
    if not secret:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Aucune activation en cours. Appelez d'abord /auth/2fa/activer.",
        )
    if not code_valide(secret, demande.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code incorrect. Vérifiez l'heure de votre appareil.")

    ctx.utilisateur.totp_actif = True
    journaliser(
        ctx.session, ActionJournal.TOTP_ACTIVE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, requete=requete,
    )
    ctx.session.commit()
    return EtatTotpSortie(actif=True, codes_secours_restants=len(ctx.utilisateur.totp_codes_secours or []))


@routeur.post("/2fa/desactiver", response_model=EtatTotpSortie)
def desactiver_totp(
    demande: DemandeDesactivationTotp,
    requete: Request,
    ctx: ContexteRequete = Depends(contexte_courant),
) -> EtatTotpSortie:
    """Désactive la double authentification.

    Exige le mot de passe **et** un code valide : la 2FA protège justement contre
    un mot de passe compromis seul, la désactiver ne doit pas être possible avec le
    seul mot de passe si celui-ci a fuité.
    """
    if not verifier(demande.mot_de_passe, ctx.utilisateur.mot_de_passe_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Mot de passe incorrect.")
    if not ctx.utilisateur.totp_actif or not _verifier_totp(ctx.utilisateur, demande.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code de vérification incorrect.")

    ctx.utilisateur.totp_actif = False
    ctx.utilisateur.totp_secret = None
    ctx.utilisateur.totp_codes_secours = []
    journaliser(
        ctx.session, ActionJournal.TOTP_DESACTIVE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, requete=requete,
    )
    ctx.session.commit()
    return EtatTotpSortie(actif=False, codes_secours_restants=0)
