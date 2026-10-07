"""Génération du rapport PDF d'une investigation.

Réservé aux plans payants (`EXPORT_PDF`) : c'est un livrable présentable à un client
ou intégrable à un dossier, contrairement au CSV brut ou au JSON complet.

`reportlab` est déjà une dépendance transitive (via Maigret) : pas de nouvelle
bibliothèque à ajouter, pas de service tiers, aucune police téléchargée à l'exécution.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

if TYPE_CHECKING:
    from app.modeles.investigation import DonneeExtraite, Investigation, ProfilIdentite

COULEUR_ENTETE = colors.HexColor("#1f2937")
COULEUR_NIVEAU = {
    "eleve": colors.HexColor("#15803d"),
    "moyen": colors.HexColor("#b45309"),
    "faible": colors.HexColor("#b91c1c"),
}

AVERTISSEMENT = (
    "Ces résultats sont des estimations probabilistes, pas des certitudes : ils "
    "doivent être vérifiés avant toute exploitation. Chaque recherche ayant produit "
    "ce rapport a été journalisée avec son auteur, son organisation et sa cible. "
    "L'utilisateur est seul responsable de la légalité de son usage."
)


def generer_rapport_pdf(
    investigation: Investigation,
    profils: list[ProfilIdentite],
    donnees_par_profil: dict[str, list[DonneeExtraite]],
    *,
    organisation_nom: str,
) -> bytes:
    """Construit le PDF en mémoire et rend ses octets."""
    tampon = io.BytesIO()
    document = SimpleDocTemplate(
        tampon, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
        title=f"Rapport d'investigation — {investigation.pseudo_initial}",
    )

    styles = getSampleStyleSheet()
    style_titre = ParagraphStyle(
        "TitreRapport", parent=styles["Title"], textColor=COULEUR_ENTETE, spaceAfter=4,
    )
    style_soustitre = ParagraphStyle(
        "SousTitre", parent=styles["Normal"], textColor=colors.grey, spaceAfter=18,
    )
    style_section = ParagraphStyle(
        "Section", parent=styles["Heading2"], textColor=COULEUR_ENTETE,
        spaceBefore=16, spaceAfter=8,
    )
    style_avertissement = ParagraphStyle(
        "Avertissement", parent=styles["Normal"], fontSize=8, textColor=colors.grey,
        borderColor=colors.lightgrey, borderWidth=0.5, borderPadding=8,
    )
    style_donnee = ParagraphStyle("Donnee", parent=styles["Normal"], fontSize=8)

    elements = [
        Paragraph("Rapport d'investigation Ops", style_titre),
        Paragraph(
            f"Cible initiale : <b>{_echapper(investigation.pseudo_initial)}</b> — "
            f"organisation {_echapper(organisation_nom)} — "
            f"{len(profils)} profil(s) trouvé(s)",
            style_soustitre,
        ),
        Paragraph(AVERTISSEMENT, style_avertissement),
        Paragraph("Profils identifiés", style_section),
    ]

    entetes = ["Site", "Pseudonyme", "Score", "Niveau", "Profondeur"]
    lignes = [entetes]
    for profil in profils:
        lignes.append([
            profil.site_nom,
            profil.pseudo_sur_le_site or "",
            f"{profil.score_confiance:.0%}" if profil.score_confiance is not None else "—",
            (profil.niveau or "—").capitalize(),
            str(profil.profondeur),
        ])

    tableau = Table(lignes, colWidths=[5 * cm, 4 * cm, 2 * cm, 2.5 * cm, 2.5 * cm], repeatRows=1)
    style_tableau = [
        ("BACKGROUND", (0, 0), (-1, 0), COULEUR_ENTETE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for index, profil in enumerate(profils, start=1):
        couleur = COULEUR_NIVEAU.get(profil.niveau or "")
        if couleur:
            style_tableau.append(("TEXTCOLOR", (3, index), (3, index), couleur))
    tableau.setStyle(TableStyle(style_tableau))
    elements.append(tableau)

    profils_avec_donnees = [p for p in profils if donnees_par_profil.get(p.id)]
    if profils_avec_donnees:
        elements.append(Paragraph("Détail des informations extraites", style_section))
        for profil in profils_avec_donnees:
            bloc = [Paragraph(f"<b>{_echapper(profil.site_nom)}</b> — {_echapper(profil.url or '')}", style_donnee)]
            for donnee in donnees_par_profil[profil.id]:
                bloc.append(
                    Paragraph(f"• {_echapper(donnee.type)} : {_echapper(donnee.valeur)}", style_donnee)
                )
            elements.append(KeepTogether(bloc))
            elements.append(Spacer(1, 6))

    document.build(elements)
    return tampon.getvalue()


def _echapper(texte: str | None) -> str:
    """Échappe les caractères spéciaux XML : reportlab interprète le texte des
    `Paragraph` comme un sous-ensemble de HTML, une donnée extraite d'un site tiers
    pourrait donc casser la mise en page ou injecter une balise."""
    if not texte:
        return ""
    return (
        texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
