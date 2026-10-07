"""Mode autohébergé : une installation personnelle n'est bridée par aucun palier.

C'est le mode par défaut du dépôt (`MODE_AUTOHEBERGE=true`). La suite de tests tourne
en mode « service » pour valider les paliers payants (voir `conftest.py`) : ces tests
réactivent donc explicitement le mode autohébergé, puis le rendent.
"""

from __future__ import annotations

import pytest

from app.config import parametres
from app.facturation.abonnements import plan_actif, plan_par_defaut
from app.facturation.plans import (
    CODE_PLAN_LIBRE,
    EXPORT_PDF,
    PIVOT_AUTOMATIQUE,
    RECHERCHE_ETENDUE,
    RECHERCHE_TELEPHONE,
    SITES_SENSIBLES,
)
from app.facturation.quotas import limite_du_plan
from app.modeles import Plan
from tests.conftest import creer_compte


def plan_gratuit_de_la_base(session):
    """Le palier gratuit, lu en base sans passer par la résolution du mode."""
    return session.query(Plan).filter(Plan.code == "free").one()


@pytest.fixture
def mode_autoheberge(monkeypatch):
    """Rétablit le mode autohébergé pour la durée du test."""
    monkeypatch.setenv("MODE_AUTOHEBERGE", "true")
    parametres.cache_clear()
    yield
    parametres.cache_clear()


def test_en_mode_service_le_palier_par_defaut_reste_bride(session):
    """Témoin : sans le mode autohébergé, c'est bien le palier gratuit qui s'applique.

    Sans ce témoin, le test suivant ne prouverait rien — le palier « libre » pourrait
    être attribué dans les deux modes.
    """
    assert parametres().mode_autoheberge is False
    assert plan_par_defaut(session).code == "free"


def test_le_palier_libre_est_attribue_sans_abonnement(session, mode_autoheberge):
    plan = plan_par_defaut(session)
    assert plan.code == CODE_PLAN_LIBRE


def test_le_palier_libre_n_impose_aucun_quota(session, mode_autoheberge):
    plan = plan_par_defaut(session)
    for quota in ("recherches", "enrichissements", "pivots"):
        assert limite_du_plan(plan, quota) is None, f"quota « {quota} » encore borné"
    # Témoin : en mode service, ces mêmes quotas sont bien bornés.
    assert limite_du_plan(plan_gratuit_de_la_base(session), "recherches") == 10


def test_le_palier_libre_ouvre_les_fonctionnalites_payantes(session, mode_autoheberge):
    plan = plan_par_defaut(session)
    for fonctionnalite in (
        RECHERCHE_TELEPHONE, RECHERCHE_ETENDUE, PIVOT_AUTOMATIQUE,
        EXPORT_PDF, SITES_SENSIBLES,
    ):
        assert plan.possede(fonctionnalite), f"« {fonctionnalite} » refusée"
    assert plan.max_sites_analyses == 0      # 0 = toute la base de sites
    assert plan.max_points_depart == 0
    assert plan.profondeur_pivot_max >= 10


def test_un_compte_cree_a_l_inscription_recoit_le_palier_libre(
    client, session, mode_autoheberge
):
    """Bout en bout : l'inscription suffit, sans abonnement ni paiement."""
    reponse = creer_compte(client, "autoheberge@test.fr")
    organisation_id = reponse["organisation_active"]
    assert organisation_id is not None
    assert plan_actif(session, organisation_id).code == CODE_PLAN_LIBRE


def test_l_api_n_expose_ni_palier_a_vendre_ni_montee_en_gamme(client, mode_autoheberge):
    """L'interface ne doit avoir aucun vocabulaire commercial à afficher.

    Le palier « libre » portant l'ordre le plus bas, une recherche naïve de palier
    supérieur désignerait le palier gratuit — plus restrictif — comme une montée en
    gamme. Ce test verrouille l'absence de cette proposition.
    """
    creer_compte(client, "sans-commerce@test.fr")
    etat = client.get("/api/v1/abonnement").json()
    assert etat["mode_autoheberge"] is True
    assert etat["plan_superieur"] is None
    assert etat["plan"]["code"] == CODE_PLAN_LIBRE
    assert [p["code"] for p in client.get("/api/v1/abonnement/plans").json()] == [
        CODE_PLAN_LIBRE
    ]


def test_en_mode_service_la_montee_en_gamme_reste_proposee(client):
    """Témoin : le mode service conserve sa mécanique commerciale intacte."""
    creer_compte(client, "avec-commerce@test.fr")
    etat = client.get("/api/v1/abonnement").json()
    assert etat["mode_autoheberge"] is False
    assert etat["plan_superieur"] is not None
    assert len(client.get("/api/v1/abonnement/plans").json()) > 1
