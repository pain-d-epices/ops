"""Intégration Gumroad : vérification de licence et traitement des webhooks.

Gumroad est *merchant of record* : il encaisse et gère la TVA à notre place. En
contrepartie, il ne pilote pas les abonnements depuis notre application — le lien
entre un achat et une organisation se fait par **clé de licence**.

Deux voies d'activation, volontairement redondantes :
  1. le webhook (« ping ») envoyé par Gumroad à chaque vente ou annulation ;
  2. la saisie manuelle de la clé par le client dans l'application.

Le webhook Gumroad n'offre aucune garantie de réémission en cas d'échec : sans la
seconde voie, un client ayant payé pourrait rester bloqué sur le palier gratuit.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import parametres
from app.db.base import maintenant
from app.modeles.enums import StatutAbonnement
from app.modeles.facturation import Abonnement, EvenementGumroad, Plan
from app.modeles.organisation import Appartenance, Organisation
from app.modeles.utilisateur import Utilisateur

journal = logging.getLogger(__name__)

URL_VERIFICATION = "https://api.gumroad.com/v2/licenses/verify"

# Événements Gumroad qui retirent l'accès payant
EVENEMENTS_RESILIATION = {"cancellation", "subscription_ended", "refund", "dispute"}


class ErreurGumroad(Exception):
    """Échec de communication ou de validation côté Gumroad."""


class LicenceInvalide(Exception):
    """La clé de licence est inconnue, remboursée ou annulée."""


def verifier_licence(product_id: str, cle_licence: str, incrementer: bool = False) -> dict[str, Any]:
    """Interroge l'API Gumroad pour valider une clé de licence.

    `incrementer=False` : ne pas incrémenter le compteur d'utilisations, sinon chaque
    revérification périodique gonflerait artificiellement le nombre d'activations.
    """
    try:
        reponse = httpx.post(
            URL_VERIFICATION,
            data={
                "product_id": product_id,
                "license_key": cle_licence,
                "increment_uses_count": "true" if incrementer else "false",
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise ErreurGumroad(f"Gumroad injoignable : {exc}") from exc

    if reponse.status_code == 404:
        raise LicenceInvalide("Clé de licence inconnue pour ce produit.")
    if reponse.status_code >= 400:
        raise ErreurGumroad(f"Réponse Gumroad inattendue ({reponse.status_code}).")

    donnees = reponse.json()
    if not donnees.get("success"):
        raise LicenceInvalide(donnees.get("message", "Licence refusée par Gumroad."))

    achat = donnees.get("purchase", {})
    if achat.get("refunded") or achat.get("chargebacked"):
        raise LicenceInvalide("Cet achat a été remboursé.")
    if achat.get("subscription_cancelled_at") or achat.get("subscription_failed_at"):
        raise LicenceInvalide("Cet abonnement a été annulé.")

    return achat


def plan_depuis_produit(session: Session, gumroad_product_id: str) -> Plan | None:
    """Retrouve le plan interne correspondant à un produit Gumroad.

    Deux sources : la colonne `gumroad_product_id` de la table plans, sinon la
    correspondance déclarée dans le .env (GUMROAD_PRODUITS).
    """
    plan = session.scalar(select(Plan).where(Plan.gumroad_product_id == gumroad_product_id))
    if plan is not None:
        return plan

    code = parametres().correspondance_produits_gumroad.get(gumroad_product_id)
    if code:
        return session.scalar(select(Plan).where(Plan.code == code))
    return None


def activer_abonnement(
    session: Session,
    organisation: Organisation,
    plan: Plan,
    *,
    cle_licence: str | None = None,
    gumroad_product_id: str | None = None,
    gumroad_sale_id: str | None = None,
    email_acheteur: str | None = None,
    duree_jours: int = 31,
) -> Abonnement:
    """Active un plan pour une organisation et clôt l'abonnement précédent.

    Une organisation n'a jamais deux abonnements actifs simultanément : l'ancien passe
    en « annulé », ce qui évite toute ambiguïté sur le plan réellement applicable.
    """
    anciens = session.scalars(
        select(Abonnement).where(
            Abonnement.organisation_id == organisation.id,
            Abonnement.statut == StatutAbonnement.ACTIF.value,
        )
    ).all()
    for ancien in anciens:
        ancien.statut = StatutAbonnement.ANNULE.value

    debut = maintenant()
    abonnement = Abonnement(
        organisation_id=organisation.id,
        plan_id=plan.id,
        statut=StatutAbonnement.ACTIF.value,
        periode_debut=debut,
        periode_fin=debut + timedelta(days=duree_jours),
        gumroad_license_key=cle_licence,
        gumroad_product_id=gumroad_product_id or plan.gumroad_product_id,
        gumroad_sale_id=gumroad_sale_id,
        gumroad_email_acheteur=email_acheteur,
        derniere_verification=debut,
    )
    session.add(abonnement)
    journal.info("Abonnement %s activé pour l'organisation %s", plan.code, organisation.slug)
    return abonnement


def resilier_abonnements(session: Session, *, cle_licence: str | None, sale_id: str | None) -> int:
    """Passe en « annulé » les abonnements correspondant à une licence ou une vente."""
    if not cle_licence and not sale_id:
        return 0

    conditions = []
    if cle_licence:
        conditions.append(Abonnement.gumroad_license_key == cle_licence)
    if sale_id:
        conditions.append(Abonnement.gumroad_sale_id == sale_id)

    from sqlalchemy import or_

    abonnements = session.scalars(
        select(Abonnement).where(
            Abonnement.statut == StatutAbonnement.ACTIF.value,
            or_(*conditions),
        )
    ).all()
    for abo in abonnements:
        abo.statut = StatutAbonnement.ANNULE.value
        abo.periode_fin = maintenant()
    return len(abonnements)


def _organisation_depuis_email(session: Session, email: str) -> Organisation | None:
    """Retrouve l'organisation d'un acheteur à partir de son email.

    On ne retient que les organisations où l'utilisateur est administrateur : un
    analyste ne doit pas pouvoir changer le plan de l'organisation par un achat perso.
    """
    utilisateur = session.scalar(select(Utilisateur).where(Utilisateur.email == email.lower().strip()))
    if utilisateur is None:
        return None
    appartenance = session.scalar(
        select(Appartenance).where(
            Appartenance.utilisateur_id == utilisateur.id,
            Appartenance.role == "admin",
        )
    )
    if appartenance is None:
        return None
    return session.get(Organisation, appartenance.organisation_id)


def enregistrer_evenement(session: Session, charge: dict[str, Any]) -> EvenementGumroad:
    """Journalise le webhook brut avant tout traitement.

    Conserver la charge utile telle quelle permet de rejouer un événement mal traité
    et de prouver l'historique d'un abonnement en cas de litige.
    """
    evenement = EvenementGumroad(
        type_evenement=_deduire_type(charge),
        gumroad_sale_id=charge.get("sale_id"),
        gumroad_license_key=charge.get("license_key"),
        email=charge.get("email"),
        charge_utile=charge,
        traite=False,
        recu_le=maintenant(),
    )
    session.add(evenement)
    return evenement


def _deduire_type(charge: dict[str, Any]) -> str:
    """Détermine la nature de l'événement à partir des champs présents.

    Gumroad n'envoie pas de champ « type » explicite sur ses pings : la nature de
    l'événement se lit dans les drapeaux de la charge utile.
    """
    if str(charge.get("refunded", "")).lower() == "true":
        return "refund"
    if str(charge.get("disputed", "")).lower() == "true":
        return "dispute"
    if charge.get("cancelled") or charge.get("subscription_cancelled_at"):
        return "cancellation"
    if charge.get("subscription_ended_at"):
        return "subscription_ended"
    if charge.get("alert_name"):
        return str(charge["alert_name"])
    return "sale"


def traiter_evenement(session: Session, evenement: EvenementGumroad) -> str:
    """Applique l'effet d'un webhook sur les abonnements. Retourne un résumé lisible."""
    charge = evenement.charge_utile or {}
    type_evenement = evenement.type_evenement

    if type_evenement in EVENEMENTS_RESILIATION:
        nombre = resilier_abonnements(
            session,
            cle_licence=charge.get("license_key"),
            sale_id=charge.get("sale_id"),
        )
        evenement.traite = True
        return f"{nombre} abonnement(s) résilié(s)."

    product_id = charge.get("product_id") or charge.get("product_permalink")
    email = charge.get("email")
    if not product_id or not email:
        evenement.erreur_traitement = "Charge utile incomplète (product_id ou email manquant)."
        return evenement.erreur_traitement

    plan = plan_depuis_produit(session, str(product_id))
    if plan is None:
        evenement.erreur_traitement = f"Aucun plan interne associé au produit Gumroad {product_id}."
        return evenement.erreur_traitement

    organisation = _organisation_depuis_email(session, str(email))
    if organisation is None:
        # Cas normal : le client achète avant de créer son compte. L'événement reste
        # en attente et le client activera lui-même sa clé de licence dans l'application.
        evenement.erreur_traitement = (
            f"Aucune organisation administrée par {email} ; "
            "activation en attente de la saisie de la clé de licence."
        )
        return evenement.erreur_traitement

    activer_abonnement(
        session,
        organisation,
        plan,
        cle_licence=charge.get("license_key"),
        gumroad_product_id=str(product_id),
        gumroad_sale_id=charge.get("sale_id"),
        email_acheteur=str(email),
    )
    evenement.traite = True
    return f"Plan {plan.code} activé pour l'organisation {organisation.slug}."
