"""Tests des protections contre l'automatisation et l'abus.

Ces protections répondent à un contournement concret du modèle économique : le palier
gratuit offrant 15 recherches par mois, un script qui crée des comptes en série obtient
un volume illimité. Le reste de la suite les désactive (voir la fixture
`sans_protections_anti_abus` dans conftest) ; ici, on les réactive pour les vérifier.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.config import surcharger_config_metier
from app.infra.limiteur_entrant import reinitialiser_limiteur_entrant
from app.infra.redis_client import reinitialiser_client_redis
from app.main import app
from app.securite.anti_bot import (
    PreuveInvalide,
    creer_defi,
    reinitialiser_epreuves_consommees,
    verifier_preuve,
)
from app.securite.domaines_jetables import est_domaine_jetable


#: Plage réduite pour les tests. La résolution se fait ici en Python, bien plus lent
#: que le SubtleCrypto d'un navigateur : garder 50 000 ferait durer ce fichier une
#: demi-minute pour ne rien vérifier de plus.
NOMBRE_MAXIMAL_TESTS = 1500


@pytest.fixture
def protections_actives():
    """Réactive les protections, et repart d'un limiteur vierge à chaque test."""
    surcharger_config_metier("anti_abus.actif", True)
    surcharger_config_metier("anti_abus.nombre_maximal", NOMBRE_MAXIMAL_TESTS)
    reinitialiser_limiteur_entrant()
    reinitialiser_client_redis()
    reinitialiser_epreuves_consommees()
    yield
    surcharger_config_metier("anti_abus.actif", False)
    surcharger_config_metier("anti_abus.nombre_maximal", 50000)
    reinitialiser_limiteur_entrant()
    reinitialiser_epreuves_consommees()


def _resoudre(defi) -> str:
    """Résout l'épreuve comme le fera le navigateur, puis encode la preuve."""
    for nombre in range(defi.maxnumber + 1):
        empreinte = hashlib.sha256(f"{defi.salt}{nombre}".encode()).hexdigest()
        if empreinte == defi.challenge:
            return base64.b64encode(
                json.dumps({
                    "algorithm": defi.algorithm,
                    "challenge": defi.challenge,
                    "number": nombre,
                    "salt": defi.salt,
                    "signature": defi.signature,
                }).encode()
            ).decode()
    raise AssertionError("épreuve insoluble : le nombre tiré sort de la plage annoncée")


# --- Épreuve anti-robot ----------------------------------------------------


def test_epreuve_resolue_est_acceptee(protections_actives):
    verifier_preuve(_resoudre(creer_defi()))   # ne doit rien lever


def test_epreuve_absente_est_refusee(protections_actives):
    with pytest.raises(PreuveInvalide):
        verifier_preuve(None)
    with pytest.raises(PreuveInvalide):
        verifier_preuve("")


def test_epreuve_mal_resolue_est_refusee(protections_actives):
    defi = creer_defi()
    faux = base64.b64encode(
        json.dumps({
            "algorithm": defi.algorithm, "challenge": defi.challenge,
            "number": defi.maxnumber + 7,      # hors plage, donc jamais la solution
            "salt": defi.salt, "signature": defi.signature,
        }).encode()
    ).decode()
    with pytest.raises(PreuveInvalide, match="non résolue"):
        verifier_preuve(faux)


def test_defi_fabrique_par_le_client_est_refuse(protections_actives):
    """Sans la clé du serveur, impossible de forger un défi : c'est ce qui empêche de
    se poser une énigme triviale à soi-même."""
    sel = "aaaaaaaa.9999999999"
    nombre = 1
    empreinte = hashlib.sha256(f"{sel}{nombre}".encode()).hexdigest()
    forge = base64.b64encode(
        json.dumps({
            "algorithm": "SHA-256", "challenge": empreinte, "number": nombre,
            "salt": sel, "signature": "0" * 64,
        }).encode()
    ).decode()
    with pytest.raises(PreuveInvalide, match="non authentique"):
        verifier_preuve(forge)


def test_epreuve_expiree_est_refusee(protections_actives):
    surcharger_config_metier("anti_abus.validite_defi_secondes", 0)
    try:
        with pytest.raises(PreuveInvalide, match="expirée"):
            verifier_preuve(_resoudre(creer_defi()))
    finally:
        surcharger_config_metier("anti_abus.validite_defi_secondes", 900)


def test_protections_desactivees_laissent_tout_passer():
    """Le drapeau de configuration doit réellement tout court-circuiter, sans quoi la
    suite de tests ne pourrait pas fonctionner."""
    surcharger_config_metier("anti_abus.actif", False)
    verifier_preuve(None)


# --- Adresses jetables -----------------------------------------------------


def test_domaines_jetables_reconnus():
    assert est_domaine_jetable("jean@yopmail.com")
    assert est_domaine_jetable("jean@1secmail.com")
    # Les sous-domaines sont couverts sans être énumérés
    assert est_domaine_jetable("jean@sub.mailinator.com")
    # Le domaine seul est accepté en entrée
    assert est_domaine_jetable("guerrillamail.com")

    assert not est_domaine_jetable("jean@gmail.com")
    assert not est_domaine_jetable("jean@cabinet-test.fr")
    assert not est_domaine_jetable("")


def test_inscription_refuse_une_adresse_jetable(protections_actives):
    client = TestClient(app)
    reponse = client.post(
        "/api/v1/auth/inscription",
        json={
            "email": "robot@yopmail.com",
            "mot_de_passe": "MotDePasseDeTest2026",
            "nom_organisation": "Org jetable",
            "accepter_cgu": True,
            "preuve_anti_robot": _resoudre(creer_defi()),
        },
    )
    assert reponse.status_code == 400
    assert "jetable" in reponse.json()["detail"].lower()


# --- Inscription de bout en bout -------------------------------------------


def test_inscription_sans_epreuve_est_refusee(protections_actives):
    client = TestClient(app)
    reponse = client.post(
        "/api/v1/auth/inscription",
        json={
            "email": "sans.epreuve@test.fr",
            "mot_de_passe": "MotDePasseDeTest2026",
            "nom_organisation": "Org sans epreuve",
            "accepter_cgu": True,
        },
    )
    assert reponse.status_code == 400
    assert "anti-robot" in reponse.json()["detail"].lower()


def test_inscription_avec_epreuve_reussit_et_le_defi_ne_resservira_pas(protections_actives):
    client = TestClient(app)
    defi = client.get("/api/v1/auth/defi-anti-robot").json()
    assert {"algorithm", "challenge", "salt", "signature", "maxnumber"} <= set(defi)

    class _Defi:      # même forme que l'objet renvoyé par creer_defi()
        algorithm = defi["algorithm"]
        challenge = defi["challenge"]
        salt = defi["salt"]
        signature = defi["signature"]
        maxnumber = defi["maxnumber"]

    preuve = _resoudre(_Defi)
    corps = {
        "mot_de_passe": "MotDePasseDeTest2026",
        "accepter_cgu": True,
        "preuve_anti_robot": preuve,
    }

    premiere = client.post(
        "/api/v1/auth/inscription",
        json={**corps, "email": "avec.epreuve@test.fr", "nom_organisation": "Org avec epreuve"},
    )
    assert premiere.status_code == 201, premiere.text

    # Rejouer la même preuve pour un second compte doit échouer : sans cela, une seule
    # résolution servirait à créer autant de comptes que voulu.
    seconde = client.post(
        "/api/v1/auth/inscription",
        json={**corps, "email": "rejeu@test.fr", "nom_organisation": "Org rejeu"},
    )
    assert seconde.status_code == 400
    assert "utilisée" in seconde.json()["detail"].lower()


# --- Plafonds par adresse IP ----------------------------------------------


def test_plafond_de_creation_de_comptes_par_ip(protections_actives):
    """Le scénario d'abus visé : créer des comptes en série pour cumuler les quotas."""
    surcharger_config_metier("anti_abus.comptes_par_ip_par_jour", 2)
    # Débit large : c'est le plafond journalier qu'on veut isoler, pas le rythme.
    surcharger_config_metier("anti_abus.debit.inscription", {"requetes_par_minute": 600, "rafale": 100})
    reinitialiser_limiteur_entrant()

    client = TestClient(app)
    codes = []
    for numero in range(4):
        reponse = client.post(
            "/api/v1/auth/inscription",
            json={
                "email": f"serie{numero}@test.fr",
                "mot_de_passe": "MotDePasseDeTest2026",
                "nom_organisation": f"Org serie {numero}",
                "accepter_cgu": True,
                "preuve_anti_robot": _resoudre(creer_defi()),
            },
        )
        codes.append(reponse.status_code)

    assert codes[:2] == [201, 201], codes
    assert codes[2:] == [429, 429], codes

    surcharger_config_metier("anti_abus.comptes_par_ip_par_jour", 3)
    surcharger_config_metier("anti_abus.debit.inscription", {"requetes_par_minute": 3, "rafale": 3})


def test_debit_par_ip_sur_la_connexion(protections_actives):
    """Le verrou par compte (8 échecs) ne couvre pas le balayage de nombreuses adresses
    depuis une même origine : chaque compte resterait sous son seuil."""
    surcharger_config_metier("anti_abus.debit.connexion", {"requetes_par_minute": 1, "rafale": 2})
    reinitialiser_limiteur_entrant()

    client = TestClient(app)
    codes = [
        client.post(
            "/api/v1/auth/connexion",
            json={"email": f"inconnu{n}@test.fr", "mot_de_passe": "PeuImporte2026!"},
        ).status_code
        for n in range(5)
    ]
    # Les premières tentatives passent (et échouent en 401), puis le débit coupe.
    assert 429 in codes, codes
    assert codes.index(429) <= 3, codes

    surcharger_config_metier("anti_abus.debit.connexion", {"requetes_par_minute": 10, "rafale": 10})


def test_entete_x_forwarded_for_ignoree_sans_proxy_declare(protections_actives):
    """Sinon la limitation par IP serait triviale à contourner : il suffirait de
    changer l'en-tête à chaque requête."""
    surcharger_config_metier("anti_abus.derriere_un_proxy_de_confiance", False)
    surcharger_config_metier("anti_abus.debit.connexion", {"requetes_par_minute": 1, "rafale": 1})
    reinitialiser_limiteur_entrant()

    client = TestClient(app)
    codes = [
        client.post(
            "/api/v1/auth/connexion",
            json={"email": "cible@test.fr", "mot_de_passe": "PeuImporte2026!"},
            headers={"X-Forwarded-For": f"10.0.0.{n}"},   # IP différente à chaque appel
        ).status_code
        for n in range(4)
    ]
    assert 429 in codes, f"l'en-tête a permis de contourner la limite : {codes}"

    surcharger_config_metier("anti_abus.debit.connexion", {"requetes_par_minute": 10, "rafale": 10})
