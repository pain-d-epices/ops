"""Dépendances FastAPI : utilisateur courant, organisation courante, rôles, plan actif.

C'est ici que se joue l'isolation entre clients. Toute route manipulant des données
d'investigation doit dépendre de `contexte_courant`, qui garantit que l'utilisateur
appartient bien à l'organisation dont il réclame les données.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import obtenir_session
from app.facturation.abonnements import plan_actif
from app.modeles.enums import RoleMembre, StatutOrganisation
from app.modeles.facturation import Plan
from app.modeles.organisation import Appartenance, Organisation
from app.modeles.utilisateur import Utilisateur
from app.securite.jetons import ContenuJeton, JetonInvalide, decoder_jeton_acces

NOM_COOKIE_ACCES = "searcher_acces"
NOM_COOKIE_RAFRAICHISSEMENT = "searcher_rafraichissement"

# Hiérarchie des rôles : un admin peut tout ce que peut un analyste, etc.
NIVEAU_ROLE = {
    RoleMembre.LECTEUR.value: 1,
    RoleMembre.ANALYSTE.value: 2,
    RoleMembre.ADMIN.value: 3,
}


@dataclass
class ContexteRequete:
    """Tout ce dont un endpoint a besoin pour décider s'il peut agir, et pour qui."""

    utilisateur: Utilisateur
    organisation: Organisation
    appartenance: Appartenance
    plan: Plan
    session: Session

    @property
    def organisation_id(self) -> str:
        return self.organisation.id

    @property
    def role(self) -> str:
        return self.appartenance.role

    def a_le_role(self, minimum: str) -> bool:
        return NIVEAU_ROLE.get(self.role, 0) >= NIVEAU_ROLE.get(minimum, 99)


def _extraire_jeton(requete: Request, autorisation: str | None) -> str:
    """Récupère le jeton d'accès, en priorité depuis le cookie httpOnly.

    L'en-tête Authorization reste accepté pour les intégrations serveur à serveur
    (accès API des plans Pro et Entreprise).
    """
    jeton = requete.cookies.get(NOM_COOKIE_ACCES)
    if jeton:
        return jeton
    if autorisation and autorisation.lower().startswith("bearer "):
        return autorisation[7:].strip()
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise.")


def contenu_jeton_courant(
    requete: Request,
    autorisation: str | None = Header(default=None, alias="Authorization"),
) -> ContenuJeton:
    try:
        return decoder_jeton_acces(_extraire_jeton(requete, autorisation))
    except JetonInvalide as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


def utilisateur_courant(
    contenu: ContenuJeton = Depends(contenu_jeton_courant),
    session: Session = Depends(obtenir_session),
) -> Utilisateur:
    utilisateur = session.get(Utilisateur, contenu.utilisateur_id)
    if utilisateur is None or not utilisateur.actif:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte introuvable ou désactivé.")
    return utilisateur


def contexte_courant(
    requete: Request,
    contenu: ContenuJeton = Depends(contenu_jeton_courant),
    session: Session = Depends(obtenir_session),
    organisation_entete: str | None = Header(default=None, alias="X-Organisation"),
) -> ContexteRequete:
    """Contexte complet de la requête, avec vérification stricte de l'appartenance.

    L'organisation peut être précisée par l'en-tête X-Organisation (utile quand un
    utilisateur appartient à plusieurs organisations), mais l'appartenance est
    **toujours** revérifiée en base : le contenu du jeton ne fait jamais autorité.
    """
    utilisateur = session.get(Utilisateur, contenu.utilisateur_id)
    if utilisateur is None or not utilisateur.actif:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte introuvable ou désactivé.")

    organisation_id = organisation_entete or contenu.organisation_id
    if not organisation_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucune organisation active.")

    appartenance = session.scalar(
        select(Appartenance).where(
            Appartenance.utilisateur_id == utilisateur.id,
            Appartenance.organisation_id == organisation_id,
        )
    )
    if appartenance is None:
        # Même message et même code qu'une ressource absente : ne pas révéler
        # l'existence d'une organisation à quelqu'un qui n'en fait pas partie.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation introuvable.")

    organisation = session.get(Organisation, organisation_id)
    if organisation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation introuvable.")
    if organisation.statut == StatutOrganisation.SUSPENDUE.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cette organisation est suspendue.")

    return ContexteRequete(
        utilisateur=utilisateur,
        organisation=organisation,
        appartenance=appartenance,
        plan=plan_actif(session, organisation_id),
        session=session,
    )


def exiger_role(minimum: str):
    """Fabrique une dépendance imposant un rôle minimal.

    Exemple :  ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ADMIN.value))
    """

    def verificateur(ctx: ContexteRequete = Depends(contexte_courant)) -> ContexteRequete:
        if not ctx.a_le_role(minimum):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Action réservée au rôle « {minimum} » ou supérieur.",
            )
        return ctx

    return verificateur


def exiger_cgu(ctx: ContexteRequete = Depends(contexte_courant)) -> ContexteRequete:
    """Bloque l'accès tant que les conditions d'utilisation n'ont pas été acceptées.

    Appliqué aux routes qui déclenchent une recherche : l'utilisateur doit avoir
    explicitement reconnu le cadre légal d'usage avant de rechercher une personne.
    """
    if not ctx.utilisateur.a_accepte_cgu:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Vous devez accepter les conditions d'utilisation avant de lancer une recherche.",
        )
    return ctx
