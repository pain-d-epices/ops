"""Configuration des tests.

Les tests tournent sur SQLite en fichier temporaire : ils sont ainsi exécutables sans
PostgreSQL, Redis ni réseau. Les modèles utilisent des types portables (chaînes pour
les identifiants, JSON générique), ce qui rend cette substitution possible.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Doit précéder tout import de `app` : le moteur SQLAlchemy est construit à l'import.
_FICHIER_BASE = Path(tempfile.gettempdir()) / "searcher_tests.db"
os.environ["URL_BASE_DE_DONNEES"] = f"sqlite:///{_FICHIER_BASE.as_posix()}"
os.environ["CLE_SECRETE"] = "cle_de_test_uniquement_pour_les_tests_automatises"
os.environ["ENVIRONNEMENT"] = "test"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"   # port inutilisé : force le repli hors Redis

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import FabriqueSession, moteur  # noqa: E402
from app.main import app  # noqa: E402
from app.modeles import Organisation, Plan, Utilisateur  # noqa: E402
from app.scripts.initialiser_plans import initialiser_plans  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def base_de_donnees():
    """Crée le schéma une fois pour toute la session de tests."""
    _supprimer_fichier_base()
    Base.metadata.create_all(moteur)
    initialiser_plans()
    yield
    Base.metadata.drop_all(moteur)
    # Windows verrouille le fichier tant qu'une connexion du pool reste ouverte :
    # il faut libérer le moteur avant de pouvoir le supprimer.
    moteur.dispose()
    _supprimer_fichier_base()


def _supprimer_fichier_base() -> None:
    try:
        _FICHIER_BASE.unlink(missing_ok=True)
    except PermissionError:
        # Fichier encore verrouillé : sans gravité, il sera écrasé au prochain lancement.
        pass


@pytest.fixture
def session() -> Session:
    session = FabriqueSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def sans_protections_anti_abus():
    """Désactive les protections anti-automatisation pour la majorité des tests.

    Elles bornent les créations de comptes par adresse IP et exigent la résolution
    d'une épreuve : la suite de tests, qui crée des dizaines de comptes depuis la même
    origine, les déclencherait toutes. Les tests qui vérifient ces protections les
    réactivent explicitement (voir `test_anti_abus.py`).
    """
    from app.config import surcharger_config_metier
    from app.infra.limiteur_entrant import reinitialiser_limiteur_entrant
    from app.infra.redis_client import reinitialiser_client_redis
    from app.securite.anti_bot import reinitialiser_epreuves_consommees

    def remettre_a_zero() -> None:
        surcharger_config_metier("anti_abus.actif", False)
        reinitialiser_limiteur_entrant()
        reinitialiser_client_redis()
        reinitialiser_epreuves_consommees()

    remettre_a_zero()
    yield
    remettre_a_zero()


@pytest.fixture(autouse=True)
def sans_file_de_taches(monkeypatch):
    """Neutralise l'envoi vers Celery : les tests ne dépendent pas d'un broker.

    Les appels `apply_async` sont enregistrés pour pouvoir vérifier qu'une tâche
    *aurait* été planifiée, sans qu'aucun worker ne soit nécessaire.
    """
    appels: list[dict] = []

    def faux_apply_async(self, args=None, kwargs=None, **options):
        appels.append({"tache": self.name, "kwargs": kwargs or {}})
        return type("FauxResultat", (), {"id": "tache-de-test"})()

    from celery.app.task import Task

    monkeypatch.setattr(Task, "apply_async", faux_apply_async, raising=False)
    return appels


def creer_compte(
    client: TestClient,
    email: str,
    mot_de_passe: str = "MotDePasseDeTest2026",
    nom_organisation: str = "Organisation de test",
) -> dict:
    """Inscrit un utilisateur et renvoie la réponse de connexion."""
    reponse = client.post(
        "/api/v1/auth/inscription",
        json={
            "email": email,
            "mot_de_passe": mot_de_passe,
            "nom_organisation": nom_organisation,
            "accepter_cgu": True,
        },
    )
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


def passer_au_plan(session: Session, organisation_id: str, code_plan: str) -> None:
    """Attribue un plan à une organisation, sans passer par Gumroad."""
    from app.services.gumroad import activer_abonnement

    organisation = session.get(Organisation, organisation_id)
    plan = session.query(Plan).filter(Plan.code == code_plan).one()
    activer_abonnement(session, organisation, plan, cle_licence=f"licence-test-{code_plan}")
    session.commit()


def utilisateur_par_email(session: Session, email: str) -> Utilisateur:
    return session.query(Utilisateur).filter(Utilisateur.email == email).one()
