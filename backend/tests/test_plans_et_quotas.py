"""Tests du modèle commercial : quotas, gating par plan, bornage des options.

Ces vérifications protègent le chiffre d'affaires autant que l'infrastructure : un
contournement permettrait d'utiliser gratuitement les fonctionnalités payantes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import FabriqueSession
from app.facturation.abonnements import plan_actif
from app.facturation.garde import (
    FonctionnaliteIndisponible,
    exiger_fonctionnalite,
    mode_pivot_effectif,
    profondeur_pivot_autorisee,
)
from app.facturation.plans import MODULES, PIVOT, PIVOT_AUTOMATIQUE
from app.facturation.quotas import (
    QuotaDepasse,
    consommer_quota,
    etat_quotas,
    periode_courante,
    rembourser_quota,
)
from app.main import app
from app.modeles.enums import ModePivot
from app.modeles.organisation import Organisation
from tests.conftest import creer_compte, passer_au_plan


def _client(email: str, organisation: str = "Organisation") -> tuple[TestClient, str]:
    client = TestClient(app)
    reponse = creer_compte(client, email, nom_organisation=organisation)
    return client, reponse["organisation_active"]


# --- Quotas ----------------------------------------------------------------


def test_quota_bloque_au_dela_de_la_limite():
    session = FabriqueSession()
    try:
        client, organisation_id = _client("quota1@test.fr")
        plan = plan_actif(session, organisation_id)
        assert plan.code == "free"

        # On consomme exactement le quota mensuel du palier, quel qu'il soit
        for _ in range(plan.quota_recherches_mois):
            consommer_quota(session, organisation_id, plan, "recherches")
        session.commit()

        with pytest.raises(QuotaDepasse) as erreur:
            consommer_quota(session, organisation_id, plan, "recherches")
        assert erreur.value.limite == plan.quota_recherches_mois

        del client
    finally:
        session.close()


def test_remboursement_de_quota_apres_echec():
    """Une panne de notre côté ne doit pas être facturée au client."""
    session = FabriqueSession()
    try:
        _, organisation_id = _client("quota2@test.fr")
        plan = plan_actif(session, organisation_id)

        consommer_quota(session, organisation_id, plan, "recherches")
        session.commit()
        avant = etat_quotas(session, organisation_id, plan)["recherches"].consomme

        rembourser_quota(session, organisation_id, "recherches")
        session.commit()
        apres = etat_quotas(session, organisation_id, plan)["recherches"].consomme

        assert apres == avant - 1
    finally:
        session.close()


def test_periode_de_facturation_au_format_mensuel():
    from datetime import datetime, timezone

    assert periode_courante(datetime(2026, 7, 27, tzinfo=timezone.utc)) == "2026-07"
    assert periode_courante(datetime(2026, 12, 1, tzinfo=timezone.utc)) == "2026-12"


def test_limite_dinvestigations_simultanees():
    """Deux limites distinctes coexistent : le quota mensuel de recherches et le
    nombre d'investigations en cours en même temps.

    La seconde protège les workers partagés : sans elle, un client pourrait lancer
    toutes ses recherches du mois d'un coup et bloquer la file pour les autres.
    """
    session = FabriqueSession()
    try:
        client, organisation_id = _client("quota3@test.fr")
        plan = plan_actif(session, organisation_id)
        maximum = plan.quota_investigations_actives   # 3 sur le palier gratuit

        codes = [
            client.post("/api/v1/investigations", json={"pseudo": f"cible{n}"}).status_code
            for n in range(maximum + 2)
        ]
        assert codes.count(201) == maximum
        assert codes[-1] == 429

        # Le quota mensuel, lui, n'est pas épuisé : seules `maximum` recherches ont
        # été consommées, et non la totalité de celles autorisées sur le mois.
        consommees = etat_quotas(session, organisation_id, plan)["recherches"].consomme
        assert consommees == maximum
        assert consommees < plan.quota_recherches_mois
    finally:
        session.close()


def test_quota_mensuel_bloque_meme_apres_cloture_des_investigations():
    """Une fois les investigations terminées, la limite de simultanéité se libère —
    mais le quota mensuel, lui, reste consommé."""
    session = FabriqueSession()
    try:
        from app.modeles.enums import StatutInvestigation
        from app.modeles.investigation import Investigation

        client, organisation_id = _client("quota4@test.fr")
        plan = plan_actif(session, organisation_id)

        codes = []
        for numero in range(plan.quota_recherches_mois + 1):
            reponse = client.post("/api/v1/investigations", json={"pseudo": f"c{numero}"})
            codes.append(reponse.status_code)
            # On clôt aussitôt pour ne jamais buter sur la limite de simultanéité
            for investigation in session.query(Investigation).filter(
                Investigation.organisation_id == organisation_id
            ):
                investigation.statut = StatutInvestigation.TERMINEE.value
            session.commit()

        assert codes.count(201) == plan.quota_recherches_mois
        assert codes[-1] == 429
    finally:
        session.close()


# --- Gating par plan -------------------------------------------------------


def test_plan_gratuit_sans_modules_ni_pivot():
    session = FabriqueSession()
    try:
        _, organisation_id = _client("gratuit@test.fr")
        plan = plan_actif(session, organisation_id)

        assert not plan.possede(MODULES)
        assert not plan.possede(PIVOT)
        assert plan.profondeur_pivot_max == 0

        with pytest.raises(FonctionnaliteIndisponible):
            exiger_fonctionnalite(plan, MODULES)
    finally:
        session.close()


def test_plan_starter_active_modules_et_pivot_supervise():
    session = FabriqueSession()
    try:
        _, organisation_id = _client("starter@test.fr")
        passer_au_plan(session, organisation_id, "starter")

        plan = plan_actif(session, organisation_id)
        assert plan.code == "starter"
        assert plan.possede(MODULES) and plan.possede(PIVOT)
        # Le pivot automatique reste réservé au palier supérieur
        assert not plan.possede(PIVOT_AUTOMATIQUE)
    finally:
        session.close()


def test_mode_automatique_est_ramene_a_supervise_sans_la_fonctionnalite():
    """Une organisation configurée en automatique mais sans le droit n'est pas bloquée :
    elle repasse en supervisé, ce qui reste utilisable."""
    session = FabriqueSession()
    try:
        _, organisation_id = _client("mode@test.fr")
        passer_au_plan(session, organisation_id, "starter")

        organisation = session.get(Organisation, organisation_id)
        organisation.mode_pivot = ModePivot.AUTOMATIQUE.value
        session.commit()

        plan = plan_actif(session, organisation_id)
        assert mode_pivot_effectif(plan, organisation) == ModePivot.SUPERVISE.value

        passer_au_plan(session, organisation_id, "pro")
        plan_pro = plan_actif(session, organisation_id)
        assert mode_pivot_effectif(plan_pro, organisation) == ModePivot.AUTOMATIQUE.value
    finally:
        session.close()


def test_profondeur_bornee_par_le_plan_puis_par_le_serveur():
    session = FabriqueSession()
    try:
        _, organisation_id = _client("profondeur@test.fr")
        organisation = session.get(Organisation, organisation_id)

        plan_gratuit = plan_actif(session, organisation_id)
        # Une demande de profondeur 9 sur le palier gratuit doit tomber à 0
        assert profondeur_pivot_autorisee(plan_gratuit, organisation, 9) == 0

        passer_au_plan(session, organisation_id, "starter")
        plan_starter = plan_actif(session, organisation_id)
        assert profondeur_pivot_autorisee(plan_starter, organisation, 9) == 2

        passer_au_plan(session, organisation_id, "pro")
        plan_pro = plan_actif(session, organisation_id)
        # Plan Pro : 5 niveaux, malgré une demande de 9
        assert profondeur_pivot_autorisee(plan_pro, organisation, 9) == 5
        assert profondeur_pivot_autorisee(plan_pro, organisation, 2) == 2

        # Plan Entreprise : 10 niveaux. Le plafond serveur doit être au moins égal à ce
        # que le palier le plus élevé annonce, sans quoi il l'écraserait en silence.
        passer_au_plan(session, organisation_id, "entreprise")
        plan_entreprise = plan_actif(session, organisation_id)
        assert profondeur_pivot_autorisee(plan_entreprise, organisation, 10) == 10
    finally:
        session.close()


def test_options_client_bornees_a_la_creation():
    """Le client demande une profondeur de 9 : le serveur enregistre ce qu'il autorise."""
    client, _ = _client("options@test.fr")
    reponse = client.post(
        "/api/v1/investigations",
        json={"pseudo": "cible_options", "profondeur_pivot": 9, "mode_pivot": "automatique"},
    )
    assert reponse.status_code == 201
    options = reponse.json()["options"]
    assert options["profondeur"] == 0                 # palier gratuit
    assert options["mode_pivot"] == "supervise"       # automatique non inclus


def test_enrichissement_refuse_sur_plan_gratuit():
    client, _ = _client("enrich@test.fr")
    investigation = client.post("/api/v1/investigations", json={"pseudo": "cible_enrich"}).json()
    reponse = client.post(
        f"/api/v1/investigations/{investigation['id']}/profils/inexistant/enrichir"
    )
    # Profil inexistant OU fonctionnalité indisponible : dans les deux cas, jamais 200
    assert reponse.status_code in (403, 404)


def test_export_csv_reserve_aux_plans_payants():
    session = FabriqueSession()
    try:
        client, organisation_id = _client("export@test.fr")
        investigation = client.post("/api/v1/investigations", json={"pseudo": "cible_export"}).json()

        refus = client.get(f"/api/v1/investigations/{investigation['id']}/export?format=csv")
        assert refus.status_code == 403

        # Le JSON reste accessible à tous : sans lui, un client gratuit ne pourrait
        # pas récupérer ses propres données (obligation RGPD de portabilité).
        assert client.get(f"/api/v1/investigations/{investigation['id']}/export?format=json").status_code == 200

        passer_au_plan(session, organisation_id, "starter")
        assert client.get(f"/api/v1/investigations/{investigation['id']}/export?format=csv").status_code == 200
    finally:
        session.close()


def test_page_abonnement_expose_quotas_et_upsell():
    client, _ = _client("abo@test.fr")
    reponse = client.get("/api/v1/abonnement")
    assert reponse.status_code == 200

    contenu = reponse.json()
    assert contenu["plan"]["code"] == "free"
    assert {q["nom"] for q in contenu["quotas"]} >= {"recherches", "enrichissements"}
    # Un palier supérieur doit être proposé pour permettre la montée en gamme
    assert contenu["plan_superieur"] is not None
    assert contenu["plan_superieur"]["code"] == "starter"


def test_limite_du_nombre_dutilisateurs_du_plan():
    client, _ = _client("equipe@test.fr", "Equipe")
    # Le palier gratuit est limité à un seul utilisateur : l'invitation doit échouer
    reponse = client.post(
        "/api/v1/organisation/invitations", json={"email": "collegue@test.fr", "role": "analyste"}
    )
    assert reponse.status_code == 403
    assert "utilisateur" in reponse.json()["detail"].lower()
