"""Règle : un profil renvoie explicitement vers un autre profil de l'investigation.

C'est le signal le plus fort du moteur : quand un compte GitHub affiche le lien de son
compte Mastodon, l'appartenance des deux comptes à la même personne n'est plus une
inférence statistique mais une déclaration de l'intéressé.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.modeles.enums import TypeDonnee
from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    RegleCorrelation,
    ResultatRegle,
    normaliser_pseudo,
)


def _cle_url(url: str) -> str:
    """Forme comparable d'une URL : domaine + chemin, sans protocole, www ni barre finale."""
    try:
        analyse = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return url.strip().lower()
    domaine = (analyse.netloc or "").lower().removeprefix("www.")
    chemin = (analyse.path or "").rstrip("/").lower()
    return f"{domaine}{chemin}"


class RegleLiensCroises(RegleCorrelation):
    nom = "liens_croises"
    libelle = "Lien explicite entre profils"

    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        liens_profil = {_cle_url(lien) for lien in profil.valeurs(TypeDonnee.LIEN_EXTERNE)}
        autres = [p for p in contexte.autres_profils(profil) if p.verdict_manuel != "faux_positif"]

        preuves: list[dict[str, str]] = []

        for autre in autres:
            cle_autre = _cle_url(autre.url)
            if not cle_autre:
                continue

            # Sens 1 : ce profil pointe vers l'autre
            if any(cle_autre and (cle_autre in lien or lien in cle_autre) for lien in liens_profil if lien):
                preuves.append({"sens": "sortant", "site": autre.site_nom, "url": autre.url})
                continue

            # Sens 2 : l'autre pointe vers ce profil (relation réciproque, tout aussi probante)
            cle_profil = _cle_url(profil.url)
            liens_autre = {_cle_url(lien) for lien in autre.valeurs(TypeDonnee.LIEN_EXTERNE)}
            if cle_profil and any(
                cle_profil in lien or lien in cle_profil for lien in liens_autre if lien
            ):
                preuves.append({"sens": "entrant", "site": autre.site_nom, "url": autre.url})

        if not preuves:
            # Le profil mentionne-t-il au moins un pseudonyme de référence dans ses liens ?
            references = contexte.pseudos_reference_normalises
            for lien in liens_profil:
                if any(ref and ref in normaliser_pseudo(lien) for ref in references):
                    return ResultatRegle(
                        score=0.6,
                        explication="Un lien externe du profil contient le pseudonyme recherché",
                        detail={"lien": lien},
                    )
            return None

        sites = ", ".join(sorted({p["site"] for p in preuves}))
        return ResultatRegle(
            score=1.0,
            explication=f"Lien explicite avec le(s) profil(s) {sites}",
            detail={"preuves": preuves},
        )
