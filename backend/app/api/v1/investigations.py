"""Endpoints d'investigation : création, suivi, consultation, suppression, export."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select

from app.config import config_metier
from app.db.base import maintenant
from app.facturation.garde import (
    mode_pivot_effectif,
    profondeur_pivot_autorisee,
    sites_analysables,
)
from app.facturation.plans import EXPORT_CSV, EXPORT_PDF
from app.facturation.quotas import QuotaDepasse, consommer_quota, rembourser_quota
from app.infra.limiteur_entrant import exiger_debit
from app.modeles.enums import (
    ActionJournal,
    RoleMembre,
    StatutInvestigation,
    StatutPropositionPivot,
    TypePointDepart,
)
from app.modeles.graphe import AreteGraphe, NoeudGraphe
from app.modeles.investigation import (
    DonneeExtraite,
    Investigation,
    PointDepart,
    ProfilIdentite,
    PropositionPivot,
)
from app.modeles.utilisateur import Utilisateur
from app.schemas.investigation import (
    DemandeInvestigation,
    InvestigationDetaillee,
    InvestigationResumee,
    PointDepartSortie,
    TypeRechercheSortie,
    TypesRechercheSortie,
)
from app.securite.dependances import ContexteRequete, contexte_courant, exiger_cgu, exiger_role
from app.services.journal import journaliser

journal = logging.getLogger(__name__)
routeur = APIRouter(prefix="/investigations", tags=["Investigations"])


def _recuperer(ctx: ContexteRequete, investigation_id: str) -> Investigation:
    """Charge une investigation en garantissant qu'elle appartient à l'organisation.

    Le filtre sur `organisation_id` est le point de contrôle de l'isolation entre
    clients : il ne doit jamais être omis, même quand l'identifiant semble suffire.
    """
    investigation = ctx.session.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id,
            Investigation.organisation_id == ctx.organisation_id,
        )
    )
    if investigation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation introuvable.")
    return investigation


def _resume(investigation: Investigation) -> InvestigationResumee:
    return InvestigationResumee(
        id=investigation.id,
        titre=investigation.titre,
        pseudo_initial=investigation.pseudo_initial,
        statut=investigation.statut,
        progression=investigation.progression,
        etape_courante=investigation.etape_courante,
        nb_profils_trouves=investigation.nb_profils_trouves,
        nb_profils_confirmes=investigation.nb_profils_confirmes,
        nb_recherches_effectuees=investigation.nb_recherches_effectuees,
        cree_le=investigation.created_at,
        terminee_le=investigation.terminee_le,
        supprimer_apres=investigation.supprimer_apres,
    )


def _enregistrer_points_depart(
    ctx: ContexteRequete, investigation: Investigation, demande: DemandeInvestigation
) -> None:
    """Enregistre les points de départ, en vérifiant droits et limites du plan.

    L'élément principal (`demande.pseudo`) n'est plus obligatoirement un pseudonyme :
    son type est déclaré explicitement par l'interface ou, à défaut, deviné, puis
    validé par le même chercheur que les éléments supplémentaires — un type non
    couvert par le plan est refusé explicitement, plutôt qu'ignoré en silence.
    """
    from app.moteur.chercheurs.base import detecter_type
    from app.moteur.chercheurs.registre import chercheur_pour
    from app.moteur.correlation.base import normaliser
    from app.services.points_depart import chercheur_autorise

    session = ctx.session
    deja_vus: set[str] = set()

    valeur_principale = demande.pseudo.strip()
    type_principal = demande.type_principal or detecter_type(valeur_principale)
    chercheur_principal = chercheur_pour(type_principal)
    if chercheur_principal is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Le type « {type_principal} » n'est pas encore pris en charge "
            f"(valeur : {valeur_principale[:60]}).",
        )

    autorise, motif = chercheur_autorise(type_principal, ctx.plan)
    if not autorise:
        raise HTTPException(status.HTTP_403_FORBIDDEN, motif or "Type de recherche non autorisé.")

    valeur_principale_valide = chercheur_principal.valider(valeur_principale)
    if valeur_principale_valide is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"« {valeur_principale[:60]} » n'est pas un(e) "
            f"{chercheur_principal.libelle.lower()} valide.",
        )

    session.add(
        PointDepart(
            investigation_id=investigation.id,
            organisation_id=ctx.organisation_id,
            type=type_principal,
            valeur=valeur_principale_valide[:500],
            valeur_normalisee=normaliser(valeur_principale_valide)[:500] or valeur_principale_valide[:500],
        )
    )
    deja_vus.add(f"{type_principal}:{valeur_principale_valide.lower()}")

    if not demande.points_depart:
        session.flush()
        return

    # `max_points_depart` compte l'élément principal ; 0 signifie illimité.
    maximum = ctx.plan.max_points_depart
    if maximum and len(demande.points_depart) + 1 > maximum:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Le plan {ctx.plan.nom_affiche} accepte {maximum} élément(s) de départ "
            f"par investigation, élément principal compris. Passez à un palier "
            f"supérieur pour en combiner davantage.",
        )

    for entree in demande.points_depart:
        valeur = entree.valeur.strip()
        if not valeur:
            continue

        type_point = entree.type or detecter_type(valeur)
        chercheur = chercheur_pour(type_point)
        if chercheur is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Le type « {type_point} » n'est pas encore pris en charge "
                f"(valeur : {valeur[:60]}).",
            )

        autorise, motif = chercheur_autorise(type_point, ctx.plan)
        if not autorise:
            raise HTTPException(status.HTTP_403_FORBIDDEN, motif or "Type de recherche non autorisé.")

        valeur_valide = chercheur.valider(valeur)
        if valeur_valide is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"« {valeur[:60]} » n'est pas un(e) {chercheur.libelle.lower()} valide.",
            )

        cle = f"{type_point}:{valeur_valide.lower()}"
        if cle in deja_vus:
            continue
        deja_vus.add(cle)

        session.add(
            PointDepart(
                investigation_id=investigation.id,
                organisation_id=ctx.organisation_id,
                type=type_point,
                valeur=valeur_valide[:500],
                valeur_normalisee=normaliser(valeur_valide)[:500] or valeur_valide[:500],
            )
        )

    session.flush()


@routeur.post(
    "",
    response_model=InvestigationDetaillee,
    status_code=status.HTTP_201_CREATED,
    # Les quotas bornent le volume *mensuel* ; cette limite borne le *rythme*. Sans
    # elle, un client peut épuiser son quota en quelques secondes et saturer la file
    # de tâches au détriment des autres organisations.
    dependencies=[Depends(exiger_debit("investigation"))],
)
def creer_investigation(
    demande: DemandeInvestigation,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_cgu),
) -> InvestigationDetaillee:
    """Crée une investigation et met la recherche en file d'attente."""
    if not ctx.a_le_role(RoleMembre.ANALYSTE.value):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Votre rôle ne permet pas de lancer une recherche.")

    # Limite du nombre d'investigations en cours, pour éviter qu'un client ne sature
    # les workers partagés avec des dizaines de recherches simultanées.
    actives = ctx.session.scalar(
        select(func.count(Investigation.id)).where(
            Investigation.organisation_id == ctx.organisation_id,
            Investigation.statut.in_(
                [StatutInvestigation.EN_ATTENTE.value, StatutInvestigation.EN_COURS.value]
            ),
        )
    )
    if (actives or 0) >= ctx.plan.quota_investigations_actives:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Vous avez déjà {actives} investigation(s) en cours, "
            f"soit le maximum du plan {ctx.plan.nom_affiche}.",
        )

    try:
        consommer_quota(ctx.session, ctx.organisation_id, ctx.plan, "recherches")
    except QuotaDepasse as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc

    # Les options envoyées par le client sont systématiquement bornées côté serveur.
    profondeur = profondeur_pivot_autorisee(ctx.plan, ctx.organisation, demande.profondeur_pivot)
    mode = mode_pivot_effectif(
        ctx.plan, ctx.organisation, demande.mode_pivot.value if demande.mode_pivot else None
    )
    top_sites = sites_analysables(ctx.plan, demande.top_sites)

    jours_retention = ctx.organisation.retention_jours or int(
        config_metier().obtenir("retention.jours_defaut", 90)
    )

    investigation = Investigation(
        organisation_id=ctx.organisation_id,
        cree_par=ctx.utilisateur.id,
        titre=demande.titre,
        pseudo_initial=demande.pseudo.strip(),
        variantes=[v.strip() for v in demande.variantes if v.strip()],
        options={
            "profondeur": profondeur,
            "mode_pivot": mode,
            "top_sites": top_sites,
            "sites_exclus": demande.sites_exclus,
            "plan_au_lancement": ctx.plan.code,
        },
        statut=StatutInvestigation.EN_ATTENTE.value,
        supprimer_apres=maintenant() + timedelta(days=jours_retention),
    )
    ctx.session.add(investigation)
    ctx.session.flush()

    _enregistrer_points_depart(ctx, investigation, demande)

    journaliser(
        ctx.session, ActionJournal.INVESTIGATION_CREEE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=investigation.pseudo_initial,
        investigation_id=investigation.id, requete=requete,
        detail={"profondeur": profondeur, "mode_pivot": mode, "plan": ctx.plan.code},
    )
    ctx.session.commit()

    try:
        from app.taches.recherche import lancer_investigation

        lancer_investigation.apply_async(
            kwargs={"investigation_id": investigation.id}, queue="recherche"
        )
    except Exception as exc:  # noqa: BLE001
        # File de tâches injoignable : rendre le quota consommé plutôt que de le
        # facturer au client pour une recherche qui n'a jamais démarré.
        journal.exception("Mise en file impossible pour l'investigation %s", investigation.id)
        investigation.statut = StatutInvestigation.ERREUR.value
        investigation.message_erreur = "Le service de traitement est momentanément indisponible."
        rembourser_quota(ctx.session, ctx.organisation_id, "recherches")
        ctx.session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Le service de traitement est momentanément indisponible. Réessayez dans un instant.",
        ) from exc

    return _detail(ctx, investigation)


@routeur.get("", response_model=list[InvestigationResumee])
def lister_investigations(
    ctx: ContexteRequete = Depends(contexte_courant),
    statut: str | None = Query(default=None),
    limite: int = Query(default=50, ge=1, le=200),
    decalage: int = Query(default=0, ge=0),
) -> list[InvestigationResumee]:
    requete = select(Investigation).where(Investigation.organisation_id == ctx.organisation_id)
    if statut:
        requete = requete.where(Investigation.statut == statut)
    requete = requete.order_by(Investigation.created_at.desc()).limit(limite).offset(decalage)
    return [_resume(i) for i in ctx.session.scalars(requete)]


@routeur.get("/types-recherche", response_model=TypesRechercheSortie)
def lister_types_recherche(
    ctx: ContexteRequete = Depends(contexte_courant),
) -> TypesRechercheSortie:
    """Types de points de départ utilisables, et lesquels le plan autorise.

    Déclaré **avant** la route `/{investigation_id}`, sans quoi FastAPI prendrait
    « types-recherche » pour un identifiant d'investigation.

    L'interface s'en sert pour construire le formulaire : les types indisponibles
    (outil absent du serveur) n'apparaissent pas du tout, ceux que le plan ne couvre
    pas apparaissent grisés avec leur motif. Ajouter un chercheur suffit donc à le
    faire apparaître dans l'interface, sans y toucher.
    """
    from app.moteur.chercheurs.registre import chercheurs_disponibles
    from app.services.points_depart import chercheur_autorise

    types: list[TypeRechercheSortie] = []
    for chercheur in chercheurs_disponibles():
        autorise, motif = chercheur_autorise(chercheur.type_point_depart, ctx.plan)
        types.append(
            TypeRechercheSortie(
                type=chercheur.type_point_depart,
                libelle=chercheur.libelle,
                exemple=chercheur.exemple,
                autorise=autorise,
                motif=motif,
            )
        )

    # Le pseudonyme d'abord (c'est le point de départ obligatoire), puis les autres
    # par ordre alphabétique de libellé, pour un affichage stable.
    types.sort(key=lambda t: (t.type != TypePointDepart.PSEUDO.value, t.libelle))
    return TypesRechercheSortie(
        types=types,
        max_points_depart=ctx.plan.max_points_depart,
        max_sites_analyses=ctx.plan.max_sites_analyses,
        nom_plan=ctx.plan.nom_affiche,
    )


def _detail(ctx: ContexteRequete, investigation: Investigation) -> InvestigationDetaillee:
    nb_noeuds = ctx.session.scalar(
        select(func.count(NoeudGraphe.id)).where(NoeudGraphe.investigation_id == investigation.id)
    )
    nb_aretes = ctx.session.scalar(
        select(func.count(AreteGraphe.id)).where(AreteGraphe.investigation_id == investigation.id)
    )
    nb_propositions = ctx.session.scalar(
        select(func.count(PropositionPivot.id)).where(
            PropositionPivot.investigation_id == investigation.id,
            PropositionPivot.statut == StatutPropositionPivot.EN_ATTENTE.value,
        )
    )
    auteur = ctx.session.get(Utilisateur, investigation.cree_par) if investigation.cree_par else None

    points = ctx.session.scalars(
        select(PointDepart)
        .where(PointDepart.investigation_id == investigation.id)
        .order_by(PointDepart.created_at)
    ).all()

    base = _resume(investigation)
    return InvestigationDetaillee(
        **base.model_dump(),
        variantes=investigation.variantes or [],
        options=investigation.options or {},
        message_erreur=investigation.message_erreur,
        cree_par_email=auteur.email if auteur else None,
        nb_noeuds=nb_noeuds or 0,
        nb_aretes=nb_aretes or 0,
        nb_propositions_en_attente=nb_propositions or 0,
        points_depart=[
            PointDepartSortie(
                id=p.id, type=p.type, valeur=p.valeur, statut=p.statut,
                message_erreur=p.message_erreur, nb_comptes_trouves=p.nb_comptes_trouves,
                detail=p.detail or {},
            )
            for p in points
        ],
    )


@routeur.get("/{investigation_id}", response_model=InvestigationDetaillee)
def obtenir_investigation(
    investigation_id: str,
    ctx: ContexteRequete = Depends(contexte_courant),
) -> InvestigationDetaillee:
    return _detail(ctx, _recuperer(ctx, investigation_id))


@routeur.post("/{investigation_id}/annuler", response_model=InvestigationDetaillee)
def annuler_investigation(
    investigation_id: str,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ANALYSTE.value)),
) -> InvestigationDetaillee:
    """Arrête une investigation en cours, en conservant ce qu'elle a déjà trouvé.

    L'arrêt est **coopératif** : le statut passé en base est consulté par chaque
    étape du cycle, qui s'interrompt à son prochain point de reprise plutôt que
    d'être tuée en plein travail (voir `app/moteur/annulation.py`). La recherche
    Maigret en cours, elle, est arrêtée en quelques secondes.

    Le quota n'est rendu que si la recherche n'a **rien** trouvé. Rembourser une
    recherche déjà fructueuse permettrait d'enchaîner « je lance, je récupère les
    résultats, j'annule, je suis remboursé » — soit un volume gratuit illimité.
    """
    from app.moteur.annulation import marquer_annulation

    investigation = _recuperer(ctx, investigation_id)

    if investigation.statut not in (
        StatutInvestigation.EN_ATTENTE.value,
        StatutInvestigation.EN_COURS.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cette investigation n'est pas en cours (statut : {investigation.statut}).",
        )

    rien_trouve = investigation.nb_profils_trouves == 0

    investigation.statut = StatutInvestigation.ANNULEE.value
    investigation.etape_courante = "Arrêtée à votre demande"
    investigation.terminee_le = maintenant()

    # Les propositions de rebond encore en attente n'ont plus lieu d'être : les
    # laisser ouvertes proposerait de relancer une investigation arrêtée.
    ctx.session.query(PropositionPivot).filter(
        PropositionPivot.investigation_id == investigation.id,
        PropositionPivot.statut == StatutPropositionPivot.EN_ATTENTE.value,
    ).update({"statut": StatutPropositionPivot.REFUSEE.value}, synchronize_session=False)

    if rien_trouve:
        rembourser_quota(ctx.session, ctx.organisation_id, "recherches")

    journaliser(
        ctx.session, ActionJournal.INVESTIGATION_ANNULEE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=investigation.pseudo_initial,
        investigation_id=investigation.id, requete=requete,
        detail={"quota_rendu": rien_trouve, "profils_conserves": investigation.nb_profils_trouves},
    )
    ctx.session.commit()

    # Après le commit seulement : le cache ne doit jamais annoncer une annulation que
    # la base n'a pas encore enregistrée.
    marquer_annulation(investigation.id)

    return _detail(ctx, investigation)


@routeur.delete("/{investigation_id}", status_code=status.HTTP_204_NO_CONTENT)
def supprimer_investigation(
    investigation_id: str,
    requete: Request,
    ctx: ContexteRequete = Depends(exiger_role(RoleMembre.ANALYSTE.value)),
) -> None:
    """Supprime définitivement une investigation et toutes ses données associées.

    Suppression réelle et non archivage : c'est ce qu'exige un droit à l'effacement
    exercé par une personne figurant dans les résultats.
    """
    investigation = _recuperer(ctx, investigation_id)
    journaliser(
        ctx.session, ActionJournal.INVESTIGATION_SUPPRIMEE,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=investigation.pseudo_initial,
        investigation_id=investigation.id, requete=requete,
    )
    ctx.session.delete(investigation)
    ctx.session.commit()


@routeur.post("/{investigation_id}/relancer-correlation", response_model=InvestigationDetaillee)
def relancer_correlation(
    investigation_id: str,
    ctx: ContexteRequete = Depends(contexte_courant),
) -> InvestigationDetaillee:
    """Recalcule les scores sans relancer aucune requête réseau.

    Utile après ajustement des poids dans config.yaml, ou après qu'un analyste a
    marqué des faux positifs : les règles croisées changent alors pour tout le monde.
    """
    from app.services.investigation import rescorer_investigation

    investigation = _recuperer(ctx, investigation_id)
    rescorer_investigation(ctx.session, investigation)
    ctx.session.commit()
    return _detail(ctx, investigation)


@routeur.get("/{investigation_id}/export")
def exporter(
    investigation_id: str,
    requete: Request,
    format: str = Query(default="json", pattern="^(json|csv|pdf)$"),
    ctx: ContexteRequete = Depends(contexte_courant),
) -> Response:
    """Exporte les résultats en JSON (complet), CSV (tableau des profils) ou PDF
    (rapport présentable, avec le détail des données extraites)."""
    investigation = _recuperer(ctx, investigation_id)

    if format == "csv" and not ctx.plan.possede(EXPORT_CSV):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"L'export CSV n'est pas inclus dans le plan {ctx.plan.nom_affiche}.",
        )
    if format == "pdf" and not ctx.plan.possede(EXPORT_PDF):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"L'export PDF n'est pas inclus dans le plan {ctx.plan.nom_affiche}.",
        )

    profils = ctx.session.scalars(
        select(ProfilIdentite)
        .where(ProfilIdentite.investigation_id == investigation.id)
        .order_by(ProfilIdentite.score_confiance.desc())
    ).all()

    journaliser(
        ctx.session, ActionJournal.EXPORT,
        organisation_id=ctx.organisation_id, utilisateur_id=ctx.utilisateur.id,
        email_utilisateur=ctx.utilisateur.email, cible=investigation.pseudo_initial,
        investigation_id=investigation.id, requete=requete, detail={"format": format},
    )
    ctx.session.commit()

    nom_fichier = f"investigation_{investigation.pseudo_initial}_{investigation.id[:8]}"

    if format == "csv":
        tampon = io.StringIO()
        redacteur = csv.writer(tampon, delimiter=";")   # point-virgule : ouverture directe dans Excel FR
        redacteur.writerow(
            ["Site", "Domaine", "URL", "Pseudonyme", "Score", "Niveau", "Verdict", "Profondeur", "Enrichi"]
        )
        for profil in profils:
            redacteur.writerow([
                profil.site_nom, profil.site_domaine, profil.url, profil.pseudo_sur_le_site,
                profil.score_confiance, profil.niveau, profil.verdict_manuel or "",
                profil.profondeur, "oui" if profil.enrichi else "non",
            ])
        return Response(
            content="﻿" + tampon.getvalue(),   # BOM UTF-8 pour les accents dans Excel
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nom_fichier}.csv"'},
        )

    donnees = ctx.session.scalars(
        select(DonneeExtraite).where(DonneeExtraite.investigation_id == investigation.id)
    ).all()

    if format == "pdf":
        from app.services.export_pdf import generer_rapport_pdf

        donnees_par_profil: dict[str, list[DonneeExtraite]] = {}
        for donnee in donnees:
            donnees_par_profil.setdefault(donnee.profil_id, []).append(donnee)

        pdf = generer_rapport_pdf(
            investigation, profils, donnees_par_profil,
            organisation_nom=ctx.organisation.nom,
        )
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{nom_fichier}.pdf"'},
        )

    par_profil: dict[str, list[dict]] = {}
    for donnee in donnees:
        par_profil.setdefault(donnee.profil_id, []).append(
            {"type": donnee.type, "valeur": donnee.valeur, "source": donnee.module_source}
        )

    contenu = {
        "investigation": {
            "id": investigation.id,
            "pseudo_initial": investigation.pseudo_initial,
            "variantes": investigation.variantes,
            "statut": investigation.statut,
            "options": investigation.options,
            "cree_le": investigation.created_at.isoformat() if investigation.created_at else None,
            "terminee_le": investigation.terminee_le.isoformat() if investigation.terminee_le else None,
        },
        "profils": [
            {
                "site": p.site_nom, "url": p.url, "pseudo": p.pseudo_sur_le_site,
                "score": p.score_confiance, "niveau": p.niveau, "verdict": p.verdict_manuel,
                "profondeur": p.profondeur, "donnees_extraites": par_profil.get(p.id, []),
            }
            for p in profils
        ],
        "avertissement": (
            "Ces résultats sont des estimations probabilistes et non des certitudes. "
            "Ils doivent être vérifiés avant toute utilisation, et leur exploitation "
            "relève de la responsabilité de l'utilisateur dans le cadre légal applicable."
        ),
    }
    return Response(
        content=json.dumps(contenu, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}.json"'},
    )
