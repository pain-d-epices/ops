"""Réception des webhooks Gumroad.

Gumroad ne signe pas ses notifications : l'authentification repose sur un secret
partagé placé dans l'URL du webhook, configurée dans le tableau de bord Gumroad :

    https://votre-domaine.fr/api/v1/gumroad/webhook?secret=VOTRE_SECRET

L'événement est d'abord enregistré brut, puis traité. Ainsi, même si le traitement
échoue, la preuve de la vente est conservée et l'événement peut être rejoué.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import parametres
from app.db.session import obtenir_session
from app.modeles.facturation import EvenementGumroad
from app.services.gumroad import enregistrer_evenement, traiter_evenement

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/gumroad", tags=["Gumroad"])


@routeur.post("/webhook")
async def webhook(
    requete: Request,
    secret: str = Query(default=""),
    session: Session = Depends(obtenir_session),
) -> dict:
    """Reçoit une notification de vente, d'annulation ou de remboursement."""
    attendu = parametres().gumroad_webhook_secret
    # Comparaison à temps constant : évite de laisser deviner le secret caractère
    # par caractère en mesurant le temps de réponse.
    if not attendu or not hmac.compare_digest(secret, attendu):
        journal.warning("Webhook Gumroad rejeté : secret invalide")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Secret invalide.")

    # Gumroad envoie du form-urlencoded, pas du JSON
    formulaire = await requete.form()
    charge = {cle: str(valeur) for cle, valeur in formulaire.items()}

    if not charge:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Charge utile vide.")

    evenement = enregistrer_evenement(session, charge)
    session.flush()

    try:
        resume = traiter_evenement(session, evenement)
    except Exception as exc:  # noqa: BLE001
        # Ne jamais renvoyer une erreur à Gumroad sur un échec de traitement : il
        # cesserait d'envoyer les notifications suivantes. L'événement reste en base,
        # marqué non traité, et pourra être rejoué.
        journal.exception("Traitement du webhook Gumroad en échec")
        evenement.erreur_traitement = str(exc)[:1000]
        session.commit()
        return {"recu": True, "traite": False}

    session.commit()
    journal.info("Webhook Gumroad traité : %s", resume)
    return {"recu": True, "traite": evenement.traite, "resume": resume}


@routeur.post("/rejouer/{evenement_id}")
def rejouer(
    evenement_id: str,
    secret: str = Query(default=""),
    session: Session = Depends(obtenir_session),
) -> dict:
    """Rejoue un événement resté non traité (par exemple : achat antérieur à la
    création du compte client)."""
    attendu = parametres().gumroad_webhook_secret
    if not attendu or not hmac.compare_digest(secret, attendu):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Secret invalide.")

    evenement = session.scalar(select(EvenementGumroad).where(EvenementGumroad.id == evenement_id))
    if evenement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Événement introuvable.")

    evenement.erreur_traitement = None
    resume = traiter_evenement(session, evenement)
    session.commit()
    return {"traite": evenement.traite, "resume": resume}
