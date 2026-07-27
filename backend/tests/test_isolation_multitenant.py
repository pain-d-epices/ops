"""Tests d'isolation entre organisations.

C'est le test le plus critique du produit : une fuite de données entre deux clients
d'un SaaS OSINT exposerait les investigations d'un cabinet à un concurrent.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import creer_compte


def _client_authentifie(email: str, organisation: str) -> TestClient:
    client = TestClient(app)
    creer_compte(client, email, nom_organisation=organisation)
    return client


def test_investigation_invisible_depuis_une_autre_organisation():
    client_a = _client_authentifie("alice@cabinet-a.fr", "Cabinet A")
    client_b = _client_authentifie("bob@cabinet-b.fr", "Cabinet B")

    creation = client_a.post("/api/v1/investigations", json={"pseudo": "cible_confidentielle"})
    assert creation.status_code == 201, creation.text
    investigation_id = creation.json()["id"]

    # B connaît l'identifiant mais n'appartient pas à l'organisation de A
    for chemin in (
        f"/api/v1/investigations/{investigation_id}",
        f"/api/v1/investigations/{investigation_id}/profils",
        f"/api/v1/investigations/{investigation_id}/graphe",
        f"/api/v1/investigations/{investigation_id}/pivots",
    ):
        reponse = client_b.get(chemin)
        assert reponse.status_code == 404, f"{chemin} a répondu {reponse.status_code}"

    # ... et ne peut pas la supprimer non plus
    assert client_b.delete(f"/api/v1/investigations/{investigation_id}").status_code == 404
    # Le propriétaire, lui, y accède normalement
    assert client_a.get(f"/api/v1/investigations/{investigation_id}").status_code == 200


def test_liste_ne_contient_que_les_investigations_de_lorganisation():
    client_a = _client_authentifie("carole@cabinet-c.fr", "Cabinet C")
    client_b = _client_authentifie("david@cabinet-d.fr", "Cabinet D")

    client_a.post("/api/v1/investigations", json={"pseudo": "cible_de_c"})
    client_b.post("/api/v1/investigations", json={"pseudo": "cible_de_d"})

    pseudos_a = {i["pseudo_initial"] for i in client_a.get("/api/v1/investigations").json()}
    pseudos_b = {i["pseudo_initial"] for i in client_b.get("/api/v1/investigations").json()}

    assert "cible_de_c" in pseudos_a and "cible_de_d" not in pseudos_a
    assert "cible_de_d" in pseudos_b and "cible_de_c" not in pseudos_b


def test_entete_organisation_forge_est_rejete():
    """Un client ne doit pas pouvoir changer d'organisation via un en-tête HTTP."""
    client_a = _client_authentifie("eva@cabinet-e.fr", "Cabinet E")
    client_b = _client_authentifie("franck@cabinet-f.fr", "Cabinet F")

    organisation_a = client_a.get("/api/v1/auth/moi").json()["organisations"][0]["id"]
    reponse = client_b.get("/api/v1/organisation", headers={"X-Organisation": organisation_a})
    assert reponse.status_code == 404


def test_acces_sans_authentification_refuse():
    client = TestClient(app)
    for chemin in ("/api/v1/investigations", "/api/v1/organisation", "/api/v1/abonnement"):
        assert client.get(chemin).status_code == 401


def test_sonde_de_sante_reste_publique():
    client = TestClient(app)
    reponse = client.get("/api/sante")
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "ok"
