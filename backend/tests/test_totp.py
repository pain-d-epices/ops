"""Tests de la double authentification (TOTP)."""

from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient

from app.db.session import FabriqueSession
from app.main import app
from app.modeles.utilisateur import Utilisateur
from tests.conftest import creer_compte, utilisateur_par_email

MOT_DE_PASSE = "MotDePasseDeTest2026"


def _client(email: str) -> TestClient:
    client = TestClient(app)
    creer_compte(client, email, mot_de_passe=MOT_DE_PASSE, nom_organisation="Organisation TOTP")
    return client


def _activer(client: TestClient) -> dict:
    """Démarre puis confirme l'activation. Rend la charge utile de `/2fa/activer`."""
    activation = client.post("/api/v1/auth/2fa/activer")
    assert activation.status_code == 200, activation.text
    donnees = activation.json()

    code = pyotp.TOTP(donnees["secret"]).now()
    confirmation = client.post("/api/v1/auth/2fa/confirmer", json={"code": code})
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["actif"] is True
    return donnees


def test_activation_puis_connexion_avec_code_totp():
    email = "totp-connexion@test.fr"
    client = _client(email)
    donnees = _activer(client)

    # Un client tiers, sans les cookies de session : simule une nouvelle connexion.
    client_frais = TestClient(app)
    premier_appel = client_frais.post(
        "/api/v1/auth/connexion", json={"email": email, "mot_de_passe": MOT_DE_PASSE}
    )
    assert premier_appel.status_code == 401
    assert premier_appel.json()["code"] == "totp_requis"

    code = pyotp.TOTP(donnees["secret"]).now()
    second_appel = client_frais.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": MOT_DE_PASSE, "code_totp": code},
    )
    assert second_appel.status_code == 200, second_appel.text


def test_code_totp_incorrect_refuse_la_confirmation():
    email = "totp-code-faux@test.fr"
    client = _client(email)

    client.post("/api/v1/auth/2fa/activer")
    confirmation = client.post("/api/v1/auth/2fa/confirmer", json={"code": "000000"})
    assert confirmation.status_code == 400


def test_code_totp_incorrect_refuse_la_connexion():
    email = "totp-code-faux-connexion@test.fr"
    client = _client(email)
    _activer(client)

    client_frais = TestClient(app)
    reponse = client_frais.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": MOT_DE_PASSE, "code_totp": "000000"},
    )
    assert reponse.status_code == 401
    assert reponse.json().get("code") != "totp_requis"


def test_code_de_secours_a_usage_unique():
    email = "totp-secours@test.fr"
    client = _client(email)
    donnees = _activer(client)
    code_secours = donnees["codes_secours"][0]

    client_frais = TestClient(app)
    premiere_utilisation = client_frais.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": MOT_DE_PASSE, "code_totp": code_secours},
    )
    assert premiere_utilisation.status_code == 200, premiere_utilisation.text

    client_frais_2 = TestClient(app)
    seconde_utilisation = client_frais_2.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": MOT_DE_PASSE, "code_totp": code_secours},
    )
    assert seconde_utilisation.status_code == 401
    assert seconde_utilisation.json().get("code") != "totp_requis"


def test_desactivation_exige_mot_de_passe_et_code_valide():
    email = "totp-desactivation@test.fr"
    client = _client(email)
    donnees = _activer(client)
    code = pyotp.TOTP(donnees["secret"]).now()

    # Mauvais mot de passe : refusé même avec un code valide
    refus_mdp = client.post(
        "/api/v1/auth/2fa/desactiver", json={"mot_de_passe": "mauvais", "code": code}
    )
    assert refus_mdp.status_code == 401

    # Code faux : refusé même avec le bon mot de passe
    refus_code = client.post(
        "/api/v1/auth/2fa/desactiver", json={"mot_de_passe": MOT_DE_PASSE, "code": "000000"}
    )
    assert refus_code.status_code == 400

    code_frais = pyotp.TOTP(donnees["secret"]).now()
    ok = client.post(
        "/api/v1/auth/2fa/desactiver",
        json={"mot_de_passe": MOT_DE_PASSE, "code": code_frais},
    )
    assert ok.status_code == 200
    assert ok.json()["actif"] is False

    # Une fois désactivée, la connexion ne demande plus de code
    client_frais = TestClient(app)
    reponse = client_frais.post(
        "/api/v1/auth/connexion", json={"email": email, "mot_de_passe": MOT_DE_PASSE}
    )
    assert reponse.status_code == 200


def test_reactivation_impossible_sans_desactiver_dabord():
    email = "totp-double-activation@test.fr"
    client = _client(email)
    _activer(client)

    reponse = client.post("/api/v1/auth/2fa/activer")
    assert reponse.status_code == 409


def test_secret_stocke_en_base_est_chiffre():
    """Le secret TOTP ne doit jamais apparaître en clair en base — seule la vérification
    applicative doit pouvoir le lire, via déchiffrement."""
    email = "totp-secret-chiffre@test.fr"
    client = _client(email)
    donnees = _activer(client)

    session = FabriqueSession()
    try:
        utilisateur = utilisateur_par_email(session, email)
        assert isinstance(utilisateur, Utilisateur)
        assert utilisateur.totp_secret is not None
        assert donnees["secret"] not in utilisateur.totp_secret
    finally:
        session.close()
