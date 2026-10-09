"""Création de compte en ligne de commande.

Le compte produit doit être strictement équivalent à celui d'une inscription web : même
politique de mot de passe, même unicité d'adresse, même trace de consentement, et un
rôle d'administrateur sur une organisation neuve.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.v1.auth import VERSION_CGU
from app.modeles import Appartenance, Organisation, Utilisateur
from app.modeles.enums import RoleMembre
from app.scripts.creer_compte import CreationImpossible, creer_compte, main
from app.securite.mots_de_passe import verifier

MOT_DE_PASSE = "MotDePasseDeTest2026"


def test_le_compte_cree_est_administrateur_de_son_organisation(session):
    identifiant, nom_organisation = creer_compte(
        email="ligne-de-commande@exemple.fr",
        mot_de_passe=MOT_DE_PASSE,
        nom_organisation="Cabinet en ligne de commande",
    )
    assert nom_organisation == "Cabinet en ligne de commande"

    utilisateur = session.get(Utilisateur, identifiant)
    assert utilisateur.email == "ligne-de-commande@exemple.fr"
    assert verifier(MOT_DE_PASSE, utilisateur.mot_de_passe_hash)
    # La trace du consentement est celle du formulaire web, pas une valeur inventée.
    assert utilisateur.cgu_version_acceptee == VERSION_CGU
    assert utilisateur.cgu_acceptees_le is not None

    appartenance = session.scalar(
        select(Appartenance).where(Appartenance.utilisateur_id == identifiant)
    )
    assert appartenance.role == RoleMembre.ADMIN.value
    assert session.get(Organisation, appartenance.organisation_id).slug == (
        "cabinet-en-ligne-de-commande"
    )


def test_l_adresse_est_normalisee_et_le_nom_d_organisation_deduit(session):
    identifiant, nom_organisation = creer_compte(
        email="  MAJUSCULES@Exemple.FR  ", mot_de_passe=MOT_DE_PASSE
    )
    assert session.get(Utilisateur, identifiant).email == "majuscules@exemple.fr"
    assert nom_organisation == "Organisation de majuscules"


def test_une_adresse_deja_prise_est_refusee():
    creer_compte(email="doublon@exemple.fr", mot_de_passe=MOT_DE_PASSE)
    with pytest.raises(CreationImpossible, match="existe déjà"):
        creer_compte(email="doublon@exemple.fr", mot_de_passe=MOT_DE_PASSE)


def test_la_politique_de_mot_de_passe_s_applique():
    with pytest.raises(CreationImpossible, match="12 caractères"):
        creer_compte(email="trop-court@exemple.fr", mot_de_passe="court")


def test_une_adresse_malformee_est_refusee():
    with pytest.raises(CreationImpossible, match="invalide"):
        creer_compte(email="pas-une-adresse", mot_de_passe=MOT_DE_PASSE)


def test_le_cadre_legal_doit_etre_accepte_explicitement():
    """Sans le drapeau, rien n'est créé : le consentement ne se présume pas."""
    code = main(["--email", "sans-accord@exemple.fr", "--mot-de-passe", MOT_DE_PASSE])
    assert code == 2


def test_la_commande_complete_cree_le_compte(session):
    code = main([
        "--email", "avec-accord@exemple.fr",
        "--mot-de-passe", MOT_DE_PASSE,
        "--organisation", "Accord donné",
        "--accepter-cadre-legal",
    ])
    assert code == 0
    assert session.scalar(
        select(Utilisateur.id).where(Utilisateur.email == "avec-accord@exemple.fr")
    )


def test_la_commande_signale_une_erreur_sans_lever(session):
    """Un échec doit sortir en code 1, pas en trace d'exception."""
    code = main([
        "--email", "echec@exemple.fr", "--mot-de-passe", "court", "--accepter-cadre-legal",
    ])
    assert code == 1
    assert not session.scalar(
        select(Utilisateur.id).where(Utilisateur.email == "echec@exemple.fr")
    )
