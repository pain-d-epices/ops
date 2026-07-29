"""Tests des chercheurs et des points de départ multiples.

Aucun accès réseau : les outils externes (Maigret, user-scanner) sont remplacés par
des versions déterministes, et les appels HTTP sont simulés.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import FabriqueSession
from app.facturation.abonnements import plan_actif
from app.facturation.plans import (
    RECHERCHE_ADRESSE,
    RECHERCHE_DEPUIS_COMPTE,
    RECHERCHE_EMAIL,
    RECHERCHE_TELEPHONE,
    RECHERCHES_SPECIALISEES,
)
from app.main import app
from app.modeles.enums import TypeDonnee, TypePointDepart
from app.moteur.chercheurs.base import detecter_type
from app.moteur.chercheurs.registre import charger_chercheurs, chercheur_pour
from app.services.points_depart import chercheur_autorise
from tests.conftest import creer_compte, passer_au_plan

# --- Registre et détection --------------------------------------------------


def test_les_cinq_chercheurs_sont_decouverts():
    chercheurs = charger_chercheurs()
    assert set(chercheurs) == {"pseudo", "compte", "email", "telephone", "adresse"}


def test_chaque_chercheur_declare_son_droit():
    """Le rapprochement plan ↔ chercheur passe par `fonctionnalite_requise` :
    un chercheur mal déclaré serait accessible à tous, y compris au palier gratuit."""
    chercheurs = charger_chercheurs()
    # La recherche par pseudonyme est la fonctionnalité d'appel : ouverte à tous
    assert chercheurs["pseudo"].fonctionnalite_requise == ""
    for type_point in ("compte", "email", "telephone", "adresse"):
        droit = chercheurs[type_point].fonctionnalite_requise
        assert droit, f"Le chercheur {type_point} n'exige aucun droit"
        assert droit in RECHERCHES_SPECIALISEES


@pytest.mark.parametrize(
    "valeur,attendu",
    [
        ("jeanmartin", TypePointDepart.PSEUDO.value),
        ("jean.martin@exemple.fr", TypePointDepart.EMAIL.value),
        ("https://github.com/torvalds", TypePointDepart.COMPTE.value),
        ("github.com/torvalds", TypePointDepart.COMPTE.value),
        ("+33612345678", TypePointDepart.TELEPHONE.value),
        ("06 12 34 56 78", TypePointDepart.TELEPHONE.value),
        ("12 rue de la Paix Paris", TypePointDepart.ADRESSE.value),
        ("Jean Martin", TypePointDepart.NOM.value),
    ],
)
def test_detection_automatique_du_type(valeur: str, attendu: str):
    """L'analyste colle ce qu'il a sans choisir de type : la détection doit suivre."""
    assert detecter_type(valeur) == attendu


# --- Validation des entrées -------------------------------------------------


def test_validation_email():
    chercheur = chercheur_pour("email")
    assert chercheur.valider("Jean.Martin@Exemple.FR") == "jean.martin@exemple.fr"
    assert chercheur.valider("pas-une-adresse") is None
    assert chercheur.valider("") is None


def test_validation_telephone():
    chercheur = chercheur_pour("telephone")
    assert chercheur.valider("+33 6 12 34 56 78") == "+33612345678"
    assert chercheur.valider("12") is None


def test_validation_compte():
    chercheur = chercheur_pour("compte")
    assert chercheur.valider("github.com/jean") == "https://github.com/jean"
    assert chercheur.valider("jeanmartin") is None  # pas de domaine


def test_telephone_invalide_signale_clairement():
    """Un numéro syntaxiquement plausible mais invalide doit produire un message
    exploitable, pas un résultat vide sans explication."""
    resultat = chercheur_pour("telephone").chercher("+33000000000", {"user_scanner_actif": False})
    assert resultat.erreur is not None
    assert "valide" in resultat.erreur.lower()


def test_telephone_extrait_pays_et_operateur():
    resultat = chercheur_pour("telephone").chercher("+33612345678", {"user_scanner_actif": False})
    assert resultat.erreur is None
    assert resultat.detail["pays"] == "FR"
    assert resultat.detail["type_ligne"] == "mobile"
    types = {i.type for i in resultat.informations}
    assert TypeDonnee.TELEPHONE in types


def test_compte_extrait_le_pseudonyme_et_enregistre_le_compte():
    resultat = chercheur_pour("compte").chercher("https://github.com/torvalds")
    assert resultat.erreur is None
    # Le compte fourni par l'analyste est tenu pour acquis
    assert len(resultat.comptes) == 1
    assert resultat.comptes[0].url == "https://github.com/torvalds"
    # Et son pseudonyme relance la recherche large
    assert "torvalds" in [i.valeur for i in resultat.informations]


# --- Gating par plan --------------------------------------------------------


def _client(email: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    reponse = creer_compte(client, email, nom_organisation=f"Org {email}")
    return client, reponse["organisation_active"]


def test_plan_gratuit_refuse_les_recherches_specialisees():
    session = FabriqueSession()
    try:
        _, organisation_id = _client("chercheurs_gratuit@test.fr")
        plan = plan_actif(session, organisation_id)

        for type_point in ("email", "telephone", "adresse", "compte"):
            autorise, motif = chercheur_autorise(type_point, plan)
            assert not autorise, f"{type_point} ne doit pas être ouvert au palier gratuit"
            assert motif

        # La recherche par pseudonyme reste ouverte : c'est l'appel du produit
        autorise, _ = chercheur_autorise("pseudo", plan)
        assert autorise
    finally:
        session.close()


def test_plan_starter_ouvre_toutes_les_recherches_specialisees():
    """Décision produit : les types de recherche sont tous accessibles dès Starter ;
    ce sont le volume et la profondeur qui distinguent les paliers supérieurs."""
    session = FabriqueSession()
    try:
        _, organisation_id = _client("chercheurs_starter@test.fr")
        passer_au_plan(session, organisation_id, "starter")
        plan = plan_actif(session, organisation_id)

        for droit in (
            RECHERCHE_EMAIL, RECHERCHE_TELEPHONE, RECHERCHE_ADRESSE, RECHERCHE_DEPUIS_COMPTE
        ):
            assert plan.possede(droit), f"{droit} devrait être inclus dès Starter"

        for type_point in ("email", "telephone", "adresse", "compte"):
            autorise, motif = chercheur_autorise(type_point, plan)
            assert autorise, f"{type_point} refusé : {motif}"
    finally:
        session.close()


def test_nombre_de_points_depart_limite_par_le_plan():
    session = FabriqueSession()
    try:
        client, organisation_id = _client("points_limite@test.fr")
        passer_au_plan(session, organisation_id, "starter")   # 2 maximum, pseudonyme compris

        # Un pseudonyme + un e-mail : dans la limite
        accepte = client.post(
            "/api/v1/investigations",
            json={
                "pseudo": "jeanmartin",
                "points_depart": [{"valeur": "jean@exemple.fr"}],
            },
        )
        assert accepte.status_code == 201, accepte.text
        types = {p["type"] for p in accepte.json()["points_depart"]}
        assert types == {"pseudo", "email"}

        # Un pseudonyme + deux éléments : au-delà de la limite du palier
        refuse = client.post(
            "/api/v1/investigations",
            json={
                "pseudo": "jeanmartin",
                "points_depart": [
                    {"valeur": "jean@exemple.fr"},
                    {"valeur": "+33612345678"},
                ],
            },
        )
        assert refuse.status_code == 403
        assert "élément" in refuse.json()["detail"]
    finally:
        session.close()


def test_point_depart_refuse_sur_plan_gratuit():
    client, _ = _client("points_gratuit@test.fr")
    reponse = client.post(
        "/api/v1/investigations",
        json={"pseudo": "jeanmartin", "points_depart": [{"valeur": "jean@exemple.fr"}]},
    )
    assert reponse.status_code == 403
    assert "plan" in reponse.json()["detail"].lower()


def test_valeur_invalide_rejetee_avec_message_clair():
    session = FabriqueSession()
    try:
        client, organisation_id = _client("points_invalide@test.fr")
        passer_au_plan(session, organisation_id, "pro")

        reponse = client.post(
            "/api/v1/investigations",
            json={
                "pseudo": "jeanmartin",
                "points_depart": [{"valeur": "ceci-nest-pas-une-adresse", "type": "email"}],
            },
        )
        assert reponse.status_code == 422
        assert "adresse" in reponse.json()["detail"].lower()
    finally:
        session.close()


def test_pseudonyme_toujours_enregistre_comme_point_depart():
    """Même sans élément supplémentaire, le pseudonyme est un point de départ :
    le traitement est ainsi homogène quel que soit le nombre d'entrées."""
    client, _ = _client("points_simple@test.fr")
    reponse = client.post("/api/v1/investigations", json={"pseudo": "jeanmartin"})
    assert reponse.status_code == 201
    points = reponse.json()["points_depart"]
    assert len(points) == 1
    assert points[0]["type"] == "pseudo"
    assert points[0]["valeur"] == "jeanmartin"


def test_doublons_de_points_depart_ignores():
    session = FabriqueSession()
    try:
        client, organisation_id = _client("points_doublon@test.fr")
        passer_au_plan(session, organisation_id, "entreprise")   # sans limite

        reponse = client.post(
            "/api/v1/investigations",
            json={
                "pseudo": "jeanmartin",
                "points_depart": [
                    {"valeur": "jean@exemple.fr"},
                    {"valeur": "JEAN@EXEMPLE.FR"},   # même adresse, autre casse
                ],
            },
        )
        assert reponse.status_code == 201
        emails = [p for p in reponse.json()["points_depart"] if p["type"] == "email"]
        assert len(emails) == 1
    finally:
        session.close()
