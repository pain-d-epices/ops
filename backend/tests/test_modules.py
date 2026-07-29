"""Tests du système de modules d'enrichissement.

Aucun accès réseau : les modules sont testés sur leur logique d'extraction, avec des
réponses simulées. Un test qui interroge GitHub échouerait un jour de panne ou de
changement d'API, pour une raison sans rapport avec notre code.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement
from app.modules.github import ModuleGitHub
from app.modules.mastodon import ModuleMastodon, nettoyer_html
from app.modules.reddit import ModuleReddit
from app.modules.registre import charger_modules, module_pour_domaine, modules_disponibles


class FauxClient:
    """Client HTTP simulé : renvoie des réponses prédéfinies, sans réseau."""

    def __init__(self, reponses: dict[str, Any], image: bytes | None = None):
        self.reponses = reponses
        self.image = image
        self.urls_appelees: list[str] = []

    def obtenir_json(self, url: str, **kwargs) -> Any:
        self.urls_appelees.append(url)
        for motif, contenu in self.reponses.items():
            if motif in url:
                return contenu
        return None

    def telecharger(self, url: str, **kwargs) -> bytes | None:
        self.urls_appelees.append(url)
        return self.image


# --- Registre --------------------------------------------------------------


def test_decouverte_automatique_des_modules():
    modules = charger_modules()
    assert {"github", "reddit", "mastodon", "gitlab", "hackernews", "keybase"} <= set(modules)


def test_selection_du_module_par_domaine():
    assert module_pour_domaine("github.com").nom == "github"
    assert module_pour_domaine("www.reddit.com").nom == "reddit"
    assert module_pour_domaine("mastodon.social").nom == "mastodon"
    # Un site sans module ne doit pas produire d'erreur, simplement aucun module
    assert module_pour_domaine("site-exotique-sans-module.fr") is None
    assert module_pour_domaine("") is None


def test_tous_les_modules_declarent_un_nom_et_des_domaines():
    for module in modules_disponibles():
        assert module.nom, f"{module.__class__.__name__} sans nom"
        assert module.domaines, f"{module.nom} sans domaine déclaré"
        assert module.libelle, f"{module.nom} sans libellé"


# --- Utilitaires partagés --------------------------------------------------


def test_extraction_des_emails_dans_un_texte():
    emails = ModuleSite.extraire_emails("Contact : jean.martin@exemple.fr ou autre@test.org")
    assert emails == ["jean.martin@exemple.fr", "autre@test.org"]
    assert ModuleSite.extraire_emails(None) == []
    assert ModuleSite.extraire_emails("aucun email ici") == []


def test_extraction_des_mentions():
    assert ModuleSite.extraire_mentions("Suivez @jeanmartin et @autre_compte") == [
        "jeanmartin", "autre_compte"
    ]
    # Une adresse électronique ne doit pas être prise pour une mention
    assert "exemple.fr" not in ModuleSite.extraire_mentions("ecrivez a jean@exemple.fr")


def test_deduction_du_pseudo_depuis_une_url():
    assert ModuleSite.pseudo_depuis_url("https://github.com/jeanmartin") == "jeanmartin"
    assert ModuleSite.pseudo_depuis_url("https://mastodon.social/@jeanmartin") == "jeanmartin"
    # Les raccourcisseurs ne désignent personne
    assert ModuleSite.pseudo_depuis_url("https://t.co/abc123") is None
    assert ModuleSite.pseudo_depuis_url("https://github.com") is None


def test_nettoyage_html_preserve_les_urls_decoupees():
    """Mastodon découpe ses liens en plusieurs balises ; insérer une espace entre
    elles casserait l'URL, donc le pivot qui en découle."""
    html = (
        '<p>Mon code : <a href="x"><span class="invisible">https://</span>'
        "<span>github.com/jeanmartin_dev</span></a></p>"
    )
    assert "https://github.com/jeanmartin_dev" in nettoyer_html(html)


def test_nettoyage_html_separe_les_blocs():
    assert nettoyer_html("<p>Ligne un</p><p>Ligne deux</p>") == "Ligne un Ligne deux"


# --- Extraction par module -------------------------------------------------


def test_github_extrait_les_champs_attendus(monkeypatch):
    faux = FauxClient(
        {
            "api.github.com/users/": {
                "login": "jeanmartin",
                "name": "Jean Martin",
                "bio": "Développeur à Lyon, écrire à contact@exemple.fr — aussi @jm_alt",
                "location": "Lyon, France",
                "company": "ACME",
                "email": "jean@exemple.fr",
                "blog": "exemple.fr",
                "twitter_username": "jm_twitter",
                "created_at": "2015-03-12T10:00:00Z",
                "followers": 42,
                "avatar_url": "https://avatars.githubusercontent.com/u/1",
            }
        }
    )
    module = ModuleGitHub()
    monkeypatch.setattr(module, "_client", lambda: faux)

    resultat = module.enrichir("https://github.com/jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    assert resultat.valeurs(TypeDonnee.NOM_AFFICHE) == ["Jean Martin"]
    assert resultat.valeurs(TypeDonnee.LOCALISATION) == ["Lyon, France"]
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
    # L'email présent dans la biographie est également récupéré
    assert "contact@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
    # Le compte X déclaré et la mention dans la bio deviennent des pseudonymes pivotables
    assert "jm_twitter" in resultat.valeurs(TypeDonnee.PSEUDO_ALT)
    assert "jm_alt" in resultat.valeurs(TypeDonnee.PSEUDO_ALT)
    # Un site personnel sans protocole doit être complété
    assert "https://exemple.fr" in resultat.valeurs(TypeDonnee.LIEN_EXTERNE)


def test_github_signale_un_profil_introuvable(monkeypatch):
    module = ModuleGitHub()
    monkeypatch.setattr(module, "_client", lambda: FauxClient({}))
    resultat = module.enrichir("https://github.com/inconnu", "inconnu")
    assert resultat.erreur is not None
    assert not resultat.informations


def test_reddit_extrait_le_nom_dutilisateur_de_lurl():
    assert ModuleReddit._identifiant("https://www.reddit.com/user/jeanmartin") == "jeanmartin"
    assert ModuleReddit._identifiant("https://reddit.com/u/jeanmartin/") == "jeanmartin"
    assert ModuleReddit._identifiant("https://reddit.com/r/france") is None


def test_mastodon_exploite_les_champs_personnalises(monkeypatch):
    faux = FauxClient(
        {
            "/api/v1/accounts/lookup": {
                "username": "jeanmartin",
                "display_name": "Jean Martin",
                "note": "<p>Développeur</p>",
                "created_at": "2016-06-01T00:00:00.000Z",
                "followers_count": 120,
                "fields": [
                    {"name": "Code", "value": '<a href="x"><span>https://</span><span>github.com/jeanmartin_dev</span></a>'},
                    {"name": "Mail", "value": "jean@exemple.fr"},
                    {"name": "Ville", "value": "Lyon"},
                ],
                "avatar_static": "https://files.mastodon.social/avatar.png",
            }
        }
    )
    module = ModuleMastodon()
    monkeypatch.setattr("app.modules.mastodon.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://mastodon.social/@jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    assert "https://github.com/jeanmartin_dev" in resultat.valeurs(TypeDonnee.LIEN_EXTERNE)
    # Le lien déclaré fournit aussi un pseudonyme exploitable pour le pivot
    assert "jeanmartin_dev" in resultat.valeurs(TypeDonnee.PSEUDO_ALT)
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
    assert "Lyon" in resultat.valeurs(TypeDonnee.LOCALISATION)


def test_valeurs_vides_ignorees():
    resultat = ResultatEnrichissement(module="test")
    for valeur in (None, "", "   ", "none", "N/A", "-"):
        resultat.ajouter(TypeDonnee.BIO, valeur)
    assert resultat.informations == []


def test_hash_perceptuel_tolere_une_image_invalide():
    assert ModuleSite.hash_perceptuel(b"ceci n'est pas une image") is None
    assert ModuleSite.hash_perceptuel(None) is None


@pytest.mark.parametrize(
    "domaine,attendu",
    [("github.com", True), ("api.github.com", True), ("gitlab.com", False), ("", False)],
)
def test_correspondance_de_domaine(domaine: str, attendu: bool):
    assert ModuleGitHub().gere(domaine) is attendu


# --- Séparation appel réseau / écriture en base -----------------------------


def test_executer_module_ne_prend_pas_de_session():
    """Garantie de conception : l'appel réseau ne doit jamais se faire dans une
    transaction ouverte, sous peine de saturer le pool de connexions PostgreSQL
    dès que plusieurs organisations enrichissent en parallèle.

    Ce test verrouille la signature : si quelqu'un réintroduit un paramètre
    `session`, il échoue et force à reconsidérer le changement.
    """
    import inspect

    from app.services.investigation import executer_module

    parametres = set(inspect.signature(executer_module).parameters)
    assert "session" not in parametres
    assert parametres == {"url_profil", "pseudo", "domaine"}


def test_executer_module_sans_module_disponible():
    from app.services.investigation import executer_module

    prepare = executer_module("https://site-sans-module.fr/jean", "jean", "site-sans-module.fr")
    assert prepare.aucun_module
    assert prepare.resultat is None


def test_executer_module_capture_les_erreurs_de_module(monkeypatch):
    """Un module qui lève une exception ne doit pas faire tomber la tâche."""
    from app.modules.registre import charger_modules
    from app.services.investigation import executer_module

    module_github = charger_modules()["github"]

    def enrichir_defaillant(*args, **kwargs):
        raise RuntimeError("panne simulée du module")

    monkeypatch.setattr(module_github, "enrichir", enrichir_defaillant)

    prepare = executer_module("https://github.com/jean", "jean", "github.com")
    assert prepare.erreur is not None
    assert "panne simulée" in prepare.erreur
    assert prepare.resultat is None
