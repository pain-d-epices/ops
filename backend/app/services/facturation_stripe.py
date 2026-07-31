"""Intégration Stripe : session de paiement, portail client, traitement des webhooks.

Contrairement à Gumroad (abandonné), Stripe ne pilote pas l'abonnement à notre place :
c'est nous qui créons la session de paiement (Checkout) et la session de gestion
(Billing Portal), et Stripe se contente de nous notifier des changements par webhook.

## Le lien entre un client Stripe et une organisation

Il passe par les métadonnées, posées à la création de la session de paiement
(`organisation_id`, `plan_code`) : Stripe les restitue telles quelles dans chaque
webhook lié à cette session ou à l'abonnement qui en découle. Pas de correspondance
par email à deviner, contrairement au schéma Gumroad précédent — plus robuste, et
plus simple.

## Sécurité du webhook

Stripe signe chaque notification (en-tête `Stripe-Signature`) avec un secret propre à
l'endpoint, configuré dans son tableau de bord. Sans cette vérification, n'importe qui
connaissant l'URL du webhook pourrait s'attribuer un abonnement gratuitement en
forgeant une notification.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import parametres
from app.db.base import maintenant
from app.facturation.abonnements import activer_abonnement, resilier_abonnements
from app.modeles.enums import StatutAbonnement
from app.modeles.facturation import Abonnement, EvenementStripe, Plan
from app.modeles.organisation import Organisation

journal = logging.getLogger(__name__)

# Événements qui résilient l'abonnement local
EVENEMENTS_RESILIATION = {"customer.subscription.deleted"}


class ErreurStripe(Exception):
    """Échec de communication, de configuration ou de vérification côté Stripe."""


def _preparer_client() -> None:
    cle = parametres().stripe_cle_secrete
    if not cle:
        raise ErreurStripe("Stripe n'est pas configuré sur ce serveur (STRIPE_CLE_SECRETE absente).")
    stripe.api_key = cle


def plan_depuis_prix(session: Session, price_id: str) -> Plan | None:
    """Retrouve le plan interne correspondant à un prix Stripe.

    Deux sources : la colonne `plans.stripe_price_id`, sinon la correspondance
    déclarée dans le .env (STRIPE_PRIX) — même schéma à deux voies que l'intégration
    Gumroad précédente, pour les mêmes raisons (configurer par l'admin en base sans
    redéployer, ou par variable d'environnement selon l'environnement).
    """
    plan = session.scalar(select(Plan).where(Plan.stripe_price_id == price_id))
    if plan is not None:
        return plan
    code = parametres().correspondance_prix_stripe.get(price_id)
    if code:
        return session.scalar(select(Plan).where(Plan.code == code))
    return None


def creer_session_paiement(organisation: Organisation, plan: Plan, email_acheteur: str) -> str:
    """Crée une session Stripe Checkout pour souscrire à `plan`. Rend l'URL à
    laquelle rediriger le client."""
    _preparer_client()
    if not plan.stripe_price_id:
        raise ErreurStripe(f"Aucun prix Stripe associé au plan {plan.code}.")

    params = parametres()
    metadonnees = {"organisation_id": organisation.id, "plan_code": plan.code}
    try:
        session_paiement = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
            customer_email=email_acheteur,
            client_reference_id=organisation.id,
            metadata=metadonnees,
            # Répétée sur la souscription elle-même : les webhooks `customer.subscription.*`
            # portent l'abonnement, pas la session de paiement, et n'auraient sinon pas
            # accès à ces métadonnées.
            subscription_data={"metadata": metadonnees},
            success_url=params.stripe_url_retour_succes,
            cancel_url=params.stripe_url_retour_annulation,
        )
    except stripe.StripeError as exc:
        raise ErreurStripe(f"Stripe injoignable ou requête refusée : {exc}") from exc

    if not session_paiement.url:
        raise ErreurStripe("Stripe n'a pas renvoyé d'URL de paiement.")
    return session_paiement.url


def creer_session_portail(organisation_id: str, session: Session) -> str:
    """Crée une session du portail client Stripe (moyen de paiement, factures,
    annulation). Exige qu'un abonnement Stripe existe déjà pour l'organisation."""
    _preparer_client()
    abonnement = session.scalar(
        select(Abonnement)
        .where(
            Abonnement.organisation_id == organisation_id,
            Abonnement.stripe_customer_id.is_not(None),
        )
        .order_by(Abonnement.created_at.desc())
    )
    if abonnement is None or not abonnement.stripe_customer_id:
        raise ErreurStripe(
            "Aucun abonnement Stripe pour cette organisation. Passez d'abord par le paiement."
        )
    try:
        session_portail = stripe.billing_portal.Session.create(
            customer=abonnement.stripe_customer_id,
            return_url=parametres().stripe_url_retour_portail,
        )
    except stripe.StripeError as exc:
        raise ErreurStripe(f"Stripe injoignable ou requête refusée : {exc}") from exc
    return session_portail.url


def verifier_signature(charge_brute: bytes, entete_signature: str) -> dict[str, Any]:
    """Vérifie la signature du webhook et rend l'événement décodé."""
    secret = parametres().stripe_webhook_secret
    if not secret:
        raise ErreurStripe("Secret de webhook Stripe non configuré.")
    try:
        return dict(stripe.Webhook.construct_event(charge_brute, entete_signature, secret))
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise ErreurStripe(f"Signature de webhook invalide : {exc}") from exc


def enregistrer_evenement(session: Session, evenement: dict[str, Any]) -> EvenementStripe | None:
    """Journalise l'événement brut avant traitement.

    Rend None si l'identifiant d'événement a déjà été reçu : Stripe garantit une
    livraison *au moins une fois*, un même événement peut donc arriver plusieurs fois,
    et le retraiter re-résilierait ou re-activerait un abonnement sans raison.
    """
    stripe_event_id = evenement.get("id")
    if stripe_event_id and session.scalar(
        select(EvenementStripe.id).where(EvenementStripe.stripe_event_id == stripe_event_id)
    ):
        return None

    objet = (evenement.get("data") or {}).get("object") or {}
    enregistrement = EvenementStripe(
        type_evenement=str(evenement.get("type") or "inconnu"),
        stripe_event_id=stripe_event_id,
        stripe_customer_id=objet.get("customer"),
        stripe_subscription_id=(
            objet.get("subscription") or (objet.get("id") if objet.get("object") == "subscription" else None)
        ),
        charge_utile=evenement,
        traite=False,
        recu_le=maintenant(),
    )
    session.add(enregistrement)
    return enregistrement


def traiter_evenement(session: Session, evenement_modele: EvenementStripe) -> str:
    """Applique l'effet d'un webhook sur les abonnements. Retourne un résumé lisible."""
    charge = evenement_modele.charge_utile or {}
    type_evenement = evenement_modele.type_evenement
    objet = (charge.get("data") or {}).get("object") or {}

    if type_evenement == "checkout.session.completed":
        return _traiter_paiement_complete(session, evenement_modele, objet)

    if type_evenement in EVENEMENTS_RESILIATION:
        nombre = resilier_abonnements(session, stripe_subscription_id=objet.get("id"))
        evenement_modele.traite = True
        return f"{nombre} abonnement(s) résilié(s)."

    if type_evenement == "customer.subscription.updated":
        return _traiter_mise_a_jour_abonnement(session, evenement_modele, objet)

    evenement_modele.traite = True
    return f"Événement {type_evenement} reçu, sans effet attendu sur les abonnements."


def _traiter_paiement_complete(session: Session, evenement_modele: EvenementStripe, objet: dict[str, Any]) -> str:
    metadonnees = objet.get("metadata") or {}
    organisation_id = metadonnees.get("organisation_id")
    plan_code = metadonnees.get("plan_code")

    if not organisation_id or not plan_code:
        evenement_modele.erreur_traitement = "Métadonnée organisation_id ou plan_code absente de la session."
        return evenement_modele.erreur_traitement

    organisation = session.get(Organisation, organisation_id)
    if organisation is None:
        evenement_modele.erreur_traitement = f"Organisation {organisation_id} introuvable."
        return evenement_modele.erreur_traitement

    plan = session.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None:
        evenement_modele.erreur_traitement = f"Plan {plan_code} introuvable."
        return evenement_modele.erreur_traitement

    activer_abonnement(
        session, organisation, plan,
        stripe_customer_id=objet.get("customer"),
        stripe_subscription_id=objet.get("subscription"),
        stripe_price_id=plan.stripe_price_id,
    )
    evenement_modele.traite = True
    return f"Plan {plan.code} activé pour l'organisation {organisation.slug}."


def _traiter_mise_a_jour_abonnement(session: Session, evenement_modele: EvenementStripe, objet: dict[str, Any]) -> str:
    """Corrige la date de fin de période et le renouvellement automatique.

    `activer_abonnement` ne pose qu'une estimation de fin de période à 31 jours,
    faute de mieux au moment du paiement ; cet événement porte la valeur exacte
    calculée par Stripe.
    """
    subscription_id = objet.get("id")
    abonnement = session.scalar(
        select(Abonnement).where(
            Abonnement.stripe_subscription_id == subscription_id,
            Abonnement.statut == StatutAbonnement.ACTIF.value,
        )
    )
    if abonnement is None:
        evenement_modele.erreur_traitement = f"Aucun abonnement actif pour la souscription {subscription_id}."
        return evenement_modele.erreur_traitement

    fin = objet.get("current_period_end")
    if fin:
        abonnement.periode_fin = datetime.fromtimestamp(fin, tz=timezone.utc)
    abonnement.renouvellement_automatique = not objet.get("cancel_at_period_end", False)
    abonnement.derniere_verification = maintenant()
    evenement_modele.traite = True
    return f"Abonnement {subscription_id} mis à jour."
