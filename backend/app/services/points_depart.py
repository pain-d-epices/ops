"""Traitement des points de départ d'une investigation.

Fait le lien entre les chercheurs et le reste du moteur. Le principe qui rend cette
brique simple : **tous les chercheurs produisent le même type de résultat**, donc
toute la chaîne existante (enregistrement des profils, corrélation, graphe, détection
de rebonds) s'applique sans modification, quel que soit le type du point de départ.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.base import maintenant
from app.modeles.enums import TypeDonnee, TypeNoeud, TypePointDepart
from app.modeles.facturation import Plan
from app.modeles.investigation import (
    ExecutionRecherche,
    Investigation,
    PointDepart,
)
from app.moteur.chercheurs.base import ResultatChercheur
from app.moteur.chercheurs.registre import chercheur_pour
from app.moteur.graphe.depot import DepotGraphe
from app.moteur.maigret_runner import ResultatRecherche
from app.services.investigation import _ajouter_donnee, enregistrer_resultats_maigret

journal = logging.getLogger(__name__)

# Type de nœud représentant le point de départ lui-même dans le graphe
NOEUD_PAR_TYPE_DEPART = {
    TypePointDepart.PSEUDO.value: TypeNoeud.PSEUDO,
    TypePointDepart.COMPTE.value: TypeNoeud.COMPTE,
    TypePointDepart.EMAIL.value: TypeNoeud.EMAIL,
    TypePointDepart.TELEPHONE.value: TypeNoeud.TELEPHONE,
    TypePointDepart.NOM.value: TypeNoeud.NOM,
    TypePointDepart.ADRESSE.value: TypeNoeud.LOCALISATION,
}


@dataclass
class BilanPointDepart:
    comptes_trouves: int = 0
    informations: int = 0
    erreur: str | None = None


def chercheur_autorise(type_point_depart: str, plan: Plan) -> tuple[bool, str | None]:
    """Le plan permet-il ce type de recherche ?

    Renvoie (autorisé, motif de refus). Le rapprochement se fait par le champ
    `fonctionnalite_requise` du chercheur : ajouter un chercheur ne demande donc
    aucune modification de la logique de facturation.
    """
    chercheur = chercheur_pour(type_point_depart)
    if chercheur is None:
        return False, f"Aucun outil de recherche disponible pour le type « {type_point_depart} »."
    if chercheur.fonctionnalite_requise and not plan.possede(chercheur.fonctionnalite_requise):
        return False, (
            f"La recherche par « {chercheur.libelle.lower()} » n'est pas incluse "
            f"dans le plan {plan.nom_affiche}."
        )
    return True, None


def marquer_point_en_cours(session: Session, point: PointDepart, plan: Plan) -> str | None:
    """Vérifie le droit, marque le point « en cours ». Renvoie un motif de refus, ou None.

    Transaction **courte** : à appeler avant l'appel réseau, jamais autour.
    """
    autorise, motif = chercheur_autorise(point.type, plan)
    if not autorise:
        point.statut = "non_autorise"
        point.message_erreur = motif
        point.traite_le = maintenant()
        return motif or "Type de recherche non autorisé."

    point.statut = "en_cours"
    session.flush()
    return None


def executer_chercheur(
    type_point_depart: str, valeur: str, options: dict | None = None, rappel=None
) -> ResultatChercheur | None:
    """Interroge les sources distantes. **Ne prend pas de session en paramètre, à dessein.**

    Même raison que pour `executer_module` : une recherche par adresse électronique
    interroge jusqu'à 144 sites et peut durer plusieurs minutes. La conduire à
    l'intérieur d'une transaction ouverte immobiliserait une connexion PostgreSQL
    pendant tout ce temps ; avec quelques investigations simultanées, le pool serait
    saturé et l'API deviendrait indisponible pour **tous** les clients.

    Mesure du 01/08/2026 : une recherche par adresse électronique tenait une connexion
    ouverte pendant 733 secondes. L'appel réseau est donc effectué ici, hors
    transaction, et son résultat enregistré ensuite par `enregistrer_point_depart`.
    """
    chercheur = chercheur_pour(type_point_depart)
    if chercheur is None:
        return None
    try:
        return chercheur.chercher(valeur, options or {}, rappel=rappel)
    except Exception as exc:  # noqa: BLE001 — un chercheur défaillant ne doit pas faire tomber la tâche
        journal.exception("Chercheur « %s » en échec sur %s", type_point_depart, valeur[:60])
        resultat = ResultatChercheur(entree=valeur, type_entree=type_point_depart)
        resultat.erreur = f"Recherche « {type_point_depart} » en erreur : {exc}"[:500]
        return resultat


def enregistrer_point_depart(
    session: Session,
    investigation: Investigation,
    point: PointDepart,
    resultat: ResultatChercheur | None,
) -> BilanPointDepart:
    """Enregistre le résultat d'un chercheur. Transaction **courte**."""
    bilan = BilanPointDepart()

    if resultat is None:
        motif = f"Aucun outil de recherche disponible pour le type « {point.type} »."
        point.statut = "erreur"
        point.message_erreur = motif
        point.traite_le = maintenant()
        bilan.erreur = motif
        return bilan

    if resultat.erreur and not resultat.comptes:
        point.statut = "erreur"
        point.message_erreur = resultat.erreur[:500]
        point.traite_le = maintenant()
        bilan.erreur = resultat.erreur
        return bilan

    _enregistrer(session, investigation, point, resultat)

    point.statut = "termine"
    point.traite_le = maintenant()
    point.nb_comptes_trouves = len(resultat.comptes)
    point.detail = {**(point.detail or {}), **resultat.detail}
    bilan.comptes_trouves = len(resultat.comptes)
    bilan.informations = len(resultat.informations)
    return bilan


def traiter_point_depart(
    session: Session,
    investigation: Investigation,
    point: PointDepart,
    plan: Plan,
    options: dict | None = None,
    rappel=None,
) -> BilanPointDepart:
    """Enchaîne vérification, appel réseau et enregistrement dans la session fournie.

    Pratique pour les tests et les scripts. **À éviter dans les tâches de fond** :
    l'appel réseau se déroule alors dans la transaction ouverte — voir l'explication
    dans `executer_chercheur`. Les tâches utilisent les trois fonctions séparément.
    """
    motif = marquer_point_en_cours(session, point, plan)
    if motif is not None:
        return BilanPointDepart(erreur=motif)

    resultat = executer_chercheur(point.type, point.valeur, options, rappel)
    return enregistrer_point_depart(session, investigation, point, resultat)


def _enregistrer(
    session: Session,
    investigation: Investigation,
    point: PointDepart,
    resultat: ResultatChercheur,
) -> None:
    """Enregistre comptes et informations, en réutilisant le chemin habituel."""
    execution = ExecutionRecherche(
        investigation_id=investigation.id,
        organisation_id=investigation.organisation_id,
        pseudo_recherche=point.valeur[:200],
        profondeur=0,
        statut="terminee",
        nb_sites_scannes=resultat.nb_sources_consultees,
        nb_sites_total=resultat.nb_sources_consultees,
        duree_secondes=resultat.duree_secondes,
        message_erreur=resultat.erreur,
    )
    session.add(execution)
    session.flush()

    # Les comptes passent par le chemin d'enregistrement habituel : ils bénéficient
    # ainsi de la déduplication, du graphe et de la corrélation sans code spécifique.
    if resultat.comptes:
        enregistrer_resultats_maigret(
            session,
            investigation,
            execution,
            ResultatRecherche(
                pseudo=point.valeur[:200],
                sites=resultat.comptes,
                nb_sites_total=resultat.nb_sources_consultees,
                nb_sites_scannes=resultat.nb_sources_consultees,
                duree_secondes=resultat.duree_secondes,
            ),
            profondeur=0,
        )

    if not resultat.informations:
        return

    # Les informations ne se rattachent à aucun compte : elles décrivent le point de
    # départ lui-même (le nom derrière une adresse Gravatar, l'opérateur d'un numéro).
    # On les rattache donc au nœud du point de départ, et non à un profil.
    depot = DepotGraphe(session, investigation.id, investigation.organisation_id)
    type_noeud = NOEUD_PAR_TYPE_DEPART.get(point.type, TypeNoeud.PSEUDO)
    noeud_depart = depot.obtenir_ou_creer_noeud(
        type_noeud,
        point.valeur,
        profondeur=0,
        meta={"point_depart": True, "type_point_depart": point.type},
    )

    # Ces informations décrivent la personne recherchée, pas un compte : elles sont
    # donc enregistrées **sans profil porteur** (`profil_id` nul).
    #
    # Auparavant, elles n'étaient conservées que si un compte avait déjà été trouvé,
    # et purement perdues sinon — c'est-à-dire dans le cas où elles comptaient le
    # plus. Mesure du 01/08/2026 : une recherche par adresse électronique remontait un
    # profil Gravatar complet dont rien n'était enregistré, faute de compte auquel le
    # rattacher. Ni affichage, ni corrélation, ni rebond possible.
    for info in resultat.informations:
        _ajouter_donnee(
            session,
            investigation,
            None,
            type_donnee=info.type,
            valeur=info.valeur,
            module_source=f"chercheur:{point.type}",
            confiance=info.confiance,
            meta={**info.meta, "issu_du_point_de_depart": point.id},
        )

        type_noeud_info = _type_noeud_information(info.type)
        if type_noeud_info is None:
            continue
        noeud_info = depot.obtenir_ou_creer_noeud(
            type_noeud_info,
            info.valeur,
            profondeur=1,
            meta={"type_donnee": info.type.value, "source": info.meta.get("source", "")},
        )
        depot.creer_arete(
            noeud_depart,
            noeud_info,
            "information_extraite",
            libelle=info.meta.get("source") or f"{info.type.value} lié au point de départ",
            poids=info.confiance,
        )

    session.flush()


CORRESPONDANCE_NOEUDS_INFORMATION = {
    TypeDonnee.EMAIL: TypeNoeud.EMAIL,
    TypeDonnee.PSEUDO_ALT: TypeNoeud.PSEUDO_ALT,
    TypeDonnee.NOM_REEL: TypeNoeud.NOM,
    TypeDonnee.NOM_AFFICHE: TypeNoeud.NOM,
    TypeDonnee.LOCALISATION: TypeNoeud.LOCALISATION,
    TypeDonnee.LIEN_EXTERNE: TypeNoeud.LIEN,
    TypeDonnee.TELEPHONE: TypeNoeud.TELEPHONE,
    TypeDonnee.ENTREPRISE: TypeNoeud.ENTREPRISE,
    TypeDonnee.AVATAR_PHASH: TypeNoeud.AVATAR,
}


def _type_noeud_information(type_donnee: TypeDonnee) -> TypeNoeud | None:
    return CORRESPONDANCE_NOEUDS_INFORMATION.get(type_donnee)
