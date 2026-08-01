"""Service d'investigation : la couche qui relie Maigret, la corrélation, les modules,
le pivot et le graphe.

Les tâches Celery n'appellent que ces fonctions ; toute la logique métier vit ici,
ce qui la rend testable sans file de tâches ni serveur web.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse  # noqa: F401 — utilisé par domaine_de()

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import maintenant
from app.facturation.abonnements import plan_actif
from app.facturation.garde import sites_sensibles_autorises
from app.infra.evenements import TypeEvenement, bus
from app.modeles.enums import (
    NiveauConfiance,
    TypeArete,
    TypeDonnee,
    TypeNoeud,
)
from app.modeles.investigation import (
    DonneeExtraite,
    ExecutionRecherche,
    Investigation,
    ProfilIdentite,
    SignalCorrelation,
)
from app.modules.base import ResultatEnrichissement
from app.modules.registre import module_pour_domaine
from app.moteur.correlation.base import ContexteCorrelation, ProfilEvalue
from app.moteur.correlation.scoreur import scorer_tous
from app.moteur.graphe.depot import DepotGraphe
from app.moteur.maigret_runner import ResultatRecherche, ResultatSite
from app.moteur.pivot.detecteur import DetecteurPivot, DonneeCandidate
from app.moteur.sites_sensibles import filtrer_sites_sensibles

journal = logging.getLogger(__name__)


@dataclass
class BilanEnregistrement:
    profils_crees: int = 0
    profils_existants: int = 0
    #: comptes écartés parce que le plan n'ouvre pas les sites sensibles
    profils_filtres: int = 0


# ---------------------------------------------------------------------------
#  Enregistrement des résultats Maigret
# ---------------------------------------------------------------------------


def enregistrer_resultats_maigret(
    session: Session,
    investigation: Investigation,
    execution: ExecutionRecherche,
    resultat: ResultatRecherche,
    profondeur: int = 0,
    profil_origine_id: str | None = None,
) -> BilanEnregistrement:
    """Crée les profils trouvés et les nœuds de graphe correspondants.

    Point de passage **unique** de tout compte découvert, quelle que soit sa source
    (Maigret, user-scanner, chercheur spécialisé). C'est donc ici qu'est appliqué le
    filtrage des sites sensibles : le placer dans chaque runner obligerait à y penser
    à chaque nouveau chercheur.
    """
    bilan = BilanEnregistrement()
    depot = DepotGraphe(session, investigation.id, investigation.organisation_id)

    comptes = resultat.comptes_trouves
    if not sites_sensibles_autorises(plan_actif(session, investigation.organisation_id)):
        comptes, ecartes = filtrer_sites_sensibles(comptes)
        bilan.profils_filtres = ecartes
        if ecartes:
            journal.info(
                "%d compte(s) sur sites sensibles écarté(s) pour l'investigation %s "
                "(plan sans accès aux sites sensibles)",
                ecartes, investigation.id,
            )

    # Nœud racine : le pseudonyme recherché lors de cette exécution
    noeud_pseudo = depot.obtenir_ou_creer_noeud(
        TypeNoeud.PSEUDO if profondeur == 0 else TypeNoeud.PSEUDO_ALT,
        resultat.pseudo,
        profondeur=profondeur,
        meta={"execution_id": execution.id},
    )

    for site in comptes:
        profil, cree = _creer_ou_recuperer_profil(
            session, investigation, execution, site, profondeur, profil_origine_id
        )
        if cree:
            bilan.profils_crees += 1
        else:
            bilan.profils_existants += 1

        noeud_compte = depot.obtenir_ou_creer_noeud(
            TypeNoeud.COMPTE,
            profil.url,
            score=profil.score_confiance,
            profondeur=profondeur,
            profil_id=profil.id,
            meta={"site": profil.site_nom, "pseudo": profil.pseudo_sur_le_site},
        )
        depot.creer_arete(
            noeud_pseudo,
            noeud_compte,
            TypeArete.POSSEDE_COMPTE,
            libelle=f"compte trouvé sur {profil.site_nom}",
        )

        if cree:
            bus().emettre(
                TypeEvenement.PROFIL_TROUVE,
                investigation.id,
                investigation.organisation_id,
                profil_id=profil.id,
                site=profil.site_nom,
                url=profil.url,
                profondeur=profondeur,
            )

    session.flush()
    investigation.nb_profils_trouves = _compter_profils(session, investigation.id)
    return bilan


def _compter_profils(session: Session, investigation_id: str) -> int:
    from sqlalchemy import func

    return int(
        session.scalar(
            select(func.count(ProfilIdentite.id)).where(
                ProfilIdentite.investigation_id == investigation_id
            )
        )
        or 0
    )


def _creer_ou_recuperer_profil(
    session: Session,
    investigation: Investigation,
    execution: ExecutionRecherche,
    site: ResultatSite,
    profondeur: int,
    profil_origine_id: str | None,
) -> tuple[ProfilIdentite, bool]:
    """Un même compte peut être retrouvé par plusieurs chemins de pivot : on ne le
    duplique pas, on conserve seulement le chemin le plus court."""
    existant = session.scalar(
        select(ProfilIdentite).where(
            ProfilIdentite.investigation_id == investigation.id,
            ProfilIdentite.url == site.url,
        )
    )
    if existant is not None:
        if profondeur < existant.profondeur:
            existant.profondeur = profondeur
            existant.decouvert_par_profil_id = profil_origine_id
        return existant, False

    profil = ProfilIdentite(
        investigation_id=investigation.id,
        organisation_id=investigation.organisation_id,
        execution_id=execution.id,
        site_nom=site.site_nom,
        site_domaine=site.site_domaine,
        url=site.url,
        pseudo_sur_le_site=site.pseudo,
        statut_maigret=site.statut.value,
        profondeur=profondeur,
        decouvert_par_profil_id=profil_origine_id,
        donnees_maigret={
            "identifiants": site.identifiants,
            "pseudos_annexes": site.pseudos_annexes,
            "liens_annexes": site.liens_annexes,
            "tags": site.tags,
            "rang_alexa": site.rang_alexa,
            "est_similaire": site.est_similaire,
            "code_http": site.code_http,
            # D'où vient ce compte : Maigret, user-scanner, recherche web, dark web…
            # Sans cette trace, un analyste ne peut pas juger de la fiabilité d'un
            # résultat, et il devenait impossible de mesurer l'apport réel de chaque
            # source. Le marqueur est posé par la source dans `brut["_source"]`.
            "source_decouverte": (site.brut or {}).get("_source", "maigret"),
        },
    )
    session.add(profil)
    session.flush()

    # Maigret extrait lui-même certains champs (uid, image, date de création) quand
    # l'extraction est autorisée : autant les exploiter, ils sont déjà payés.
    _importer_donnees_maigret(session, investigation, profil, site)
    return profil, True


# Correspondance entre les clés renvoyées par les extracteurs de Maigret et nos types
CORRESPONDANCE_IDS_MAIGRET = {
    "created_at": TypeDonnee.DATE_CREATION,
    "image": TypeDonnee.AVATAR_URL,
    "name": TypeDonnee.NOM_AFFICHE,
    "fullname": TypeDonnee.NOM_AFFICHE,
    "full_name": TypeDonnee.NOM_AFFICHE,
    "bio": TypeDonnee.BIO,
    "location": TypeDonnee.LOCALISATION,
    "email": TypeDonnee.EMAIL,
    "follower_count": TypeDonnee.NB_ABONNES,
    "gravatar_email_md5_hash": TypeDonnee.EMAIL,
}


def _importer_donnees_maigret(
    session: Session, investigation: Investigation, profil: ProfilIdentite, site: ResultatSite
) -> None:
    for cle, valeur in (site.identifiants or {}).items():
        type_donnee = CORRESPONDANCE_IDS_MAIGRET.get(cle.lower())
        if type_donnee is None or not valeur:
            continue
        _ajouter_donnee(
            session, investigation, profil,
            type_donnee=type_donnee,
            valeur=str(valeur),
            module_source="maigret",
            confiance=0.7,   # extraction générique, moins fiable qu'un module dédié
        )

    for pseudo_annexe in (site.pseudos_annexes or {}):
        _ajouter_donnee(
            session, investigation, profil,
            type_donnee=TypeDonnee.PSEUDO_ALT,
            valeur=str(pseudo_annexe),
            module_source="maigret",
            confiance=0.6,
        )


def _ajouter_donnee(
    session: Session,
    investigation: Investigation,
    profil: ProfilIdentite | None,
    *,
    type_donnee: TypeDonnee,
    valeur: str,
    module_source: str,
    confiance: float = 1.0,
    meta: dict | None = None,
) -> DonneeExtraite | None:
    """Ajoute une donnée extraite, sans doublon.

    `profil` peut être nul : l'information décrit alors la personne recherchée et non
    un compte trouvé (voir `DonneeExtraite.profil_id`). La déduplication se fait dans
    ce cas à l'échelle de l'investigation, puisqu'il n'y a pas de profil qui la porte.
    """
    from app.modules.base import InfoExtraite

    info = InfoExtraite(type=type_donnee, valeur=valeur, confiance=confiance)
    normalisee = info.valeur_normalisee
    if not normalisee:
        return None

    profil_id = profil.id if profil is not None else None
    condition_profil = (
        DonneeExtraite.profil_id == profil_id
        if profil_id is not None
        else DonneeExtraite.profil_id.is_(None)
    )
    existante = session.scalar(
        select(DonneeExtraite).where(
            DonneeExtraite.investigation_id == investigation.id,
            condition_profil,
            DonneeExtraite.type == type_donnee.value,
            DonneeExtraite.valeur_normalisee == normalisee,
        )
    )
    if existante is not None:
        return existante

    donnee = DonneeExtraite(
        profil_id=profil_id,
        investigation_id=investigation.id,
        organisation_id=investigation.organisation_id,
        type=type_donnee.value,
        valeur=valeur[:2000],
        valeur_normalisee=normalisee,
        module_source=module_source,
        confiance_extraction=confiance,
        meta=meta or {},
    )
    session.add(donnee)
    session.flush()
    return donnee


# ---------------------------------------------------------------------------
#  Corrélation
# ---------------------------------------------------------------------------


def construire_contexte(session: Session, investigation: Investigation) -> ContexteCorrelation:
    """Assemble la vue mémoire des profils nécessaire au scoring."""
    profils = session.scalars(
        select(ProfilIdentite).where(ProfilIdentite.investigation_id == investigation.id)
    ).all()

    donnees = session.scalars(
        select(DonneeExtraite).where(DonneeExtraite.investigation_id == investigation.id)
    ).all()

    par_profil: dict[str, dict[str, list[str]]] = {}
    for donnee in donnees:
        # Une donnée issue d'un point de départ n'appartient à aucun compte : elle ne
        # peut donc pas contribuer au score *d'un* profil en particulier.
        if donnee.profil_id is None:
            continue
        par_profil.setdefault(donnee.profil_id, {}).setdefault(donnee.type, []).append(donnee.valeur)

    evalues = [
        ProfilEvalue(
            identifiant=p.id,
            site_nom=p.site_nom,
            site_domaine=p.site_domaine,
            url=p.url,
            pseudo_sur_le_site=p.pseudo_sur_le_site,
            profondeur=p.profondeur,
            est_similaire=bool((p.donnees_maigret or {}).get("est_similaire")),
            tags=list((p.donnees_maigret or {}).get("tags") or []),
            donnees=par_profil.get(p.id, {}),
            verdict_manuel=p.verdict_manuel,
        )
        for p in profils
    ]

    return ContexteCorrelation(
        pseudos_reference=[investigation.pseudo_initial, *(investigation.variantes or [])],
        profils=evalues,
    )


def rescorer_investigation(session: Session, investigation: Investigation) -> int:
    """Recalcule le score de tous les profils et rafraîchit le graphe.

    Toujours global, jamais profil par profil : les règles croisées (avatar identique,
    email partagé, lien réciproque) font dépendre le score d'un profil de tous les
    autres. Rescorer isolément produirait des scores incohérents entre eux.
    """
    contexte = construire_contexte(session, investigation)
    if not contexte.profils:
        return 0

    resultats = scorer_tous(contexte)
    profils = {
        p.id: p
        for p in session.scalars(
            select(ProfilIdentite).where(ProfilIdentite.investigation_id == investigation.id)
        ).all()
    }
    depot = DepotGraphe(session, investigation.id, investigation.organisation_id)
    horodatage = maintenant()
    nb_confirmes = 0

    for resultat in resultats:
        profil = profils.get(resultat.profil_id)
        if profil is None:
            continue

        profil.score_confiance = resultat.score
        profil.niveau = resultat.niveau.value
        if resultat.niveau == NiveauConfiance.ELEVE:
            nb_confirmes += 1

        # Les signaux sont remplacés à chaque recalcul : ils décrivent le score actuel,
        # pas l'historique des scores successifs.
        session.query(SignalCorrelation).filter(SignalCorrelation.profil_id == profil.id).delete()
        for contribution in resultat.contributions:
            session.add(
                SignalCorrelation(
                    profil_id=profil.id,
                    organisation_id=investigation.organisation_id,
                    regle=contribution.regle,
                    score_regle=contribution.score_regle,
                    poids=contribution.poids,
                    contribution_points=contribution.contribution_points,
                    explication=contribution.explication[:500],
                    detail=contribution.detail,
                    calcule_le=horodatage,
                )
            )

        depot.mettre_a_jour_score_profil(profil.id, resultat.score)

    investigation.nb_profils_confirmes = nb_confirmes
    investigation.nb_profils_trouves = len(profils)
    session.flush()
    return len(resultats)


# ---------------------------------------------------------------------------
#  Enrichissement
# ---------------------------------------------------------------------------


@dataclass
class EnrichissementPrepare:
    """Résultat d'un appel de module, en attente d'enregistrement."""

    module_nom: str
    resultat: ResultatEnrichissement | None = None
    erreur: str | None = None

    @property
    def aucun_module(self) -> bool:
        return self.module_nom == ""


AUCUN_MODULE = EnrichissementPrepare(module_nom="")


def executer_module(url_profil: str, pseudo: str, domaine: str) -> EnrichissementPrepare:
    """Interroge le site distant. **Ne prend pas de session en paramètre, à dessein.**

    Un enrichissement dure plusieurs secondes (requêtes réseau, attente du limiteur de
    débit, téléchargement d'avatar). Le faire à l'intérieur d'une transaction ouverte
    immobiliserait une connexion du pool PostgreSQL pendant tout ce temps : avec
    plusieurs organisations enrichissant en parallèle, le pool serait saturé et l'API
    deviendrait indisponible pour tout le monde.

    L'appel réseau est donc effectué ici, hors transaction, et son résultat est
    enregistré ensuite par `enregistrer_enrichissement` dans une transaction courte.
    """
    module = module_pour_domaine(domaine)
    if module is None:
        return AUCUN_MODULE

    try:
        return EnrichissementPrepare(module_nom=module.nom, resultat=module.enrichir(url_profil, pseudo))
    except Exception as exc:  # noqa: BLE001 — un module tiers ne doit pas faire tomber la tâche
        journal.exception("Module « %s » en échec sur %s", module.nom, url_profil)
        return EnrichissementPrepare(
            module_nom=module.nom, erreur=f"Module {module.nom} en erreur : {exc}"[:500]
        )


def enregistrer_enrichissement(
    session: Session,
    investigation: Investigation,
    profil: ProfilIdentite,
    prepare: EnrichissementPrepare,
) -> str | None:
    """Enregistre le résultat d'un module : données extraites, nœuds et arêtes du graphe."""
    if prepare.aucun_module:
        profil.erreur_enrichissement = None
        return None

    if prepare.erreur is not None or prepare.resultat is None:
        profil.erreur_enrichissement = prepare.erreur
        return prepare.erreur

    module_nom = prepare.module_nom
    resultat = prepare.resultat
    profil.module_utilise = module_nom
    profil.enrichi = True
    profil.enrichi_le = maintenant()
    profil.erreur_enrichissement = resultat.erreur[:500] if resultat.erreur else None

    depot = DepotGraphe(session, investigation.id, investigation.organisation_id)
    noeud_compte = depot.obtenir_ou_creer_noeud(
        TypeNoeud.COMPTE, profil.url, score=profil.score_confiance,
        profondeur=profil.profondeur, profil_id=profil.id,
    )

    for info in resultat.informations:
        donnee = _ajouter_donnee(
            session, investigation, profil,
            type_donnee=info.type,
            valeur=info.valeur,
            module_source=module_nom,
            confiance=info.confiance,
            meta=info.meta,
        )
        if donnee is None:
            continue

        type_noeud = _type_noeud_pour(info.type)
        if type_noeud is None:
            continue  # information affichée dans la fiche, mais sans intérêt dans le graphe

        noeud_info = depot.obtenir_ou_creer_noeud(
            type_noeud, info.valeur, profondeur=profil.profondeur + 1,
            meta={"type_donnee": info.type.value, "module": module_nom},
        )
        depot.creer_arete(
            noeud_compte, noeud_info, TypeArete.INFORMATION_EXTRAITE,
            libelle=info.meta.get("source") or f"{info.type.value} extrait de {profil.site_nom}",
            poids=info.confiance,
        )
        bus().emettre(
            TypeEvenement.NOEUD_AJOUTE, investigation.id, investigation.organisation_id,
            noeud_id=noeud_info.id, type=type_noeud.value, libelle=info.valeur[:120],
        )

    session.flush()
    return resultat.erreur


def enrichir_profil(session: Session, investigation: Investigation, profil: ProfilIdentite) -> str | None:
    """Enchaîne appel du module et enregistrement, dans la session fournie.

    Pratique pour les tests et les scripts. **À éviter dans les tâches de fond** :
    l'appel réseau se déroule alors dans la transaction ouverte — voir l'explication
    dans `executer_module`. Les tâches utilisent les deux fonctions séparément.
    """
    prepare = executer_module(profil.url, profil.pseudo_sur_le_site, profil.site_domaine)
    return enregistrer_enrichissement(session, investigation, profil, prepare)


# Seules les informations qui identifient quelque chose deviennent des nœuds.
# Une biographie ou un nombre d'abonnés reste consultable dans la fiche du profil,
# mais encombrerait le graphe sans rien y apporter.
CORRESPONDANCE_NOEUDS = {
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


def _type_noeud_pour(type_donnee: TypeDonnee) -> TypeNoeud | None:
    return CORRESPONDANCE_NOEUDS.get(type_donnee)


def profils_a_enrichir(session: Session, investigation: Investigation, score_minimal: int) -> list[ProfilIdentite]:
    """Profils qui méritent un enrichissement : score suffisant, site couvert, pas déjà fait.

    Filtrer sur le score évite de dépenser des requêtes (et du quota client) sur des
    profils que la corrélation a déjà identifiés comme douteux.
    """
    profils = session.scalars(
        select(ProfilIdentite).where(
            ProfilIdentite.investigation_id == investigation.id,
            ProfilIdentite.enrichi.is_(False),
        )
    ).all()

    retenus = []
    for profil in profils:
        if profil.verdict_manuel == "faux_positif":
            continue
        if profil.score_confiance < score_minimal:
            continue
        if module_pour_domaine(profil.site_domaine) is None:
            continue
        retenus.append(profil)
    return retenus


# ---------------------------------------------------------------------------
#  Pivot
# ---------------------------------------------------------------------------


def collecter_donnees_pivotables(
    session: Session, investigation: Investigation, score_minimal: int
) -> list[DonneeCandidate]:
    """Données extraites susceptibles de servir de pivot, issues des profils fiables."""
    profils = {
        p.id: p
        for p in session.scalars(
            select(ProfilIdentite).where(ProfilIdentite.investigation_id == investigation.id)
        ).all()
    }
    donnees = session.scalars(
        select(DonneeExtraite).where(
            DonneeExtraite.investigation_id == investigation.id,
            DonneeExtraite.pivotee.is_(False),
        )
    ).all()

    candidates: list[DonneeCandidate] = []
    for donnee in donnees:
        # Donnée issue d'un point de départ (profil Gravatar, opérateur d'un numéro) :
        # elle décrit la personne recherchée elle-même. Elle est donc pivotable sans
        # condition de score — il n'y a pas de profil douteux à écarter, et c'est
        # souvent la piste la plus solide de l'investigation, puisqu'elle vient d'une
        # page que la personne a remplie elle-même.
        if donnee.profil_id is None:
            candidates.append(
                DonneeCandidate(
                    identifiant=donnee.id,
                    type=donnee.type,
                    valeur=donnee.valeur,
                    valeur_normalisee=donnee.valeur_normalisee,
                    profil_id=None,
                    profil_site="point de départ",
                    confiance=donnee.confiance_extraction,
                    module_source=donnee.module_source,
                )
            )
            continue

        profil = profils.get(donnee.profil_id)
        if profil is None or profil.verdict_manuel == "faux_positif":
            continue
        # Un pivot issu d'un profil douteux propagerait l'erreur à toute la suite
        # de l'investigation : on ne pivote que depuis des profils crédibles.
        if profil.score_confiance < score_minimal:
            continue
        candidates.append(
            DonneeCandidate(
                identifiant=donnee.id,
                type=donnee.type,
                valeur=donnee.valeur,
                valeur_normalisee=donnee.valeur_normalisee,
                profil_id=profil.id,
                profil_site=profil.site_nom,
                confiance=donnee.confiance_extraction,
                module_source=donnee.module_source,
            )
        )
    return candidates


def marquer_donnees_pivotees(session: Session, identifiants: list[str]) -> None:
    if not identifiants:
        return
    for donnee in session.scalars(
        select(DonneeExtraite).where(DonneeExtraite.id.in_(identifiants))
    ):
        donnee.pivotee = True


def detecteur_pour(session: Session, investigation: Investigation, deja_explorees: set[str]) -> DetecteurPivot:
    del session, investigation  # signature homogène avec les autres fabriques du service
    return DetecteurPivot(valeurs_deja_explorees=deja_explorees)


def relier_pivot_dans_graphe(
    session: Session,
    investigation: Investigation,
    profil_source_id: str | None,
    valeur_pivot: str,
    type_noeud: TypeNoeud,
    libelle_relation: str,
) -> None:
    """Trace dans le graphe le lien entre l'origine d'un pivot et sa cible."""
    depot = DepotGraphe(session, investigation.id, investigation.organisation_id)
    noeud_cible = depot.obtenir_ou_creer_noeud(type_noeud, valeur_pivot)

    if profil_source_id:
        profil = session.get(ProfilIdentite, profil_source_id)
        if profil is not None:
            noeud_source = depot.obtenir_ou_creer_noeud(
                TypeNoeud.COMPTE, profil.url, profil_id=profil.id, score=profil.score_confiance
            )
            depot.creer_arete(
                noeud_source, noeud_cible, TypeArete.PIVOT_VERS, libelle=libelle_relation
            )


def domaine_de(url: str) -> str:
    return urlparse(url if "://" in url else f"https://{url}").netloc.lower()
