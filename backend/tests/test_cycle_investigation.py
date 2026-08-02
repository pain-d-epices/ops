"""Test du cycle complet d'une investigation, avec un Maigret simulé.

Valide l'enchaînement réel : recherche → enregistrement des profils → corrélation →
graphe → détection de pivots → arbitrage selon le plan. Aucun accès réseau : le
runner Maigret est remplacé par une version déterministe.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import FabriqueSession
from app.facturation.abonnements import plan_actif
from app.main import app
from app.modeles.enums import StatutMaigret, StatutPropositionPivot, TypeDonnee, TypeNoeud
from app.modeles.investigation import ExecutionRecherche, Investigation, ProfilIdentite
from app.modeles.organisation import Organisation
from app.moteur.graphe.depot import DepotGraphe
from app.moteur.maigret_runner import (
    ResultatSite,
    RunnerMaigretFactice,
    definir_runner,
    runner,
)
from app.moteur.pivot.detecteur import DetecteurPivot, DonneeCandidate, pseudo_exploitable
from app.moteur.pivot.orchestrateur import OrchestrateurPivot
from app.services.investigation import (
    _ajouter_donnee,
    collecter_donnees_pivotables,
    enregistrer_resultats_maigret,
    rescorer_investigation,
)
from tests.conftest import creer_compte, passer_au_plan


def site(nom: str, pseudo: str, domaine: str | None = None, **kwargs) -> ResultatSite:
    domaine = domaine or f"{nom.lower()}.com"
    return ResultatSite(
        site_nom=nom,
        site_domaine=domaine,
        url=kwargs.pop("url", f"https://{domaine}/{pseudo}"),
        pseudo=pseudo,
        statut=StatutMaigret.TROUVE,
        **kwargs,
    )


@pytest.fixture
def runner_factice():
    """Remplace Maigret par un runner déterministe, et le restaure ensuite."""
    original = runner()
    factice = RunnerMaigretFactice(
        {
            "jeanmartin": [
                site("GitHub", "jeanmartin", "github.com"),
                site("Mastodon", "jeanmartin", "mastodon.social"),
                site("Instructables", "jeanmartin", "www.instructables.com", est_similaire=True),
            ],
            "jm_alternatif": [site("GitLab", "jm_alternatif", "gitlab.com")],
        }
    )
    definir_runner(factice)
    yield factice
    definir_runner(original)


def _preparer_investigation(email: str, plan: str | None = None) -> tuple[str, str]:
    """Crée un compte et une investigation. Renvoie (investigation_id, organisation_id)."""
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
    return creation.json()["id"], organisation_id


# --- Enregistrement et corrélation -----------------------------------------


def test_enregistrement_cree_profils_et_graphe(runner_factice):
    investigation_id, _ = _preparer_investigation("cycle1@test.fr")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        execution = ExecutionRecherche(
            investigation_id=investigation.id,
            organisation_id=investigation.organisation_id,
            pseudo_recherche="jeanmartin",
            profondeur=0,
            statut="terminee",
        )
        session.add(execution)
        session.flush()

        resultat = runner_factice.lancer("jeanmartin")
        bilan = enregistrer_resultats_maigret(session, investigation, execution, resultat)
        session.commit()

        assert bilan.profils_crees == 3
        profils = session.query(ProfilIdentite).filter(
            ProfilIdentite.investigation_id == investigation_id
        ).all()
        assert {p.site_nom for p in profils} == {"GitHub", "Mastodon", "Instructables"}

        # Le graphe contient le nœud racine et un nœud par compte
        depot = DepotGraphe(session, investigation.id, investigation.organisation_id)
        noeuds, aretes = depot.compter()
        assert noeuds == 4      # 1 pseudo + 3 comptes
        assert aretes == 3
    finally:
        session.close()


def test_relancer_le_meme_compte_ne_cree_pas_de_doublon(runner_factice):
    investigation_id, _ = _preparer_investigation("cycle2@test.fr")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        resultat = runner_factice.lancer("jeanmartin")

        for _ in range(2):
            execution = ExecutionRecherche(
                investigation_id=investigation.id,
                organisation_id=investigation.organisation_id,
                pseudo_recherche="jeanmartin",
                profondeur=0,
                statut="terminee",
            )
            session.add(execution)
            session.flush()
            enregistrer_resultats_maigret(session, investigation, execution, resultat)
        session.commit()

        profils = session.query(ProfilIdentite).filter(
            ProfilIdentite.investigation_id == investigation_id
        ).all()
        assert len(profils) == 3   # et non six
    finally:
        session.close()


def test_correlation_classe_les_profils(runner_factice):
    investigation_id, _ = _preparer_investigation("cycle3@test.fr")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        execution = ExecutionRecherche(
            investigation_id=investigation.id,
            organisation_id=investigation.organisation_id,
            pseudo_recherche="jeanmartin", profondeur=0, statut="terminee",
        )
        session.add(execution)
        session.flush()
        enregistrer_resultats_maigret(
            session, investigation, execution, runner_factice.lancer("jeanmartin")
        )

        # Deux profils partagent la même adresse : la corroboration doit les faire monter
        for profil in session.query(ProfilIdentite).filter(
            ProfilIdentite.site_nom.in_(["GitHub", "Mastodon"])
        ):
            _ajouter_donnee(
                session, investigation, profil,
                type_donnee=TypeDonnee.EMAIL, valeur="jean@exemple.fr", module_source="test",
            )

        rescorer_investigation(session, investigation)
        session.commit()

        scores = {
            p.site_nom: p.score_confiance
            for p in session.query(ProfilIdentite).filter(
                ProfilIdentite.investigation_id == investigation_id
            )
        }
        assert scores["GitHub"] > scores["Instructables"]
        assert scores["Mastodon"] > scores["Instructables"]
        # Le résultat approximatif sur un site peu fiable doit rester bas
        assert scores["Instructables"] < 40
    finally:
        session.close()


# --- Détection de pivots ---------------------------------------------------


def test_pseudos_inexploitables_ecartes():
    assert pseudo_exploitable("jeanmartin")
    assert not pseudo_exploitable("admin")     # trop générique
    assert not pseudo_exploitable("ab")        # trop court
    assert not pseudo_exploitable("12345")     # suite de chiffres
    assert not pseudo_exploitable("")


def test_detection_des_pivots_par_type():
    donnees = [
        DonneeCandidate("1", TypeDonnee.PSEUDO_ALT.value, "jm_alternatif", "jmalternatif", "p1", "GitHub"),
        DonneeCandidate("2", TypeDonnee.EMAIL.value, "jean.martin@exemple.fr",
                        "jean.martin@exemple.fr", "p1", "GitHub"),
        DonneeCandidate("3", TypeDonnee.BIO.value, "une biographie", "une biographie", "p1", "GitHub"),
        DonneeCandidate("4", TypeDonnee.PSEUDO_ALT.value, "admin", "admin", "p1", "GitHub"),
    ]
    pivots = DetecteurPivot().detecter(donnees)
    valeurs = {p.valeur for p in pivots}

    assert "jm_alternatif" in valeurs
    assert "jean.martin" in valeurs     # partie locale de l'adresse
    assert "une biographie" not in valeurs   # une bio n'est pas un point de rebond
    assert "admin" not in valeurs            # pseudonyme générique écarté


def test_anti_cycle_du_pivot():
    """Une valeur déjà explorée ne doit jamais relancer une recherche."""
    from app.moteur.pivot.detecteur import ACTION_RECHERCHE

    donnees = [
        DonneeCandidate("1", TypeDonnee.PSEUDO_ALT.value, "jeanmartin", "jeanmartin", "p1", "GitHub")
    ]
    detecteur = DetecteurPivot(valeurs_deja_explorees={f"{ACTION_RECHERCHE}:jeanmartin"})
    assert detecteur.detecter(donnees) == []


def test_doublons_dans_un_meme_lot_ignores():
    donnees = [
        DonneeCandidate("1", TypeDonnee.PSEUDO_ALT.value, "jm_alternatif", "jmalternatif", "p1", "GitHub"),
        DonneeCandidate("2", TypeDonnee.PSEUDO_ALT.value, "jm_alternatif", "jmalternatif", "p2", "Mastodon"),
    ]
    assert len(DetecteurPivot().detecter(donnees)) == 1


# --- Arbitrage du pivot selon le plan --------------------------------------


def _pivots_de_test(session, investigation, score_minimal=0):
    profil = session.query(ProfilIdentite).filter(
        ProfilIdentite.investigation_id == investigation.id
    ).first()
    _ajouter_donnee(
        session, investigation, profil,
        type_donnee=TypeDonnee.PSEUDO_ALT, valeur="jm_alternatif", module_source="test",
    )
    session.flush()
    candidates = collecter_donnees_pivotables(session, investigation, score_minimal)
    return DetecteurPivot().detecter(candidates)


def test_plan_gratuit_propose_un_rebond_mais_ne_lexecute_jamais(runner_factice):
    """Le palier gratuit dispose d'un niveau de rebond, en mode supervisé uniquement.

    Il faut donc qu'il *propose* — c'est ce qui démontre la fonctionnalité — sans
    jamais lancer de recherche de lui-même : le rebond automatique reste payant.
    """
    investigation_id, organisation_id = _preparer_investigation("pivot_gratuit@test.fr")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        execution = ExecutionRecherche(
            investigation_id=investigation.id, organisation_id=organisation_id,
            pseudo_recherche="jeanmartin", profondeur=0, statut="terminee",
        )
        session.add(execution)
        session.flush()
        enregistrer_resultats_maigret(
            session, investigation, execution, runner_factice.lancer("jeanmartin")
        )
        rescorer_investigation(session, investigation)

        pivots = _pivots_de_test(session, investigation)
        assert pivots, "le jeu de test doit produire au moins un pivot détectable"

        organisation = session.get(Organisation, organisation_id)
        plan = plan_actif(session, organisation_id)
        decision = OrchestrateurPivot(session, investigation, organisation, plan).arbitrer(pivots, 0)
        session.commit()

        assert len(decision.a_executer) == 0, "le rebond automatique reste payant"
        assert len(decision.en_attente) >= 1
    finally:
        session.close()


def test_plan_gratuit_bloque_le_rebond_au_dela_du_premier_niveau(runner_factice):
    """Un seul niveau : au niveau 1, plus rien n'est retenu, même en supervisé."""
    investigation_id, organisation_id = _preparer_investigation("pivot_gratuit2@test.fr")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        execution = ExecutionRecherche(
            investigation_id=investigation.id, organisation_id=organisation_id,
            pseudo_recherche="jeanmartin", profondeur=0, statut="terminee",
        )
        session.add(execution)
        session.flush()
        enregistrer_resultats_maigret(
            session, investigation, execution, runner_factice.lancer("jeanmartin")
        )
        rescorer_investigation(session, investigation)

        pivots = _pivots_de_test(session, investigation)
        organisation = session.get(Organisation, organisation_id)
        plan = plan_actif(session, organisation_id)
        decision = OrchestrateurPivot(session, investigation, organisation, plan).arbitrer(pivots, 1)

        assert decision.total_retenus == 0
    finally:
        session.close()


def test_plan_starter_propose_le_pivot_sans_lexecuter(runner_factice):
    """Mode supervisé : la proposition est créée, mais aucune recherche n'est lancée."""
    investigation_id, organisation_id = _preparer_investigation("pivot_starter@test.fr", "starter")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        execution = ExecutionRecherche(
            investigation_id=investigation.id, organisation_id=organisation_id,
            pseudo_recherche="jeanmartin", profondeur=0, statut="terminee",
        )
        session.add(execution)
        session.flush()
        enregistrer_resultats_maigret(
            session, investigation, execution, runner_factice.lancer("jeanmartin")
        )
        rescorer_investigation(session, investigation)

        pivots = _pivots_de_test(session, investigation)
        organisation = session.get(Organisation, organisation_id)
        plan = plan_actif(session, organisation_id)
        decision = OrchestrateurPivot(session, investigation, organisation, plan).arbitrer(pivots, 0)
        session.commit()

        assert len(decision.a_executer) == 0
        assert len(decision.en_attente) >= 1
        assert decision.en_attente[0].statut == StatutPropositionPivot.EN_ATTENTE.value
    finally:
        session.close()


def test_plan_pro_en_mode_automatique_execute_directement(runner_factice):
    investigation_id, organisation_id = _preparer_investigation("pivot_pro@test.fr", "pro")
    session = FabriqueSession()
    try:
        organisation = session.get(Organisation, organisation_id)
        organisation.mode_pivot = "automatique"
        investigation = session.get(Investigation, investigation_id)
        investigation.options = {**(investigation.options or {}), "mode_pivot": "automatique",
                                 "profondeur": 3}
        session.commit()

        execution = ExecutionRecherche(
            investigation_id=investigation.id, organisation_id=organisation_id,
            pseudo_recherche="jeanmartin", profondeur=0, statut="terminee",
        )
        session.add(execution)
        session.flush()
        enregistrer_resultats_maigret(
            session, investigation, execution, runner_factice.lancer("jeanmartin")
        )
        rescorer_investigation(session, investigation)

        pivots = _pivots_de_test(session, investigation)
        plan = plan_actif(session, organisation_id)
        decision = OrchestrateurPivot(session, investigation, organisation, plan).arbitrer(pivots, 0)
        session.commit()

        assert len(decision.a_executer) >= 1
        assert decision.a_executer[0].statut == StatutPropositionPivot.AUTOMATIQUE.value
        assert decision.a_executer[0].profondeur_cible == 1
    finally:
        session.close()


def test_profondeur_maximale_stoppe_la_cascade(runner_factice):
    """Au dernier niveau autorisé, plus aucun pivot n'est retenu."""
    investigation_id, organisation_id = _preparer_investigation("pivot_profondeur@test.fr", "starter")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        execution = ExecutionRecherche(
            investigation_id=investigation.id, organisation_id=organisation_id,
            pseudo_recherche="jeanmartin", profondeur=0, statut="terminee",
        )
        session.add(execution)
        session.flush()
        enregistrer_resultats_maigret(
            session, investigation, execution, runner_factice.lancer("jeanmartin")
        )
        rescorer_investigation(session, investigation)

        pivots = _pivots_de_test(session, investigation)
        organisation = session.get(Organisation, organisation_id)
        plan = plan_actif(session, organisation_id)   # Starter : profondeur maximale 1

        orchestrateur = OrchestrateurPivot(session, investigation, organisation, plan)
        # Depuis la profondeur 1, un pivot viserait la profondeur 2 : refusé
        decision = orchestrateur.arbitrer(pivots, profondeur_source=1)
        assert decision.total_retenus == 0
        assert any("profondeur" in raison for _, raison in decision.ignores)
    finally:
        session.close()


def test_graphe_deduplique_les_informations_communes(runner_factice):
    """Deux comptes menant au même email doivent converger vers un nœud unique :
    c'est cette convergence qui fait apparaître visuellement le lien."""
    investigation_id, organisation_id = _preparer_investigation("graphe@test.fr", "starter")
    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        execution = ExecutionRecherche(
            investigation_id=investigation.id, organisation_id=organisation_id,
            pseudo_recherche="jeanmartin", profondeur=0, statut="terminee",
        )
        session.add(execution)
        session.flush()
        enregistrer_resultats_maigret(
            session, investigation, execution, runner_factice.lancer("jeanmartin")
        )

        depot = DepotGraphe(session, investigation.id, organisation_id)
        noeuds_avant, _ = depot.compter()

        for profil in session.query(ProfilIdentite).filter(
            ProfilIdentite.site_nom.in_(["GitHub", "Mastodon"])
        ):
            noeud_compte = depot.obtenir_ou_creer_noeud(
                TypeNoeud.COMPTE, profil.url, profil_id=profil.id
            )
            noeud_email = depot.obtenir_ou_creer_noeud(TypeNoeud.EMAIL, "jean@exemple.fr")
            depot.creer_arete(noeud_compte, noeud_email, "information_extraite")
        session.commit()

        noeuds_apres, aretes_apres = depot.compter()
        assert noeuds_apres == noeuds_avant + 1   # un seul nœud email, pas deux
        assert aretes_apres >= 5                  # 3 comptes + 2 arêtes vers l'email
    finally:
        session.close()


# --- Élément de départ principal de type quelconque -------------------------


def test_lancer_investigation_relance_maigret_sur_pseudonyme_decouvert(runner_factice):
    """Démarrer d'un compte (et non d'un pseudonyme) doit tout de même déclencher la
    recherche large, à partir du pseudonyme extrait de l'adresse fournie."""
    from app.modeles.investigation import PointDepart
    from app.taches.recherche import lancer_investigation

    client = TestClient(app)
    reponse = creer_compte(client, "compte_pivot@test.fr", nom_organisation="Org compte pivot")
    organisation_id = reponse["organisation_active"]
    session = FabriqueSession()
    try:
        passer_au_plan(session, organisation_id, "pro")
    finally:
        session.close()

    creation = client.post(
        "/api/v1/investigations",
        json={"pseudo": "https://github.com/jeanmartin", "type_principal": "compte"},
    )
    assert creation.status_code == 201, creation.text
    investigation_id = creation.json()["id"]

    resultat = lancer_investigation(investigation_id)
    assert resultat["pseudos_decouverts"] == ["jeanmartin"]

    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        noms_sites = {
            p.site_nom
            for p in session.query(ProfilIdentite).filter(
                ProfilIdentite.investigation_id == investigation_id
            )
        }
        assert "GitHub" in noms_sites      # le compte fourni par l'analyste
        assert "Mastodon" in noms_sites    # trouvé par la recherche large déclenchée
        assert investigation.nb_recherches_effectuees == 1

        point_principal = (
            session.query(PointDepart)
            .filter(PointDepart.investigation_id == investigation_id)
            .order_by(PointDepart.created_at)
            .first()
        )
        assert point_principal.type == "compte"
    finally:
        session.close()


def test_lancer_investigation_saute_la_recherche_large_sans_pseudonyme(runner_factice):
    """Démarrer d'un compte sur un domaine générique ne permet d'extraire aucun
    pseudonyme exploitable : Maigret ne doit pas être lancé sur une valeur qui n'en
    est pas un."""
    from app.taches.recherche import lancer_investigation

    client = TestClient(app)
    reponse = creer_compte(client, "compte_sans_pivot@test.fr", nom_organisation="Org sans pivot")
    organisation_id = reponse["organisation_active"]
    session = FabriqueSession()
    try:
        passer_au_plan(session, organisation_id, "pro")
    finally:
        session.close()

    # "example.com" figure parmi les domaines génériques (DOMAINES_NON_PIVOTABLES,
    # app.modules.base) : aucun pseudonyme n'en est extrait.
    creation = client.post(
        "/api/v1/investigations",
        json={"pseudo": "https://example.com/jeanmartin", "type_principal": "compte"},
    )
    assert creation.status_code == 201, creation.text
    investigation_id = creation.json()["id"]

    resultat = lancer_investigation(investigation_id)
    assert resultat["pseudos_decouverts"] == []

    session = FabriqueSession()
    try:
        investigation = session.get(Investigation, investigation_id)
        assert investigation.nb_recherches_effectuees == 0   # Maigret jamais lancé
        profils = list(
            session.query(ProfilIdentite).filter(
                ProfilIdentite.investigation_id == investigation_id
            )
        )
        assert len(profils) == 1                              # seulement le compte fourni
        assert profils[0].site_domaine == "example.com"
    finally:
        session.close()


# --- Sources complémentaires (recherche web / dark web) ---------------------


class _SourceFactice:
    """Source complémentaire déterministe, pour vérifier le branchement dans
    `executer_recherche` sans dépendre de DuckDuckGo ou Ahmia."""

    nom = "source_factice"
    libelle = "Source factice"
    categorie = "web"

    def __init__(self, sites):
        self._sites = sites
        self.appels: list[str] = []

    def disponible(self) -> bool:
        return True

    def rechercher(self, pseudo: str):
        from app.moteur.sources.base import ResultatSource

        self.appels.append(pseudo)
        return ResultatSource(source=self.nom, sites=list(self._sites), nb_resultats_bruts=len(self._sites))


def test_recherche_etendue_absente_pour_le_plan_gratuit(runner_factice, monkeypatch):
    """Le palier gratuit ne doit jamais déclencher les sources complémentaires : ni
    appel réseau, ni profil supplémentaire dans le graphe."""
    from app.taches.recherche import lancer_investigation

    source = _SourceFactice([site("Blog", "jeanmartin", "blog-jeanmartin.fr")])
    monkeypatch.setattr("app.moteur.sources.registre.sources_disponibles", lambda: [source])

    investigation_id, _ = _preparer_investigation("gratuit_source@test.fr")
    lancer_investigation(investigation_id)

    assert source.appels == []
    session = FabriqueSession()
    try:
        noms_sites = {
            p.site_nom
            for p in session.query(ProfilIdentite).filter(
                ProfilIdentite.investigation_id == investigation_id
            )
        }
        assert "Blog" not in noms_sites
    finally:
        session.close()


def test_recherche_etendue_fusionne_les_sources_pour_un_plan_starter(runner_factice, monkeypatch):
    """Un plan qui inclut RECHERCHE_ETENDUE doit voir les résultats des sources
    complémentaires apparaître comme des profils normaux, fusionnés à ceux de Maigret."""
    from app.taches.recherche import lancer_investigation

    source = _SourceFactice([site("Blog", "jeanmartin", "blog-jeanmartin.fr")])
    monkeypatch.setattr("app.moteur.sources.registre.sources_disponibles", lambda: [source])

    investigation_id, organisation_id = _preparer_investigation("starter_source@test.fr", plan="starter")
    lancer_investigation(investigation_id)

    assert source.appels == ["jeanmartin"]
    session = FabriqueSession()
    try:
        noms_sites = {
            p.site_nom
            for p in session.query(ProfilIdentite).filter(
                ProfilIdentite.investigation_id == investigation_id
            )
        }
        # Les comptes Maigret et le résultat de la source complémentaire coexistent.
        assert {"GitHub", "Mastodon", "Blog"} <= noms_sites
    finally:
        session.close()


def test_recherche_etendue_ne_duplique_pas_un_compte_deja_trouve_par_maigret(
    runner_factice, monkeypatch
):
    """Une source qui retomberait sur une URL déjà trouvée par Maigret ne doit pas
    créer de doublon (même règle de déduplication que le reste du pipeline)."""
    from app.taches.recherche import lancer_investigation

    doublon = site("GitHub bis", "jeanmartin", "github.com", url="https://github.com/jeanmartin")
    source = _SourceFactice([doublon])
    monkeypatch.setattr("app.moteur.sources.registre.sources_disponibles", lambda: [source])

    investigation_id, _ = _preparer_investigation("starter_doublon@test.fr", plan="starter")
    lancer_investigation(investigation_id)

    session = FabriqueSession()
    try:
        profils_github = list(
            session.query(ProfilIdentite).filter(
                ProfilIdentite.investigation_id == investigation_id,
                ProfilIdentite.site_domaine == "github.com",
            )
        )
        assert len(profils_github) == 1
        assert profils_github[0].site_nom == "GitHub"  # la version Maigret l'emporte
    finally:
        session.close()
