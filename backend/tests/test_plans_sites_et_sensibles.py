"""Tests des limites de plan introduites avec la nouvelle grille tarifaire :
nombre de sites analysables, et accès aux résultats de sites sensibles.

Comme pour `test_plans_et_quotas`, ces vérifications protègent le chiffre d'affaires :
un contournement livrerait gratuitement ce qui est vendu.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import FabriqueSession
from app.facturation.abonnements import plan_actif
from app.facturation.garde import (
    TOTALITE_DES_SITES,
    sites_analysables,
    sites_sensibles_autorises,
)
from app.main import app
from app.modeles.enums import StatutMaigret
from app.modeles.facturation import Plan
from app.modeles.investigation import ExecutionRecherche, Investigation, ProfilIdentite
from app.moteur.maigret_runner import ResultatRecherche, ResultatSite
from app.moteur.sites_sensibles import est_site_sensible
from app.services.investigation import enregistrer_resultats_maigret
from tests.conftest import creer_compte, passer_au_plan


def _client(email: str, organisation: str = "Organisation") -> tuple[TestClient, str]:
    client = TestClient(app)
    reponse = creer_compte(client, email, nom_organisation=organisation)
    return client, reponse["organisation_active"]


# --- Nombre de sites analysables -------------------------------------------


def test_nombre_de_sites_borne_par_le_plan():
    """La couverture en nombre de sites est un levier de différenciation : un palier ne
    doit jamais obtenir plus large que ce qu'il a acheté, même en le demandant."""
    session = FabriqueSession()
    try:
        _, organisation_id = _client("sites_plan@test.fr")

        gratuit = plan_actif(session, organisation_id)
        assert gratuit.max_sites_analyses == 100
        assert sites_analysables(gratuit, 3000) == 100
        # Sans demande explicite, le défaut serveur (500) est lui aussi ramené au plan
        assert sites_analysables(gratuit, None) == 100
        # Une demande inférieure au plafond est respectée
        assert sites_analysables(gratuit, 50) == 50

        passer_au_plan(session, organisation_id, "starter")
        starter = plan_actif(session, organisation_id)
        assert sites_analysables(starter, 3000) == 1000
        assert sites_analysables(starter, 200) == 200

        # Pro et Entreprise : « recherche maximale », donc toute la base
        for code in ("pro", "entreprise"):
            passer_au_plan(session, organisation_id, code)
            plan = plan_actif(session, organisation_id)
            assert plan.max_sites_analyses == 0, f"{code} devrait être sans limite"
            assert sites_analysables(plan, 3000) == TOTALITE_DES_SITES
            assert sites_analysables(plan, 99999) == TOTALITE_DES_SITES
    finally:
        session.close()


def test_nombre_de_sites_borne_a_la_creation_de_l_investigation():
    """Un client qui modifierait la requête ne doit pas s'octroyer plus de sites."""
    session = FabriqueSession()
    try:
        client, _ = _client("sites_creation@test.fr")
        reponse = client.post(
            "/api/v1/investigations",
            json={"pseudo": "cible_sites", "top_sites": 3000},
        )
        assert reponse.status_code == 201, reponse.text

        investigation = session.get(Investigation, reponse.json()["id"])
        assert investigation.options["top_sites"] == 100
    finally:
        session.close()


# --- Identification des sites sensibles ------------------------------------


def test_identification_des_sites_sensibles():
    """Deux sources : les étiquettes de Maigret, et une liste explicite pour les sites
    qui n'en portent aucune. Les faux positifs d'un filtrage par mots-clés
    (« illustrators.ru » contient « lust ») doivent être épargnés."""
    assert est_site_sensible("OnlyFans", "onlyfans.com", ["porn"])
    assert est_site_sensible("Livejasmin", "livejasmin.com", ["us", "webcam"])
    assert est_site_sensible("m.smutty.com", "m.smutty.com", ["erotic"])
    # Sans étiquette adéquate : rattrapés par la liste de domaines et de noms
    assert est_site_sensible("Fansly", None, [])
    assert est_site_sensible("AdultFriendFinder", "adultfriendfinder.com", ["dating"])
    assert est_site_sensible("PornhubPornstars", None, [])
    # Un sous-domaine ou un miroir est couvert sans être énuméré
    assert est_site_sensible("miroir", "video.eporner.com", [])

    assert not est_site_sensible("GitHub", "github.com", ["coding"])
    assert not est_site_sensible("Illustrators", "illustrators.ru", ["ru"])
    assert not est_site_sensible("antiscam.space", "antiscam.space", ["forum", "ru"])
    assert not est_site_sensible("forums.wyzecam.com", "forums.wyzecam.com", [])
    # Un site de rencontres n'est pas pornographique : c'est un signal légitime
    assert not est_site_sensible("Tinder", "tinder.com", ["dating"])


def test_sites_sensibles_reserves_aux_plans_payants():
    session = FabriqueSession()
    try:
        _, organisation_id = _client("sensibles_plan@test.fr")
        assert not sites_sensibles_autorises(plan_actif(session, organisation_id))

        for code in ("starter", "pro", "entreprise"):
            passer_au_plan(session, organisation_id, code)
            assert sites_sensibles_autorises(plan_actif(session, organisation_id)), code
    finally:
        session.close()


def _resultat_mixte(pseudo: str) -> ResultatRecherche:
    """Un compte anodin et un compte sur site sensible, pour la même cible."""
    return ResultatRecherche(
        pseudo=pseudo,
        sites=[
            ResultatSite(
                site_nom="GitHub", site_domaine="github.com",
                url=f"https://github.com/{pseudo}", pseudo=pseudo,
                statut=StatutMaigret.TROUVE, tags=["coding"],
            ),
            ResultatSite(
                site_nom="OnlyFans", site_domaine="onlyfans.com",
                url=f"https://onlyfans.com/{pseudo}", pseudo=pseudo,
                statut=StatutMaigret.TROUVE, tags=["porn"],
            ),
        ],
    )


def _enregistrer(client: TestClient, organisation_id: str, pseudo: str):
    """Crée une investigation et y enregistre le résultat mixte. Rend le bilan."""
    creation = client.post("/api/v1/investigations", json={"pseudo": pseudo})
    assert creation.status_code == 201, creation.text
    investigation_id = creation.json()["id"]

    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        execution = ExecutionRecherche(
            investigation_id=investigation_id, organisation_id=organisation_id,
            pseudo_recherche=pseudo, profondeur=0, statut="terminee",
        )
        session.add(execution)
        session.flush()
        bilan = enregistrer_resultats_maigret(
            session, investigation, execution, _resultat_mixte(pseudo), profondeur=0
        )
        session.commit()
        domaines = {
            p.site_domaine
            for p in session.scalars(
                select(ProfilIdentite).where(
                    ProfilIdentite.investigation_id == investigation_id
                )
            )
        }
        return bilan, domaines
    finally:
        session.close()


def test_comptes_sensibles_ecartes_a_l_enregistrement_sur_plan_gratuit():
    """Le filtrage s'applique à l'enregistrement, point de passage de tout compte
    découvert quelle que soit sa source (Maigret, user-scanner, chercheur)."""
    client, organisation_id = _client("sensibles_filtre@test.fr", "Org sensibles")

    bilan, domaines = _enregistrer(client, organisation_id, "cible_gratuite")
    # Écarté, et compté plutôt que masqué : un écart entre paliers doit rester explicable
    assert bilan.profils_filtres == 1
    assert bilan.profils_crees == 1
    assert domaines == {"github.com"}


def test_comptes_sensibles_conserves_sur_plan_payant():
    client, organisation_id = _client("sensibles_payant@test.fr", "Org payante")
    session = FabriqueSession()
    try:
        passer_au_plan(session, organisation_id, "starter")
    finally:
        session.close()

    bilan, domaines = _enregistrer(client, organisation_id, "cible_payante")
    assert bilan.profils_filtres == 0
    assert bilan.profils_crees == 2
    assert domaines == {"github.com", "onlyfans.com"}


# --- Verrou sur la grille tarifaire ----------------------------------------


def test_quotas_et_rebonds_des_quatre_paliers():
    """Une modification involontaire d'un quota est un incident commercial, pas un
    détail technique : la grille est donc verrouillée par un test."""
    attendu = {
        # code : (recherches par mois, rebonds max, sites max)
        # Le palier gratuit a été refondu le 02/08/2026 : moins de volume (10 au lieu
        # de 15) et moins de sites (100 au lieu de 200), mais un niveau de rebond et
        # l'enrichissement, sans quoi il ne démontrait pas la corrélation qu'il vend.
        "free": (10, 1, 100),
        "starter": (100, 2, 1000),
        "pro": (500, 5, 0),
        "entreprise": (2500, 10, 0),
    }
    session = FabriqueSession()
    try:
        for code, (recherches, rebonds, sites) in attendu.items():
            plan = session.scalar(select(Plan).where(Plan.code == code))
            assert plan is not None, code
            assert plan.quota_recherches_mois == recherches, code
            assert plan.profondeur_pivot_max == rebonds, code
            assert plan.max_sites_analyses == sites, code
    finally:
        session.close()
