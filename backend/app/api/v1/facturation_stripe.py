"""Réception des webhooks Stripe.

Contrairement à Gumroad (abandonné), Stripe signe chaque notification (en-tête
`Stripe-Signature`) avec un secret propre au endpoint webhook, configuré dans le
tableau de bord Stripe : https://dashboard.stripe.com/webhooks
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import parametres
from app.db.session import obtenir_session
from app.modeles.facturation import EvenementStripe
from app.services.facturation_stripe import (
    ErreurStripe,
    enregistrer_evenement,
    traiter_evenement,
    verifier_signature,
)

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/stripe", tags=["Stripe"])


@routeur.post("/webhook")
async def webhook(requete: Request, session: Session = Depends(obtenir_session)) -> dict:
    """Reçoit une notification de paiement, de renouvellement ou de résiliation."""
    charge_brute = await requete.body()
    entete_signature = requete.headers.get("stripe-signature", "")

    try:
        evenement = verifier_signature(charge_brute, entete_signature)
    except ErreurStripe as exc:
        journal.warning("Webhook Stripe rejeté : %s", exc)
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    enregistrement = enregistrer_evenement(session, evenement)
    if enregistrement is None:
        # Déjà reçu (Stripe redélivre parfois le même événement) : accusé réception
        # sans retraiter, pour ne pas réactiver ou résilier deux fois le même abonnement.
        return {"recu": True, "traite": True, "resume": "événement déjà reçu, ignoré"}
    session.flush()

    try:
        resume = traiter_evenement(session, enregistrement)
    except Exception as exc:  # noqa: BLE001
        # Ne jamais renvoyer une erreur à Stripe sur un échec de traitement : il
        # cesserait d'envoyer les notifications suivantes. L'événement reste en base,
        # marqué non traité, et pourra être rejoué.
        journal.exception("Traitement du webhook Stripe en échec")
        enregistrement.erreur_traitement = str(exc)[:1000]
        session.commit()
        return {"recu": True, "traite": False}

    session.commit()
    journal.info("Webhook Stripe traité : %s", resume)
    return {"recu": True, "traite": enregistrement.traite, "resume": resume}


@routeur.post("/rejouer/{evenement_id}")
def rejouer(
    evenement_id: str,
    secret: str = Query(default=""),
    session: Session = Depends(obtenir_session),
) -> dict:
    """Rejoue un événement resté non traité (ex. organisation créée après le paiement).

    Route d'exploitation, pas de bout en bout côté client : protégée par le même
    secret que le webhook plutôt que par l'authentification applicative, faute
    d'interface d'administration dédiée à ce jour.
    """
    attendu = parametres().stripe_webhook_secret
    if not attendu or not hmac.compare_digest(secret, attendu):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Secret invalide.")

    evenement = session.scalar(select(EvenementStripe).where(EvenementStripe.id == evenement_id))
    if evenement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Événement introuvable.")

    evenement.erreur_traitement = None
    resume = traiter_evenement(session, evenement)
    session.commit()
    return {"traite": evenement.traite, "resume": resume}
