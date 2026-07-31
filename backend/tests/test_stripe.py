"""Tests de l'intégration Stripe : endpoints de paiement et traitement des webhooks.

Aucune clé Stripe n'est configurée dans l'environnement de test (comme en
développement, avant la création du compte Stripe — voir REPRISE.md) : les tests
d'endpoints vérifient donc le comportement de repli (503, pas de plantage), et la
logique de traitement des webhooks est testée directement, en contournant la
vérification de signature qui exige un vrai secret Stripe.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import FabriqueSession
from app.facturation.abonnements import plan_actif
from app.main import app
from app.modeles.enums import StatutAbonnement
from app.modeles.facturation import Abonnement
from app.services.facturation_stripe import enregistrer_evenement, traiter_evenement
from tests.conftest import creer_compte


def _client(email: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    reponse = creer_compte(client, email, nom_organisation="Organisation Stripe")
    return client, reponse["organisation_active"]


# --- Endpoints, sans clé Stripe configurée -----------------------------------


def test_checkout_sans_cle_stripe_configuree_renvoie_503():
    client, _ = _client("stripe-checkout@test.fr")
    reponse = client.post("/api/v1/abonnement/checkout", json={"code_plan": "starter"})
    assert reponse.status_code == 503


def test_checkout_plan_gratuit_refuse():
    client, _ = _client("stripe-checkout-gratuit@test.fr")
    reponse = client.post("/api/v1/abonnement/checkout", json={"code_plan": "free"})
    assert reponse.status_code == 400


def test_checkout_plan_inconnu_404():
    client, _ = _client("stripe-checkout-inconnu@test.fr")
    reponse = client.post("/api/v1/abonnement/checkout", json={"code_plan": "inexistant"})
    assert reponse.status_code == 404


def test_portail_sans_cle_stripe_configuree_renvoie_503():
    client, _ = _client("stripe-portail@test.fr")
    reponse = client.post("/api/v1/abonnement/portail")
    assert reponse.status_code == 503


def test_webhook_sans_secret_configure_refuse():
    client = TestClient(app)
    reponse = client.post(
        "/api/v1/stripe/webhook", content=b"{}", headers={"stripe-signature": "invalide"}
    )
    assert reponse.status_code == 403


# --- Traitement des événements (logique interne, sans signature Stripe) -----


def _evenement_paiement_complete(organisation_id: str, plan_code: str, event_id: str) -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_test_123",
                "subscription": "sub_test_123",
                "metadata": {"organisation_id": organisation_id, "plan_code": plan_code},
            }
        },
    }


def test_paiement_complete_active_le_plan_via_les_metadonnees():
    session = FabriqueSession()
    try:
        _, organisation_id = _client("stripe-webhook-activation@test.fr")

        assert plan_actif(session, organisation_id).code == "free"

        evenement = enregistrer_evenement(
            session, _evenement_paiement_complete(organisation_id, "starter", "evt_activation_1")
        )
        session.flush()
        resume = traiter_evenement(session, evenement)
        session.commit()

        assert evenement.traite is True, resume
        assert plan_actif(session, organisation_id).code == "starter"

        abonnement = session.query(Abonnement).filter(
            Abonnement.organisation_id == organisation_id,
            Abonnement.statut == StatutAbonnement.ACTIF.value,
        ).one()
        assert abonnement.stripe_customer_id == "cus_test_123"
        assert abonnement.stripe_subscription_id == "sub_test_123"
    finally:
        session.close()


def test_resiliation_desactive_labonnement():
    session = FabriqueSession()
    try:
        _, organisation_id = _client("stripe-webhook-resiliation@test.fr")

        activation = enregistrer_evenement(
            session, _evenement_paiement_complete(organisation_id, "starter", "evt_resiliation_1")
        )
        session.flush()
        traiter_evenement(session, activation)
        session.commit()
        assert plan_actif(session, organisation_id).code == "starter"

        resiliation = enregistrer_evenement(
            session,
            {
                "id": "evt_resiliation_2",
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": "sub_test_123", "customer": "cus_test_123"}},
            },
        )
        session.flush()
        resume = traiter_evenement(session, resiliation)
        session.commit()

        assert resiliation.traite is True, resume
        # Résilié : l'organisation retombe sur le plan gratuit
        assert plan_actif(session, organisation_id).code == "free"
    finally:
        session.close()


def test_evenement_deja_recu_nest_pas_retraite():
    session = FabriqueSession()
    try:
        _, organisation_id = _client("stripe-webhook-dedup@test.fr")
        charge = _evenement_paiement_complete(organisation_id, "starter", "evt_dedup_1")

        premier = enregistrer_evenement(session, charge)
        session.flush()
        assert premier is not None
        traiter_evenement(session, premier)
        session.commit()

        second = enregistrer_evenement(session, charge)
        assert second is None
    finally:
        session.close()


def test_paiement_sans_metadonnees_organisation_signale_une_erreur():
    session = FabriqueSession()
    try:
        evenement = enregistrer_evenement(
            session,
            {
                "id": "evt_sans_metadonnees",
                "type": "checkout.session.completed",
                "data": {"object": {"customer": "cus_x", "subscription": "sub_x", "metadata": {}}},
            },
        )
        session.flush()
        resume = traiter_evenement(session, evenement)
        session.commit()

        assert evenement.traite is False
        assert evenement.erreur_traitement is not None
        assert "metadata" in resume.lower() or "organisation_id" in resume.lower()
    finally:
        session.close()
