"""Tests de l'arrêt d'une recherche en cours.

Le mécanisme est **coopératif** (voir `app/moteur/annulation.py`) : le pool solo de
Celery sous Windows interdit de tuer la tâche, puisque le processus qui l'exécute est
le worker lui-même. Ce qui est vérifié ici, c'est donc que chaque étape du cycle
consulte bien le drapeau et refuse d'enchaîner.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import FabriqueSession
from app.main import app
from app.modeles.enums import StatutInvestigation, StatutPropositionPivot
from app.modeles.investigation import Investigation, ProfilIdentite, PropositionPivot
from app.moteur.maigret_runner import (
    OptionsRecherche,
    ResultatSite,
    RunnerMaigretFactice,
    definir_runner,
    runner,
)
from tests.conftest import creer_compte, passer_au_plan
from tests.test_cycle_investigation import site

# --- Le drapeau lui-même ----------------------------------------------------


@pytest.fixture(autouse=True)
def cache_annulation_vierge():
    """Redis est absent en test : le drapeau retombe sur la base, ce qui est le
    comportement dégradé qu'on veut aussi valider."""
    from app.infra.redis_client import reinitialiser_client_redis

    reinitialiser_client_redis()
    yield
    reinitialiser_client_redis()


def _creer_investigation(email: str, plan: str | None = None) -> tuple[TestClient, str]:
    client = TestClient(app)
    reponse = creer_compte(client, email, nom_organisation=f"Org {email}")
    organisation_id = reponse["organisation_active"]
    if plan:
        session = FabriqueSession()
        try:
            passer_au_plan(session, organisation_id, plan)
        finally:
            session.close()
    creation = client.post("/api/v1/investigations", json={"pseudo": "jeanmartin"})
    assert creation.status_code == 201, creation.text
    return client, creation.json()["id"]


def test_annulation_marque_le_statut_et_conserve_les_resultats():
    from app.moteur.annulation import est_annulee

    client, investigation_id = _creer_investigation("annul1@test.fr")

    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        # Simule une recherche déjà partiellement fructueuse
        session.add(
            ProfilIdentite(
                investigation_id=investigation_id,
                organisation_id=investigation.organisation_id,
                site_nom="GitHub", site_domaine="github.com",
                url="https://github.com/jeanmartin", pseudo_sur_le_site="jeanmartin",
                statut_maigret="trouve",
            )
        )
        investigation.statut = StatutInvestigation.EN_COURS.value
        investigation.nb_profils_trouves = 1
        session.commit()
    finally:
        session.close()

    reponse = client.post(f"/api/v1/investigations/{investigation_id}/annuler")
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["statut"] == StatutInvestigation.ANNULEE.value

    session = FabriqueSession()
    try:
        # Le drapeau est visible par les tâches de fond…
        assert est_annulee(investigation_id, session) is True
        # …et le compte déjà trouvé n'est pas perdu.
        profils = session.query(ProfilIdentite).filter(
            ProfilIdentite.investigation_id == investigation_id
        ).all()
        assert len(profils) == 1
    finally:
        session.close()


def test_annulation_impossible_sur_investigation_terminee():
    client, investigation_id = _creer_investigation("annul2@test.fr")

    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        investigation.statut = StatutInvestigation.TERMINEE.value
        session.commit()
    finally:
        session.close()

    reponse = client.post(f"/api/v1/investigations/{investigation_id}/annuler")
    assert reponse.status_code == 409


def test_annulation_dune_investigation_dautrui_renvoie_404():
    """Un 403 confirmerait l'existence de la ressource : même règle que partout."""
    _, investigation_id = _creer_investigation("annul3a@test.fr")
    client_b = TestClient(app)
    creer_compte(client_b, "annul3b@test.fr", nom_organisation="Org annul3b")

    reponse = client_b.post(f"/api/v1/investigations/{investigation_id}/annuler")
    assert reponse.status_code == 404


def test_quota_rendu_seulement_si_rien_na_ete_trouve():
    """Rembourser une recherche déjà fructueuse permettrait d'enchaîner
    « je lance, je récupère, j'annule, je suis remboursé » — soit du volume gratuit
    illimité. Le quota n'est donc rendu que si l'investigation est vide."""
    from app.facturation.quotas import obtenir_compteur

    client, investigation_id = _creer_investigation("annul4@test.fr")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        organisation_id = investigation.organisation_id
        investigation.statut = StatutInvestigation.EN_COURS.value
        session.commit()
        avant = obtenir_compteur(session, organisation_id).compteur_recherches
    finally:
        session.close()

    client.post(f"/api/v1/investigations/{investigation_id}/annuler")

    session = FabriqueSession()
    try:
        apres = obtenir_compteur(session, organisation_id).compteur_recherches
        assert apres == avant - 1, "une investigation vide doit rendre le quota"
    finally:
        session.close()


def test_quota_non_rendu_si_des_comptes_ont_ete_trouves():
    from app.facturation.quotas import obtenir_compteur

    client, investigation_id = _creer_investigation("annul5@test.fr")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        organisation_id = investigation.organisation_id
        investigation.statut = StatutInvestigation.EN_COURS.value
        investigation.nb_profils_trouves = 3
        session.commit()
        avant = obtenir_compteur(session, organisation_id).compteur_recherches
    finally:
        session.close()

    client.post(f"/api/v1/investigations/{investigation_id}/annuler")

    session = FabriqueSession()
    try:
        apres = obtenir_compteur(session, organisation_id).compteur_recherches
        assert apres == avant, "une recherche fructueuse reste décomptée"
    finally:
        session.close()


def test_propositions_de_rebond_en_attente_sont_closes():
    """Laisser une proposition ouverte permettrait de relancer une investigation
    que l'utilisateur vient d'arrêter."""
    client, investigation_id = _creer_investigation("annul6@test.fr", plan="starter")

    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        investigation.statut = StatutInvestigation.EN_COURS.value
        session.add(
            PropositionPivot(
                investigation_id=investigation_id,
                organisation_id=investigation.organisation_id,
                type_pivot="pseudo_alt", valeur="jm_alt", valeur_normalisee="jm_alt",
                action="recherche_maigret",
                profondeur_cible=1, statut=StatutPropositionPivot.EN_ATTENTE.value,
                libelle="pseudonyme découvert",
            )
        )
        session.commit()
    finally:
        session.close()

    client.post(f"/api/v1/investigations/{investigation_id}/annuler")

    session = FabriqueSession()
    try:
        restantes = session.query(PropositionPivot).filter(
            PropositionPivot.investigation_id == investigation_id,
            PropositionPivot.statut == StatutPropositionPivot.EN_ATTENTE.value,
        ).count()
        assert restantes == 0
    finally:
        session.close()


# --- Les tâches de fond respectent-elles le drapeau ? -----------------------


def test_la_recherche_ne_demarre_pas_si_lannulation_precede():
    """Cas réel : l'utilisateur annule pendant que la tâche attend en file."""
    from app.taches.recherche import executer_recherche

    client, investigation_id = _creer_investigation("annul7@test.fr")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        investigation.statut = StatutInvestigation.EN_COURS.value
        session.commit()
    finally:
        session.close()
    client.post(f"/api/v1/investigations/{investigation_id}/annuler")

    original = runner()
    factice = RunnerMaigretFactice({"jeanmartin": [site("GitHub", "jeanmartin", "github.com")]})
    definir_runner(factice)
    try:
        resultat = executer_recherche(
            investigation_id=investigation_id, pseudo="jeanmartin", profondeur=0
        )
    finally:
        definir_runner(original)

    assert resultat["statut"] == "annulee"
    # Maigret ne doit pas avoir été lancé du tout : c'est l'intérêt du contrôle amont.
    assert factice.appels == []


def test_finalisation_ne_repeint_pas_une_investigation_annulee():
    """La finalisation peut arriver après l'annulation (elle était déjà en file)."""
    from app.taches.recherche import finaliser_investigation

    client, investigation_id = _creer_investigation("annul8@test.fr")
    session = FabriqueSession()
    try:
        session.get(Investigation, investigation_id).statut = StatutInvestigation.EN_COURS.value
        session.commit()
    finally:
        session.close()
    client.post(f"/api/v1/investigations/{investigation_id}/annuler")

    resultat = finaliser_investigation(investigation_id=investigation_id)

    assert resultat["statut"] == "annulee"
    session = FabriqueSession()
    try:
        statut = session.get(Investigation, investigation_id).statut
        assert statut == StatutInvestigation.ANNULEE.value
    finally:
        session.close()


def test_le_rebond_ne_part_pas_apres_annulation():
    from app.taches.pivot import detecter_et_pivoter

    client, investigation_id = _creer_investigation("annul9@test.fr", plan="pro")
    session = FabriqueSession()
    try:
        session.get(Investigation, investigation_id).statut = StatutInvestigation.EN_COURS.value
        session.commit()
    finally:
        session.close()
    client.post(f"/api/v1/investigations/{investigation_id}/annuler")

    assert detecter_et_pivoter(investigation_id=investigation_id)["statut"] == "annulee"


def test_lenrichissement_ne_part_pas_apres_annulation():
    from app.taches.enrichissement import enrichir_investigation

    client, investigation_id = _creer_investigation("annul10@test.fr", plan="pro")
    session = FabriqueSession()
    try:
        session.get(Investigation, investigation_id).statut = StatutInvestigation.EN_COURS.value
        session.commit()
    finally:
        session.close()
    client.post(f"/api/v1/investigations/{investigation_id}/annuler")

    assert enrichir_investigation(investigation_id=investigation_id)["statut"] == "annulee"


# --- Interruption du sous-processus Maigret ---------------------------------


def test_le_runner_sarrete_si_lannulation_est_deja_demandee():
    """Le runner factice reproduit le contrat attendu du vrai : un arrêt déjà demandé
    au lancement interrompt sans rien chercher."""
    factice = RunnerMaigretFactice({"jeanmartin": [site("GitHub", "jeanmartin", "github.com")]})
    resultat = factice.lancer(
        "jeanmartin", OptionsRecherche(), doit_arreter=lambda: True
    )
    assert resultat.interrompu is True
    assert resultat.sites == []


def test_le_surveillant_tue_le_sous_processus_quand_larret_est_demande():
    """Vérifie le mécanisme réel sur un vrai sous-processus, sans lancer Maigret.

    C'est le point qui rend l'annulation perceptible : sans lui, arrêter une
    recherche ne produirait aucun effet visible avant la fin de Maigret — jusqu'à
    trente minutes sur une recherche complète.
    """
    import subprocess
    import sys
    import threading
    import time

    from app.moteur.maigret_runner import RunnerMaigretSousProcessus

    # Un processus qui dormirait bien plus longtemps que le test
    processus = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    arret = threading.Event()
    try:
        surveillant = threading.Thread(
            target=RunnerMaigretSousProcessus._surveiller_arret,
            args=(processus, lambda: True, arret),
            daemon=True,
        )
        debut = time.monotonic()
        surveillant.start()
        processus.wait(timeout=15)
        duree = time.monotonic() - debut
    finally:
        arret.set()
        if processus.poll() is None:
            processus.kill()

    assert processus.poll() is not None, "le sous-processus aurait dû être tué"
    assert duree < 10, f"arrêt trop lent ({duree:.1f}s)"


def test_le_surveillant_sarrete_seul_quand_la_recherche_se_termine():
    """Le fil de surveillance ne doit pas survivre à la recherche qu'il surveille."""
    import subprocess
    import sys
    import threading

    from app.moteur.maigret_runner import RunnerMaigretSousProcessus

    processus = subprocess.Popen([sys.executable, "-c", "pass"])
    processus.wait(timeout=15)
    arret = threading.Event()
    surveillant = threading.Thread(
        target=RunnerMaigretSousProcessus._surveiller_arret,
        args=(processus, lambda: False, arret),
        daemon=True,
    )
    surveillant.start()
    surveillant.join(timeout=5)
    assert not surveillant.is_alive(), "le fil de surveillance ne s'est pas arrêté"
