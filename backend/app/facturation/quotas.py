"""Compteurs d'usage et vérification des quotas.

Point clé : la consommation est **atomique**. Un client ne doit pas pouvoir dépasser
son quota en lançant dix recherches simultanées — ce qui arriverait avec un simple
« je lis le compteur, je compare, puis j'incrémente ».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.db.base import nouvel_id
from app.modeles.facturation import CompteurUsage, Plan

# Correspondance : nom du quota -> (colonne du compteur, colonne du plan)
QUOTAS = {
    "recherches": ("compteur_recherches", "quota_recherches_mois"),
    "enrichissements": ("compteur_enrichissements", "quota_enrichissements_mois"),
    "pivots": ("compteur_pivots", "quota_recherches_mois"),   # un pivot consomme le quota de recherches
    "exports": ("compteur_exports", None),                    # non limité pour l'instant
}


class QuotaDepasse(Exception):
    """Le quota mensuel de l'organisation est atteint."""

    def __init__(self, nom_quota: str, limite: int, consomme: int):
        self.nom_quota = nom_quota
        self.limite = limite
        self.consomme = consomme
        super().__init__(
            f"Quota « {nom_quota} » atteint : {consomme}/{limite} pour ce mois. "
            "Passez à un palier supérieur pour continuer."
        )


@dataclass
class EtatQuota:
    nom: str
    consomme: int
    limite: int | None   # None = illimité

    @property
    def restant(self) -> int | None:
        if self.limite is None:
            return None
        return max(0, self.limite - self.consomme)

    @property
    def pourcentage(self) -> float:
        if not self.limite:
            return 0.0
        return min(100.0, round(self.consomme * 100 / self.limite, 1))


def periode_courante(reference: datetime | None = None) -> str:
    """Période de facturation au format « AAAA-MM » (mois calendaire, en UTC)."""
    ref = reference or datetime.now(timezone.utc)
    return f"{ref.year:04d}-{ref.month:02d}"


def _assurer_ligne_compteur(session: Session, organisation_id: str, periode: str) -> None:
    """Crée la ligne de compteur du mois si elle n'existe pas encore.

    Une contrainte d'unicité protège des créations concurrentes : en cas de collision,
    on ignore l'erreur car l'autre transaction a créé la ligne recherchée.
    """
    existe = session.scalar(
        select(CompteurUsage.id).where(
            CompteurUsage.organisation_id == organisation_id,
            CompteurUsage.periode == periode,
        )
    )
    if existe:
        return

    try:
        with session.begin_nested():
            session.execute(
                insert(CompteurUsage).values(
                    id=nouvel_id(),
                    organisation_id=organisation_id,
                    periode=periode,
                    compteur_recherches=0,
                    compteur_enrichissements=0,
                    compteur_pivots=0,
                    compteur_exports=0,
                    detail={},
                )
            )
    except Exception:
        # Ligne créée entre-temps par une transaction concurrente : c'est le résultat voulu.
        pass


def obtenir_compteur(session: Session, organisation_id: str, periode: str | None = None) -> CompteurUsage:
    periode = periode or periode_courante()
    _assurer_ligne_compteur(session, organisation_id, periode)
    compteur = session.scalar(
        select(CompteurUsage).where(
            CompteurUsage.organisation_id == organisation_id,
            CompteurUsage.periode == periode,
        )
    )
    assert compteur is not None  # garanti par _assurer_ligne_compteur
    return compteur


def limite_du_plan(plan: Plan, nom_quota: str) -> int | None:
    if nom_quota not in QUOTAS:
        raise ValueError(f"Quota inconnu : {nom_quota}")
    _, champ_plan = QUOTAS[nom_quota]
    if champ_plan is None:
        return None
    return getattr(plan, champ_plan)


def etat_quotas(session: Session, organisation_id: str, plan: Plan) -> dict[str, EtatQuota]:
    """Vue synthétique de la consommation du mois, pour la page « Abonnement »."""
    compteur = obtenir_compteur(session, organisation_id)
    resultat: dict[str, EtatQuota] = {}
    for nom, (champ_compteur, _) in QUOTAS.items():
        resultat[nom] = EtatQuota(
            nom=nom,
            consomme=getattr(compteur, champ_compteur),
            limite=limite_du_plan(plan, nom),
        )
    return resultat


def verifier_quota(session: Session, organisation_id: str, plan: Plan, nom_quota: str, cout: int = 1) -> None:
    """Vérifie sans consommer. Lève QuotaDepasse si la limite serait franchie.

    À utiliser pour afficher un message clair avant de lancer un traitement ; la
    consommation réelle passe obligatoirement par `consommer_quota`.
    """
    limite = limite_du_plan(plan, nom_quota)
    if limite is None:
        return
    compteur = obtenir_compteur(session, organisation_id)
    champ_compteur, _ = QUOTAS[nom_quota]
    consomme = getattr(compteur, champ_compteur)
    if consomme + cout > limite:
        raise QuotaDepasse(nom_quota, limite, consomme)


def consommer_quota(
    session: Session, organisation_id: str, plan: Plan, nom_quota: str, cout: int = 1
) -> int:
    """Incrémente le compteur de façon atomique, en refusant tout dépassement.

    L'incrément et la vérification de la limite tiennent dans une seule instruction
    UPDATE conditionnelle : si aucune ligne n'est modifiée, c'est que le quota est
    atteint. Deux requêtes simultanées ne peuvent donc pas passer toutes les deux.

    Retourne la nouvelle valeur du compteur.
    """
    if nom_quota not in QUOTAS:
        raise ValueError(f"Quota inconnu : {nom_quota}")

    champ_compteur, _ = QUOTAS[nom_quota]
    limite = limite_du_plan(plan, nom_quota)
    periode = periode_courante()
    _assurer_ligne_compteur(session, organisation_id, periode)

    colonne = getattr(CompteurUsage, champ_compteur)
    conditions = [
        CompteurUsage.organisation_id == organisation_id,
        CompteurUsage.periode == periode,
    ]
    if limite is not None:
        conditions.append(colonne <= limite - cout)

    resultat = session.execute(
        update(CompteurUsage).where(*conditions).values({champ_compteur: colonne + cout})
    )

    if resultat.rowcount == 0:
        compteur = obtenir_compteur(session, organisation_id, periode)
        consomme = getattr(compteur, champ_compteur)
        raise QuotaDepasse(nom_quota, limite or 0, consomme)

    session.flush()
    compteur = obtenir_compteur(session, organisation_id, periode)
    session.refresh(compteur)
    return getattr(compteur, champ_compteur)


def rembourser_quota(session: Session, organisation_id: str, nom_quota: str, cout: int = 1) -> None:
    """Rend une unité de quota lorsqu'un traitement échoue avant d'avoir rien produit.

    Sans cela, un client perdrait une recherche à cause d'une panne de notre côté.
    """
    if nom_quota not in QUOTAS:
        return
    champ_compteur, _ = QUOTAS[nom_quota]
    colonne = getattr(CompteurUsage, champ_compteur)
    session.execute(
        update(CompteurUsage)
        .where(
            CompteurUsage.organisation_id == organisation_id,
            CompteurUsage.periode == periode_courante(),
            colonne >= cout,
        )
        .values({champ_compteur: colonne - cout})
    )
