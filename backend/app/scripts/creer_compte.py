"""Création d'un compte en ligne de commande, sans passer par le formulaire.

    python -m app.scripts.creer_compte --email vous@exemple.fr --organisation "Mon cabinet"

Sur une installation neuve, l'inscription web impose une épreuve anti-robot résolue par
le navigateur et un plafond de créations par adresse IP : deux protections utiles contre
un inconnu, sans objet pour l'opérateur qui installe l'outil chez lui. Ce script
court-circuite ces deux contrôles — et seulement ceux-là. La politique de mot de passe,
l'unicité de l'adresse et la trace au journal restent appliquées à l'identique.

Le compte créé est administrateur de son organisation. Sans `--mot-de-passe`, la saisie
est demandée en clavier masqué : l'écrire dans la commande le laisse dans l'historique
du terminal.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import re
import sys

from sqlalchemy import select

# Les deux fonctions de nommage et la version du cadre légal sont reprises de
# l'inscription web : les dupliquer ici les ferait diverger au premier changement.
from app.api.v1.auth import VERSION_CGU, _slug_disponible, _slugifier
from app.db.base import maintenant, nouvel_id
from app.db.session import portee_session
from app.modeles import Appartenance, Organisation, Utilisateur
from app.modeles.enums import ActionJournal, RoleMembre
from app.securite.mots_de_passe import MotDePasseInvalide, hacher, valider_politique
from app.services.journal import journaliser

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
journal = logging.getLogger("creer_compte")

#: Validation volontairement permissive : seule une adresse manifestement malformée est
#: refusée. Aucun courriel n'étant envoyé, une faute de frappe n'a pas de conséquence
#: au-delà du compte lui-même.
MOTIF_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class CreationImpossible(RuntimeError):
    """Le compte n'a pas pu être créé ; le message porte la raison."""


def creer_compte(
    email: str,
    mot_de_passe: str,
    nom_organisation: str | None = None,
    nom_complet: str | None = None,
) -> tuple[str, str]:
    """Crée l'utilisateur, son organisation et son appartenance d'administrateur.

    Retourne l'identifiant de l'utilisateur et le nom de l'organisation.
    """
    email = email.strip().lower()
    if not MOTIF_EMAIL.match(email):
        raise CreationImpossible(f"Adresse électronique invalide : {email}")

    try:
        valider_politique(mot_de_passe)
    except MotDePasseInvalide as exc:
        raise CreationImpossible(str(exc)) from exc

    with portee_session() as session:
        if session.scalar(select(Utilisateur.id).where(Utilisateur.email == email)):
            raise CreationImpossible(
                f"Un compte existe déjà avec l'adresse {email}. "
                "Utilisez le formulaire de connexion de l'interface."
            )

        utilisateur = Utilisateur(
            id=nouvel_id(),
            email=email,
            mot_de_passe_hash=hacher(mot_de_passe),
            nom_complet=nom_complet,
            # Le drapeau --accepter-cadre-legal est obligatoire sur la commande : la
            # trace du consentement vaut celle du formulaire web.
            cgu_acceptees_le=maintenant(),
            cgu_version_acceptee=VERSION_CGU,
        )
        session.add(utilisateur)
        session.flush()

        nom = nom_organisation or f"Organisation de {email.split('@')[0]}"
        organisation = Organisation(
            id=nouvel_id(),
            nom=nom[:150],
            slug=_slug_disponible(session, _slugifier(nom)),
        )
        session.add(organisation)
        session.flush()

        session.add(
            Appartenance(
                utilisateur_id=utilisateur.id,
                organisation_id=organisation.id,
                role=RoleMembre.ADMIN.value,
            )
        )
        journaliser(
            session,
            ActionJournal.INSCRIPTION,
            organisation_id=organisation.id,
            utilisateur_id=utilisateur.id,
            email_utilisateur=email,
            detail={"cgu_version": VERSION_CGU, "origine": "ligne de commande"},
        )
        session.flush()
        return utilisateur.id, organisation.nom


def _demander_mot_de_passe() -> str:
    """Deux saisies masquées concordantes, puisque rien ne permettra de le relire."""
    premiere = getpass.getpass("Mot de passe (12 caractères minimum) : ")
    seconde = getpass.getpass("Confirmation : ")
    if premiere != seconde:
        raise CreationImpossible("Les deux saisies diffèrent.")
    return premiere


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="python -m app.scripts.creer_compte",
        description="Crée un compte administrateur sans passer par le formulaire web.",
    )
    analyseur.add_argument("--email", required=True, help="adresse de connexion du compte")
    analyseur.add_argument("--organisation", help="nom de l'organisation à créer")
    analyseur.add_argument("--nom", help="nom complet de l'utilisateur, facultatif")
    analyseur.add_argument(
        "--mot-de-passe",
        dest="mot_de_passe",
        help="à éviter : reste dans l'historique du terminal. Omettez-le pour une saisie masquée.",
    )
    analyseur.add_argument(
        "--accepter-cadre-legal",
        dest="accepter",
        action="store_true",
        help=(
            "obligatoire : atteste que les recherches menées depuis ce compte le seront "
            "dans un cadre légal et autorisé (voir le README et docs/rgpd.md)"
        ),
    )
    arguments = analyseur.parse_args(argv)

    if not arguments.accepter:
        journal.error(
            "L'option --accepter-cadre-legal est obligatoire. Cet outil traite des "
            "données personnelles de tiers : le consentement au cadre d'utilisation "
            "est tracé pour chaque compte, comme dans l'interface web."
        )
        return 2

    try:
        mot_de_passe = arguments.mot_de_passe or _demander_mot_de_passe()
        _, nom_organisation = creer_compte(
            email=arguments.email,
            mot_de_passe=mot_de_passe,
            nom_organisation=arguments.organisation,
            nom_complet=arguments.nom,
        )
    except CreationImpossible as exc:
        journal.error("%s", exc)
        return 1

    journal.info(
        "Compte créé : %s, administrateur de « %s ». Connexion sur http://localhost:8080",
        arguments.email.strip().lower(),
        nom_organisation,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
