"""Tests du moteur de corrélation — le cœur « intelligent » du produit.

Ces tests protègent les décisions de scoring : ce sont elles qui déterminent si un
compte est attribué ou non à une personne réelle. Une régression ici produirait des
conclusions fausses sur des individus.
"""

from __future__ import annotations

import pytest

from app.modeles.enums import NiveauConfiance
from app.moteur.correlation.base import (
    ContexteCorrelation,
    ProfilEvalue,
    analyser_date,
    normaliser,
    normaliser_pseudo,
    separer_suffixe_numerique,
)
from app.moteur.correlation.registre import charger_regles
from app.moteur.correlation.regles.avatar_phash import distance_hamming
from app.moteur.correlation.scoreur import scorer_profil, scorer_tous


def profil(identifiant: str, pseudo: str, site: str = "GitHub", **kwargs) -> ProfilEvalue:
    return ProfilEvalue(
        identifiant=identifiant,
        site_nom=site,
        site_domaine=kwargs.pop("domaine", f"{site.lower()}.com"),
        url=kwargs.pop("url", f"https://{site.lower()}.com/{pseudo}"),
        pseudo_sur_le_site=pseudo,
        **kwargs,
    )


# --- Utilitaires de normalisation ------------------------------------------


def test_normalisation_supprime_accents_et_ponctuation():
    assert normaliser("Jean-Luc P.") == "jean luc p"
    assert normaliser("ÉLÈVE") == "eleve"


def test_normalisation_pseudo_ignore_les_separateurs():
    # Ces trois graphies désignent le même identifiant selon les sites
    assert normaliser_pseudo("john.doe") == normaliser_pseudo("john_doe") == normaliser_pseudo("john-doe")


def test_separation_suffixe_numerique():
    assert separer_suffixe_numerique("john92") == ("john", "92")
    assert separer_suffixe_numerique("john_92") == ("john", "92")
    # Base trop courte pour être significative : on ne découpe pas
    assert separer_suffixe_numerique("ab1") == ("ab1", None)
    assert separer_suffixe_numerique("john") == ("john", None)


def test_analyse_des_dates_multiformats():
    assert analyser_date("2015-03-12") is not None
    assert analyser_date("2015-03-12T10:00:00Z") is not None
    assert analyser_date("1160418092") is not None       # horodatage Unix (Hacker News)
    assert analyser_date("pas une date") is None
    assert analyser_date("") is None


def test_distance_hamming():
    assert distance_hamming("ff00", "ff00") == 0
    assert distance_hamming("ff00", "ff01") == 1
    # Longueurs différentes : incomparable, et surtout pas une distance de 0
    assert distance_hamming("ff00", "ff0000") is None
    assert distance_hamming("zzzz", "ff00") is None


# --- Règles ----------------------------------------------------------------


def test_les_regles_sont_toutes_decouvertes():
    noms = {r.nom for r in charger_regles()}
    assert {
        "pseudo_similarite", "avatar_phash", "liens_croises",
        "coherence_temporelle", "contenu_bio", "email_partage", "site_douteux",
        "identite_contradictoire",
    } <= noms


def test_pseudo_identique_donne_un_score_positif():
    cible = profil("1", "jeanmartin")
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[cible])
    resultat = scorer_profil(cible, contexte)
    assert resultat.score > 0
    assert any(c.regle == "pseudo_similarite" and c.score_regle == 1.0 for c in resultat.contributions)


def test_pseudo_eloigne_est_penalise():
    cible = profil("1", "xxjeanxx")
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[cible])
    resultat = scorer_profil(cible, contexte)
    assert resultat.score == 0
    assert resultat.niveau == NiveauConfiance.FAIBLE


def test_signal_unique_ne_peut_pas_atteindre_la_confiance_elevee():
    """Un pseudonyme identique seul ne doit jamais suffire à conclure.

    C'est la protection centrale contre les faux positifs : sur un pseudonyme
    courant, des dizaines de personnes sans lien le partagent.
    """
    cible = profil("1", "jeanmartin")
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[cible])
    resultat = scorer_profil(cible, contexte)
    assert resultat.nb_signaux_positifs == 1
    assert resultat.score <= 65
    assert resultat.niveau != NiveauConfiance.ELEVE


def test_signaux_multiples_donnent_une_confiance_elevee():
    a = profil(
        "1", "jeanmartin", "GitHub",
        donnees={
            "email": ["jean@exemple.fr"],
            "avatar_phash": ["ff00ff00ff00ff00"],
            "bio": ["Developpeur Python a Lyon, amateur de velo"],
        },
    )
    b = profil(
        "2", "jeanmartin", "Mastodon",
        donnees={
            "email": ["jean@exemple.fr"],
            "avatar_phash": ["ff00ff00ff00ff00"],
            "bio": ["Lyon, developpeur Python et cycliste"],
        },
    )
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[a, b])
    resultats = {r.profil_id: r for r in scorer_tous(contexte)}
    assert resultats["1"].nb_signaux_positifs >= 3
    assert resultats["1"].niveau == NiveauConfiance.ELEVE
    assert resultats["1"].score >= 85


def test_email_generique_github_ne_relie_pas_deux_profils():
    """Les adresses de masquage GitHub sont partagées par des millions de comptes."""
    a = profil("1", "jeanmartin", "GitHub", donnees={"email": ["noreply@github.com"]})
    b = profil("2", "jeanmartin", "GitLab", donnees={"email": ["noreply@github.com"]})
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[a, b])
    resultat = scorer_profil(a, contexte)
    assert not any(c.regle == "email_partage" for c in resultat.contributions)


def test_resultat_par_recherche_approximative_est_penalise():
    exact = profil("1", "jeanmartin", "GitHub")
    approximatif = profil("2", "jeanmartin", "Autre", est_similaire=True)
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[exact, approximatif])
    resultats = {r.profil_id: r for r in scorer_tous(contexte)}
    assert resultats["2"].score < resultats["1"].score
    assert any(c.regle == "site_douteux" for c in resultats["2"].contributions)


def test_site_connu_pour_faux_positifs_est_penalise():
    cible = profil("1", "jeanmartin", "Instructables", domaine="www.instructables.com")
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[cible])
    resultat = scorer_profil(cible, contexte)
    assert any(c.regle == "site_douteux" and c.score_regle < 0 for c in resultat.contributions)
    assert resultat.score < 40


def test_lien_explicite_entre_profils_est_reconnu():
    a = profil(
        "1", "jeanmartin", "GitHub",
        url="https://github.com/jeanmartin",
        donnees={"lien_externe": ["https://mastodon.social/@jm"]},
    )
    b = profil("2", "jm", "Mastodon", domaine="mastodon.social", url="https://mastodon.social/@jm")
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[a, b])
    resultats = {r.profil_id: r for r in scorer_tous(contexte)}
    # Les deux profils bénéficient du lien : celui qui pointe et celui qui est pointé
    assert any(c.regle == "liens_croises" for c in resultats["1"].contributions)
    assert any(c.regle == "liens_croises" for c in resultats["2"].contributions)


def test_regle_qui_sabstient_ne_penalise_pas_le_score():
    """Un profil non enrichi ne doit pas être puni pour l'absence de données.

    Sans cette règle, tout compte du palier gratuit plafonnerait artificiellement bas.
    """
    sans_donnees = profil("1", "jeanmartin")
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[sans_donnees])
    resultat = scorer_profil(sans_donnees, contexte)
    regles_utilisees = {c.regle for c in resultat.contributions}
    assert "avatar_phash" not in regles_utilisees
    assert "email_partage" not in regles_utilisees
    assert resultat.score > 0


def test_verdict_manuel_prime_sur_le_calcul():
    valide = profil("1", "totalementdifferent", verdict_manuel="valide")
    rejete = profil("2", "jeanmartin", verdict_manuel="faux_positif")
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[valide, rejete])
    resultats = {r.profil_id: r for r in scorer_tous(contexte)}
    assert resultats["1"].score == 100
    assert resultats["2"].score == 0


def test_profil_rejete_ne_sert_plus_de_reference_croisee():
    """Un faux positif ne doit pas continuer à corroborer les autres profils."""
    rejete = profil(
        "1", "jeanmartin", "Faux",
        donnees={"email": ["jean@exemple.fr"]}, verdict_manuel="faux_positif",
    )
    autre = profil("2", "jeanmartin", "GitHub", donnees={"email": ["jean@exemple.fr"]})
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[rejete, autre])
    resultat = scorer_profil(autre, contexte)
    assert not any(c.regle == "email_partage" for c in resultat.contributions)


@pytest.mark.parametrize(
    "pseudo_trouve,attendu_minimal",
    [("jeanmartin", 60), ("jeanmartin92", 50), ("jeanmarrtin", 20)],
)
def test_variantes_de_pseudo_restent_credibles(pseudo_trouve: str, attendu_minimal: int):
    cible = profil("1", pseudo_trouve)
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[cible])
    assert scorer_profil(cible, contexte).score >= attendu_minimal


# --- Écartement des homonymes ----------------------------------------------
# Cas relevés en ouvrant à la main les comptes remontés sur « torvalds » le
# 02/08/2026 : ils existent tous, mais appartiennent à d'autres personnes.


def test_nom_declare_etranger_declasse_un_homonyme():
    """« instagram.com/torvalds » déclare « Marco Migozzi » : ce n'est pas la cible."""
    homonyme = profil(
        "1", "torvalds", "Instagram", donnees={"nom_affiche": ["Marco Migozzi"]}
    )
    contexte = ContexteCorrelation(pseudos_reference=["torvalds"], profils=[homonyme])
    resultat = scorer_profil(homonyme, contexte)

    assert any(
        c.regle == "identite_contradictoire" and c.score_regle < 0
        for c in resultat.contributions
    )
    assert resultat.niveau == NiveauConfiance.FAIBLE
    assert resultat.score < 40


def test_nom_declare_coherent_corrobore_le_compte():
    """« github.com/torvalds » déclare « Linus Torvalds » : le nom confirme."""
    cible = profil("1", "torvalds", "GitHub", donnees={"nom_affiche": ["Linus Torvalds"]})
    contexte = ContexteCorrelation(pseudos_reference=["torvalds"], profils=[cible])
    resultat = scorer_profil(cible, contexte)

    assert any(
        c.regle == "identite_contradictoire" and c.score_regle > 0
        for c in resultat.contributions
    )
    assert resultat.score > 60


def test_nom_dun_seul_mot_ne_penalise_pas():
    """« NaraKa » est un pseudonyme d'affichage, pas une identité civile.

    Pénaliser sur cette base écarterait des comptes légitimes dont le propriétaire
    n'a simplement pas renseigné son vrai nom.
    """
    compte = profil("1", "torvalds", "Steam", donnees={"nom_affiche": ["NaraKa"]})
    contexte = ContexteCorrelation(pseudos_reference=["torvalds"], profils=[compte])
    resultat = scorer_profil(compte, contexte)
    assert not any(c.regle == "identite_contradictoire" for c in resultat.contributions)


def test_deux_homonymes_au_meme_nom_ne_se_promeuvent_pas_mutuellement():
    """Deux comptes d'un même tiers ne doivent pas se corroborer l'un l'autre.

    Constaté en conditions réelles : sur « torvalds », Instagram et Pinterest
    déclarent tous deux « Marco Migozzi ». Traiter cette concordance comme une preuve
    les faisait passer tous les deux en confiance élevée, alors qu'elle établit
    exactement l'inverse — un tiers possède ce pseudonyme sur plusieurs plateformes.
    """
    a = profil("1", "torvalds", "Instagram", donnees={"nom_affiche": ["Marco Migozzi"]})
    b = profil("2", "torvalds", "Pinterest", donnees={"nom_affiche": ["Marco Migozzi"]})
    contexte = ContexteCorrelation(pseudos_reference=["torvalds"], profils=[a, b])
    resultat = scorer_profil(a, contexte)

    assert any(
        c.regle == "identite_contradictoire" and c.score_regle < 0
        for c in resultat.contributions
    )
    assert resultat.niveau != NiveauConfiance.ELEVE


def test_nom_recopie_du_pseudonyme_ne_compte_pas_comme_signal():
    """« Torvalds Torvalds » : le site a recopié le nom d'utilisateur dans le champ nom.

    Le compter corroborerait le pseudonyme par lui-même — la même information votant
    deux fois, assez pour hisser un inconnu en confiance élevée.
    """
    compte = profil(
        "1", "torvalds", "SoundCloud", donnees={"nom_affiche": ["Torvalds Torvalds"]}
    )
    contexte = ContexteCorrelation(pseudos_reference=["torvalds"], profils=[compte])
    resultat = scorer_profil(compte, contexte)

    assert not any(
        c.regle == "identite_contradictoire" and c.score_regle > 0
        for c in resultat.contributions
    )
    assert resultat.niveau != NiveauConfiance.ELEVE


def test_nom_reel_contenant_le_pseudonyme_corrobore():
    """« Dmitriy (Soxoj) Danilov » contient le pseudonyme : le nom rattache le compte."""
    cible = profil(
        "1", "sox0j", "Twitter", donnees={"nom_reel": ["Dmitriy Soxoj Danilov"]}
    )
    contexte = ContexteCorrelation(pseudos_reference=["soxoj"], profils=[cible])
    resultat = scorer_profil(cible, contexte)

    assert any(
        c.regle == "identite_contradictoire" and c.score_regle > 0
        for c in resultat.contributions
    )


def test_localisation_isolee_penalise_a_defaut_de_nom():
    """Le compte Steam « torvalds » se disait en Indonésie, les autres à Portland."""
    etranger = profil("1", "torvalds", "Steam", donnees={"localisation": ["Indonesia"]})
    a = profil("2", "torvalds", "GitHub", donnees={"localisation": ["Portland, OR"]})
    b = profil("3", "torvalds", "Mastodon", donnees={"localisation": ["Portland"]})
    contexte = ContexteCorrelation(
        pseudos_reference=["torvalds"], profils=[etranger, a, b]
    )
    resultat = scorer_profil(etranger, contexte)

    assert any(
        c.regle == "identite_contradictoire" and c.score_regle < 0
        for c in resultat.contributions
    )


def test_localisation_divergente_isolee_ne_penalise_pas():
    """Un seul autre compte localisé : un déménagement suffit à l'expliquer."""
    cible = profil("1", "jeanmartin", "GitHub", donnees={"localisation": ["Lyon"]})
    autre = profil("2", "jeanmartin", "Mastodon", donnees={"localisation": ["Berlin"]})
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[cible, autre])
    resultat = scorer_profil(cible, contexte)
    assert not any(c.regle == "identite_contradictoire" for c in resultat.contributions)


def test_localisation_compatible_ne_penalise_pas():
    """« Portland » et « Portland, OR » désignent le même lieu."""
    cible = profil("1", "torvalds", "GitHub", donnees={"localisation": ["Portland, OR"]})
    a = profil("2", "torvalds", "Mastodon", donnees={"localisation": ["Portland"]})
    b = profil("3", "torvalds", "Keybase", donnees={"localisation": ["Berlin"]})
    contexte = ContexteCorrelation(pseudos_reference=["torvalds"], profils=[cible, a, b])
    resultat = scorer_profil(cible, contexte)
    assert not any(c.regle == "identite_contradictoire" for c in resultat.contributions)


# --- Sites à caractère sexuel ----------------------------------------------
# Imputer un tel compte à quelqu'un sur la seule foi d'un pseudonyme identique est
# diffamatoire, et au RGPD un traitement de données de l'article 9 sur un faux
# positif. Mesuré le 02/08/2026 : « torvalds » remontait OnlyFans, Xvideos et
# ChaturBate à 65 %, « confiance moyenne ».


def test_site_sensible_non_corrobore_reste_en_confiance_faible():
    compte = profil(
        "1", "torvalds", "OnlyFans",
        domaine="onlyfans.com", tags=["porn"],
    )
    contexte = ContexteCorrelation(pseudos_reference=["torvalds"], profils=[compte])
    resultat = scorer_profil(compte, contexte)
    assert resultat.niveau == NiveauConfiance.FAIBLE
    assert resultat.score < 40


def test_site_sensible_identifie_par_domaine_sans_etiquette():
    """Fansly ne porte aucune étiquette « porn » dans la base Maigret."""
    compte = profil("1", "torvalds", "Fansly", domaine="fansly.com", tags=[])
    contexte = ContexteCorrelation(pseudos_reference=["torvalds"], profils=[compte])
    assert scorer_profil(compte, contexte).niveau == NiveauConfiance.FAIBLE


def test_site_sensible_reellement_corrobore_reste_exploitable():
    """Un avatar identique et une adresse partagée sont des preuves, pas une homonymie.

    L'outil ne doit pas devenir aveugle à un compte réel : c'est une information
    d'enquête légitime dès lors qu'elle repose sur autre chose qu'un pseudonyme.
    """
    sensible = profil(
        "1", "jeanmartin", "OnlyFans",
        domaine="onlyfans.com", tags=["porn"],
        donnees={
            "email": ["jean@exemple.fr"],
            "avatar_phash": ["ff00ff00ff00ff00"],
        },
    )
    connu = profil(
        "2", "jeanmartin", "GitHub",
        donnees={
            "email": ["jean@exemple.fr"],
            "avatar_phash": ["ff00ff00ff00ff00"],
        },
    )
    contexte = ContexteCorrelation(
        pseudos_reference=["jeanmartin"], profils=[sensible, connu]
    )
    resultat = scorer_profil(sensible, contexte)
    assert resultat.nb_signaux_positifs >= 2
    assert resultat.niveau == NiveauConfiance.ELEVE


def test_site_ordinaire_nest_pas_affecte_par_le_plafond_sensible():
    compte = profil("1", "jeanmartin", "GitHub", tags=["coding"])
    contexte = ContexteCorrelation(pseudos_reference=["jeanmartin"], profils=[compte])
    assert scorer_profil(compte, contexte).niveau == NiveauConfiance.MOYEN
