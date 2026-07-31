"""Tests de l'export PDF des investigations.

L'export CSV est déjà couvert dans `test_plans_et_quotas.py` : ici, on ne teste que ce
qui est spécifique au PDF (gating par plan, contenu du fichier produit).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import FabriqueSession
from app.main import app
from tests.conftest import creer_compte, passer_au_plan


def _client(email: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    reponse = creer_compte(client, email, nom_organisation="Organisation export PDF")
    return client, reponse["organisation_active"]


def test_export_pdf_reserve_aux_plans_avec_la_fonctionnalite():
    session = FabriqueSession()
    try:
        client, organisation_id = _client("export-pdf@test.fr")
        investigation = client.post("/api/v1/investigations", json={"pseudo": "cible_export_pdf"}).json()

        # Palier gratuit : ni CSV ni PDF
        assert client.get(f"/api/v1/investigations/{investigation['id']}/export?format=pdf").status_code == 403

        # Starter possède export_csv mais pas export_pdf (voir app/facturation/plans.py)
        passer_au_plan(session, organisation_id, "starter")
        assert client.get(f"/api/v1/investigations/{investigation['id']}/export?format=pdf").status_code == 403

        passer_au_plan(session, organisation_id, "pro")
        reponse = client.get(f"/api/v1/investigations/{investigation['id']}/export?format=pdf")
        assert reponse.status_code == 200
        assert reponse.headers["content-type"] == "application/pdf"
        assert reponse.content.startswith(b"%PDF")
    finally:
        session.close()


def test_export_pdf_echappe_le_contenu_extrait_des_sites():
    """Une donnée extraite d'un site tiers ne doit jamais casser la mise en page ou
    injecter une balise dans le PDF (reportlab interprète le texte comme du XML)."""
    from app.services.export_pdf import generer_rapport_pdf

    class FauxInvestigation:
        pseudo_initial = "cible"

    class FauxProfil:
        id = "p1"
        site_nom = "Site <test>"
        pseudo_sur_le_site = "cible"
        score_confiance = 0.5
        niveau = "moyen"
        profondeur = 0
        url = "https://exemple.test/cible"

    class FausseDonnee:
        profil_id = "p1"
        type = "bio"
        valeur = "<script>alert(1)</script> & compagnie"

    pdf = generer_rapport_pdf(
        FauxInvestigation(), [FauxProfil()], {"p1": [FausseDonnee()]},
        organisation_nom="Organisation & Associés",
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500
