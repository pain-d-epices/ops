"""Règle : deux profils exposent la même adresse électronique.

Signal très fort, au même niveau qu'un lien explicite. Les empreintes Gravatar
(md5 de l'email) sont traitées comme des emails : deux profils partageant la même
empreinte partagent la même adresse, sans qu'on ait besoin de la connaître.
"""

from __future__ import annotations

from app.modeles.enums import TypeDonnee
from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    RegleCorrelation,
    ResultatRegle,
)

# Adresses techniques qui n'identifient personne : les ignorer évite de relier
# à tort tous les comptes GitHub qui masquent leur adresse.
EMAILS_GENERIQUES = {
    "noreply@github.com",
    "no-reply@github.com",
    "support@github.com",
    "privacy@github.com",
}


def _emails_identifiants(profil: ProfilEvalue) -> set[str]:
    valeurs = {v.strip().lower() for v in profil.valeurs(TypeDonnee.EMAIL) if v and v.strip()}
    return {
        email
        for email in valeurs
        if email not in EMAILS_GENERIQUES and not email.endswith(".noreply.github.com")
    }


class RegleEmailPartage(RegleCorrelation):
    nom = "email_partage"
    libelle = "Adresse électronique partagée"

    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        emails = _emails_identifiants(profil)
        if not emails:
            return None

        correspondances: list[dict[str, str]] = []
        for autre in contexte.autres_profils(profil):
            if autre.verdict_manuel == "faux_positif":
                continue
            communs = emails & _emails_identifiants(autre)
            for email in communs:
                correspondances.append({"site": autre.site_nom, "email": email})

        if not correspondances:
            return None

        sites = ", ".join(sorted({c["site"] for c in correspondances}))
        return ResultatRegle(
            score=1.0,
            explication=f"Même adresse électronique que le(s) profil(s) {sites}",
            detail={"correspondances": correspondances},
        )
