"""Tests des recherches par téléphone et par adresse, et de la portée du rebond.

Aucun accès réseau : les appels au moteur de recherche web sont simulés. Ces tests
verrouillent des défauts mesurés en conditions réelles le 01/08/2026, dont chacun
rendait la fonctionnalité inexploitable pour un analyste.
"""

from __future__ import annotations

import pytest

from app.modeles.enums import TypeDonnee
from app.moteur.chercheurs.adresse import ChercheurAdresse
from app.moteur.chercheurs.telephone import ChercheurTelephone, est_annuaire_inverse
from app.moteur.pivot.detecteur import DetecteurPivot, DonneeCandidate
from app.moteur.sources.duckduckgo import MentionWeb


class FausseMention(MentionWeb):
    pass


def mention(url: str, titre: str = "titre") -> MentionWeb:
    return MentionWeb(url=url, titre=titre, extrait="extrait")


# --- Téléphone --------------------------------------------------------------


def test_le_telephone_ne_fabrique_plus_de_faux_comptes(monkeypatch):
    """Défaut mesuré : `user-scanner` testait le numéro comme un **nom d'utilisateur**
    et produisait « https://youtube.com/@+33184944000 » — un identifiant YouTube ne
    peut pas contenir de « + ». Annoncer un compte inexistant est le pire défaut
    possible pour cet outil."""
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions", lambda *a, **k: []
    )
    resultat = ChercheurTelephone().chercher("+33140205050")

    assert resultat.erreur is None
    assert resultat.comptes == [], "un numéro ne doit jamais produire de compte"


def test_le_telephone_cherche_en_graphie_compacte(monkeypatch):
    """Défaut mesuré : cherché « 01 40 20 50 50 », le moteur traite les groupes comme
    des mots séparés et renvoie des calculatrices. Cherché « 0140205050 », il renvoie
    le Musée du Louvre. Seules les graphies compactes sont donc utilisées."""
    requetes: list[str] = []

    def faux_rechercher(requete: str, nb_max: int = 10):
        requetes.append(requete)
        return []

    monkeypatch.setattr("app.moteur.sources.duckduckgo.rechercher_mentions", faux_rechercher)
    ChercheurTelephone().chercher("+33140205050")

    assert requetes, "aucune recherche web n'a été lancée"
    for requete in requetes:
        assert " " not in requete, f"graphie espacée utilisée : {requete!r}"
        assert '"' not in requete, (
            f"guillemets utilisés : {requete!r} — lite.duckduckgo.com renvoie "
            "zéro résultat sur une expression entre guillemets"
        )
    assert "0140205050" in requetes


def test_le_telephone_ecarte_les_annuaires_inverses(monkeypatch):
    """Ces services publient une page pour tout numéro, y compris inexistant :
    en trouver une n'apprend rien et masquerait les vraies pistes."""
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions",
        lambda *a, **k: [
            mention("https://www.truecaller.com/fr/0140205050", "Reverse lookup"),
            mention("https://www.tellows.fr/num/0140205050", "Qui m'appelle"),
            mention("https://www.google.com/search?q=x", "Google"),
            mention("https://contact.louvre.fr/hc/fr", "Contacter le Musée du Louvre"),
        ],
    )
    resultat = ChercheurTelephone().chercher("+33140205050")

    liens = resultat.valeurs_information(TypeDonnee.LIEN_EXTERNE)
    assert liens == ["https://contact.louvre.fr/hc/fr"], liens


def test_le_telephone_conserve_les_donnees_du_numero(monkeypatch):
    """Ce que libphonenumber déduit du numéro reste la base : pays, type de ligne."""
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions", lambda *a, **k: []
    )
    resultat = ChercheurTelephone().chercher("+33140205050")

    assert resultat.detail["pays"] == "FR"
    assert resultat.detail["type_ligne"] == "ligne fixe"
    assert "+33140205050" in resultat.valeurs_information(TypeDonnee.TELEPHONE)


@pytest.mark.parametrize(
    "domaine,attendu",
    [
        ("www.truecaller.com", True),
        ("tellows.fr", True),
        ("maps.google.com", True),
        ("contact.louvre.fr", False),
        ("www.infobel.com", False),
        ("annuaire-inverse-france.com", False),   # publie le nom de l'établissement
    ],
)
def test_reconnaissance_des_annuaires_inverses(domaine: str, attendu: bool):
    assert est_annuaire_inverse(domaine) is attendu


# --- Adresse ----------------------------------------------------------------


def test_ladresse_cherche_les_mentions_sur_le_web(monkeypatch):
    """Défaut mesuré : la recherche par adresse ne faisait que renormaliser ce que
    l'analyste venait de saisir. Elle doit remonter les pages qui la mentionnent —
    c'est ainsi qu'on découvre qu'une agence bancaire occupe cette adresse."""
    monkeypatch.setattr(
        "app.moteur.chercheurs.adresse.ChercheurAdresse._chercher_ban",
        lambda self, adresse, resultat: (
            resultat.ajouter_information(
                TypeDonnee.LOCALISATION, "10 Rue de Rivoli 75004 Paris", confiance=0.97
            )
            or True
        ),
    )
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions",
        lambda *a, **k: [
            mention("https://www.pagesjaunes.fr/pros/53102742", "Bnp Paribas - Banque"),
        ],
    )

    resultat = ChercheurAdresse().chercher("10 rue de Rivoli 75004 Paris")

    liens = resultat.valeurs_information(TypeDonnee.LIEN_EXTERNE)
    assert "https://www.pagesjaunes.fr/pros/53102742" in liens


def test_ladresse_cherche_la_forme_normalisee_sans_guillemets(monkeypatch):
    """La graphie normalisée est celle sous laquelle les annuaires publient une
    adresse. Et les guillemets font échouer la requête (mesuré)."""
    requetes: list[str] = []

    monkeypatch.setattr(
        "app.moteur.chercheurs.adresse.ChercheurAdresse._chercher_ban",
        lambda self, adresse, resultat: (
            resultat.ajouter_information(
                TypeDonnee.LOCALISATION, "10 Rue de Rivoli 75004 Paris", confiance=0.97
            )
            or True
        ),
    )

    def faux_rechercher(requete: str, nb_max: int = 10):
        requetes.append(requete)
        return []

    monkeypatch.setattr("app.moteur.sources.duckduckgo.rechercher_mentions", faux_rechercher)
    ChercheurAdresse().chercher("10 rue rivoli paris")

    assert requetes == ["10 Rue de Rivoli 75004 Paris"], requetes


# --- Portée du rebond -------------------------------------------------------


def _candidate(type_donnee: str, valeur: str) -> DonneeCandidate:
    return DonneeCandidate(
        identifiant="d1", type=type_donnee, valeur=valeur,
        valeur_normalisee=valeur.lower(), profil_id="p1", profil_site="GitHub",
        confiance=1.0,
    )


def test_le_nom_affiche_est_pivotable():
    """Défaut mesuré : seul `nom_reel` était pivotable, or il n'est renseigné que par
    Gravatar. Sur une investigation réelle de 26 comptes, 13 noms affichés étaient
    disponibles et aucun n'était exploité — le rebond avait une portée bien plus
    étroite que ne le laissait croire la configuration."""
    detecteur = DetecteurPivot()
    pivots = detecteur.detecter([_candidate(TypeDonnee.NOM_AFFICHE.value, "Linus Torvalds")])

    assert len(pivots) == 1
    assert pivots[0].valeur == "linustorvalds"
    # Le type d'origine est conservé : un rebond parti d'un nom d'affichage n'a pas
    # la même fiabilité qu'un rebond parti d'un nom déclaré comme réel.
    assert pivots[0].type_pivot == TypeDonnee.NOM_AFFICHE.value


def test_un_nom_affiche_en_un_seul_mot_nest_pas_pivotable():
    """« Nicolas » ou « ken » ne désignent personne : les rechercher noierait
    l'investigation sous les homonymes."""
    detecteur = DetecteurPivot()
    for valeur in ("Nicolas", "ken", "torvalds"):
        assert detecteur.detecter([_candidate(TypeDonnee.NOM_AFFICHE.value, valeur)]) == []


def test_un_nom_sans_rapport_avec_la_cible_est_ecarte():
    """Mesuré le 01/08/2026 : sur une investigation « torvalds », le nom affiché
    « Paolo Ferrante » — porté par un compte homonyme, donc un faux positif —
    déclenchait une recherche complète sur quelqu'un qui n'a aucun rapport."""
    detecteur = DetecteurPivot(pseudos_reference=["torvalds"])

    assert detecteur.detecter([_candidate(TypeDonnee.NOM_AFFICHE.value, "Paolo Ferrante")]) == []

    # Les noms qui partagent la racine recherchée restent, eux, de vraies pistes :
    # « Pauline Torvalds » est un lien familial, pas un homonyme fortuit.
    for nom in ("Linus Torvalds", "Pauline Torvalds"):
        pivots = detecteur.detecter([_candidate(TypeDonnee.NOM_AFFICHE.value, nom)])
        assert len(pivots) == 1, nom


def test_sans_reference_le_filtre_de_nom_ne_sapplique_pas():
    """Le filtre ne doit jamais bloquer une investigation dont on ignore la cible."""
    detecteur = DetecteurPivot(pseudos_reference=[])
    assert len(detecteur.detecter([_candidate(TypeDonnee.NOM_AFFICHE.value, "Paolo Ferrante")])) == 1


def test_le_hash_gravatar_nest_plus_pris_pour_une_adresse():
    """Défaut mesuré : `gravatar_email_md5_hash` était enregistré comme EMAIL,
    affichant « 690495313b377cd5578c2d0f8cb314ee » dans la colonne des adresses."""
    from app.services.investigation import CORRESPONDANCE_IDS_MAIGRET

    assert "gravatar_email_md5_hash" not in CORRESPONDANCE_IDS_MAIGRET


# --- Exploitation des pages citant un numéro ou une adresse -----------------
# Les titres et extraits ci-dessous sont ceux réellement relevés en base après une
# recherche sur le standard du Louvre (+33140205050), le 02/08/2026.


def _mentions_du_louvre() -> list[MentionWeb]:
    return [
        MentionWeb(
            url="https://www.annuaire-inverse-france.com/annuaire-entreprises/paris",
            titre="MUSEE DU LOUVRE Paris - Annuaire inversé",
            extrait=(
                "MUSEE DU LOUVRE 34 quai francois mitterrand 75001 Paris 0140205050 "
                "musées - Paris - Ile-de-France"
            ),
        ),
        MentionWeb(
            url="https://www.infobel.com/fr/france/musee_du_louvre/paris/FR108534803",
            titre="Musée Du Louvre, Paris, FR | Informations sur l'entreprise",
            extrait="Trouvez des informations sur cette entreprise, telles que...",
        ),
        MentionWeb(
            url="https://telephone.fr/informations-musee-du-louvre/",
            titre="Comment contacter Musée du Louvre : téléphone et coordonnées",
            extrait="Pour contacter Musée du Louvre par téléphone, composez le 0140205050.",
        ),
        MentionWeb(
            url="https://www.quinumero.info/numero/0140205050/",
            titre="0140205050 - Commentaires: 7 (Négatif: 0) - Qui est ce numéro ...",
            extrait=(
                "À qui appartient ce numéro de téléphone?? Nombre d'opinions: 7. "
                "Opinion majoritaire: indifférent"
            ),
        ),
    ]


def test_le_nom_de_lentite_est_extrait_des_pages_citant_le_numero(monkeypatch):
    """Défaut mesuré le 02/08/2026 : le nom figurait dans six titres sur huit, et
    l'outil ne rendait que des liens — l'analyste devait le lire lui-même."""
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions",
        lambda *a, **k: _mentions_du_louvre(),
    )
    resultat = ChercheurTelephone().chercher("+33140205050")

    entreprises = resultat.valeurs_information(TypeDonnee.ENTREPRISE)
    assert any("louvre" in valeur.lower() for valeur in entreprises), entreprises


def test_ladresse_postale_est_extraite_des_extraits(monkeypatch):
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions",
        lambda *a, **k: _mentions_du_louvre(),
    )
    resultat = ChercheurTelephone().chercher("+33140205050")

    lieux = resultat.valeurs_information(TypeDonnee.LOCALISATION)
    assert any("75001" in valeur for valeur in lieux), lieux


def test_les_pages_sans_contenu_sont_ecartees(monkeypatch):
    """`quinumero.info` ne publie que des compteurs d'avis : il passait au travers de
    la liste de domaines, d'où un critère fondé aussi sur le contenu."""
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions",
        lambda *a, **k: _mentions_du_louvre(),
    )
    resultat = ChercheurTelephone().chercher("+33140205050")

    liens = resultat.valeurs_information(TypeDonnee.LIEN_EXTERNE)
    assert not any("quinumero" in lien for lien in liens), liens


def test_un_nom_cite_par_un_seul_site_ne_suffit_pas(monkeypatch):
    """Un titre isolé peut dire n'importe quoi : il faut deux domaines concordants.

    C'est ce qui évite d'affirmer une identité sur la foi d'une seule page — le cas
    normal pour un numéro de particulier, où rien ne doit être nommé.
    """
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions",
        lambda *a, **k: [
            MentionWeb(
                url="https://exemple-unique.fr/fiche",
                titre="Cabinet Dupont et Associés - Exemple",
                extrait="Un texte quelconque sans autre mention.",
            )
        ],
    )
    resultat = ChercheurTelephone().chercher("+33140205050")
    assert resultat.valeurs_information(TypeDonnee.ENTREPRISE) == []


def test_ladresse_ecarte_la_cartographie_et_limmobilier(monkeypatch):
    """Mesuré le 02/08/2026 : la recherche par adresse n'appliquait aucun filtre et
    rendait des itinéraires RATP, Bing Maps et des estimations MeilleursAgents."""
    monkeypatch.setattr(
        "app.moteur.sources.duckduckgo.rechercher_mentions",
        lambda *a, **k: [
            MentionWeb(url="https://www.ratp.fr/itineraires/55-rue", titre="Itinéraire", extrait=""),
            MentionWeb(url="https://www.bing.com/maps?where=55", titre="Bing Maps", extrait=""),
            MentionWeb(
                url="https://www.meilleursagents.com/prix-immobilier/paris",
                titre="Prix immobilier", extrait="",
            ),
            MentionWeb(
                url="https://fr.wikipedia.org/wiki/Palais_de_l_Elysee",
                titre="Palais de l'Élysée — Wikipédia", extrait="Résidence officielle.",
            ),
        ],
    )
    # Le géocodage n'est pas l'objet du test : seul le filtrage des mentions l'est.
    chercheur = ChercheurAdresse()
    monkeypatch.setattr(chercheur, "_chercher_ban", lambda *a, **k: False)
    monkeypatch.setattr(chercheur, "_chercher_nominatim", lambda *a, **k: None)
    resultat = chercheur.chercher("55 rue du Faubourg Saint-Honore, 75008 Paris")

    liens = resultat.valeurs_information(TypeDonnee.LIEN_EXTERNE)
    assert any("wikipedia" in lien for lien in liens), liens
    for indesirable in ("ratp.fr", "bing.com", "meilleursagents"):
        assert not any(indesirable in lien for lien in liens), (indesirable, liens)
