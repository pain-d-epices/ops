"""Règle : avatars perceptuellement identiques entre deux profils.

Le hash perceptuel (pHash) reste stable après redimensionnement ou recompression :
deux profils affichant la même photo produisent des empreintes très proches, même si
les fichiers diffèrent. C'est l'un des signaux les plus fiables de l'outil — une
personne réutilise très souvent le même avatar d'un site à l'autre.
"""

from __future__ import annotations

from app.modeles.enums import TypeDonnee
from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    RegleCorrelation,
    ResultatRegle,
)


def distance_hamming(hash_a: str, hash_b: str) -> int | None:
    """Nombre de bits différents entre deux empreintes hexadécimales.

    Renvoie None si les empreintes ne sont pas comparables (longueurs différentes
    ou format invalide).
    """
    hash_a, hash_b = hash_a.strip().lower(), hash_b.strip().lower()
    if not hash_a or not hash_b or len(hash_a) != len(hash_b):
        return None
    try:
        return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")
    except ValueError:
        return None


class RegleAvatarPhash(RegleCorrelation):
    nom = "avatar_phash"
    libelle = "Avatar identique"

    def evaluer(self, profil: ProfilEvalue, contexte: ContexteCorrelation) -> ResultatRegle | None:
        empreintes = profil.valeurs(TypeDonnee.AVATAR_PHASH)
        if not empreintes:
            return None

        distance_max = int(self.config.get("distance_max", 8))
        correspondances: list[dict[str, object]] = []
        meilleure_distance = None

        for autre in contexte.autres_profils(profil):
            if autre.verdict_manuel == "faux_positif":
                continue
            for empreinte in empreintes:
                for empreinte_autre in autre.valeurs(TypeDonnee.AVATAR_PHASH):
                    distance = distance_hamming(empreinte, empreinte_autre)
                    if distance is None or distance > distance_max:
                        continue
                    correspondances.append({"site": autre.site_nom, "distance": distance})
                    if meilleure_distance is None or distance < meilleure_distance:
                        meilleure_distance = distance
                    break

        if not correspondances:
            # Un avatar différent ne prouve rien : beaucoup de gens changent de photo
            # d'un site à l'autre. La règle s'abstient plutôt que de pénaliser.
            return None

        # Score dégressif avec la distance : identique (0) vaut mieux que « très proche ».
        score = 1.0 if meilleure_distance == 0 else max(0.6, 1.0 - meilleure_distance / (distance_max * 2))
        sites = ", ".join(sorted({str(c["site"]) for c in correspondances}))
        qualificatif = "identique" if meilleure_distance == 0 else "quasi identique"
        return ResultatRegle(
            score=round(score, 3),
            explication=f"Avatar {qualificatif} à celui trouvé sur {sites}",
            detail={"correspondances": correspondances, "distance_min": meilleure_distance},
        )
