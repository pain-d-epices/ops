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


class FauxReponse:
    """Simule la réponse brute d'httpx, pour les modules qui lisent du texte (RSS/XML)
    plutôt que du JSON."""

    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


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

    def obtenir(self, url: str, **kwargs) -> FauxReponse:
        """Pour les modules qui lisent une réponse texte brute (flux RSS)."""
        self.urls_appelees.append(url)
        for motif, contenu in self.reponses.items():
            if motif in url:
                return FauxReponse(200, contenu)
        return FauxReponse(404, "")

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


# --- Nouveaux modules -------------------------------------------------------


def test_tous_les_modules_couvrent_les_sites_attendus():
    modules = charger_modules()
    assert {
        "github", "gitlab", "codeberg", "gitee",          # forges de code
        "reddit", "mastodon", "bluesky", "hackernews",    # réseaux et communautés
        "devto", "keybase", "mixcloud", "steam",
        "pixelfed", "peertube", "lemmy",                  # fédivers au-delà de Mastodon
        "lobsters", "wikipedia", "liberapay",             # sans clé
        "goodreads", "letterboxd",                        # via flux RSS
        "lastfm", "twitch",                               # nécessitent une clé (indisponibles en test)
    } == set(modules)


def test_classe_de_base_des_forges_non_enregistree():
    """`ModuleForgeGit` mutualise le code de Codeberg et Gitee ; ce n'est pas un
    module utilisable et il ne doit jamais apparaître dans le registre."""
    from app.modules.forge_git import ModuleForgeGit

    assert ModuleForgeGit.nom == ""
    assert ModuleForgeGit not in {type(m) for m in modules_disponibles()}


def test_bluesky_extrait_le_domaine_personnel_verifie(monkeypatch):
    """Un handle Bluesky qui n'est pas en .bsky.social est un domaine dont
    l'utilisateur a prouvé le contrôle : piste de premier ordre."""
    from app.modules.bluesky import ModuleBluesky

    faux = FauxClient(
        {
            "getProfile": {
                "handle": "jeanmartin.fr",
                "displayName": "Jean Martin",
                "description": "Développeur — contact@jeanmartin.fr",
                "createdAt": "2023-05-01T10:00:00Z",
                "followersCount": 250,
            }
        }
    )
    module = ModuleBluesky()
    monkeypatch.setattr("app.modules.bluesky.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://bsky.app/profile/jeanmartin.fr", "jeanmartin.fr")

    assert "https://jeanmartin.fr" in resultat.valeurs(TypeDonnee.LIEN_EXTERNE)
    assert "contact@jeanmartin.fr" in resultat.valeurs(TypeDonnee.EMAIL)


def test_bluesky_ignore_les_handles_par_defaut(monkeypatch):
    """Un handle en .bsky.social n'est pas un domaine personnel : ne pas le
    transformer en lien externe, ce serait un faux pivot."""
    from app.modules.bluesky import ModuleBluesky

    faux = FauxClient({"getProfile": {"handle": "jeanmartin.bsky.social", "displayName": "Jean"}})
    module = ModuleBluesky()
    monkeypatch.setattr("app.modules.bluesky.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://bsky.app/profile/jeanmartin.bsky.social", "jeanmartin")
    assert resultat.valeurs(TypeDonnee.LIEN_EXTERNE) == []


def test_devto_exploite_les_comptes_declares(monkeypatch):
    from app.modules.devto import ModuleDevTo

    faux = FauxClient(
        {
            "by_username": {
                "username": "jeanmartin",
                "name": "Jean Martin",
                "summary": "Développeur Python",
                "location": "Lyon",
                "github_username": "jm_github",
                "twitter_username": "jm_x",
                "joined_at": "2020-01-15",
            }
        }
    )
    module = ModuleDevTo()
    monkeypatch.setattr("app.modules.devto.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://dev.to/jeanmartin", "jeanmartin")
    pseudos = resultat.valeurs(TypeDonnee.PSEUDO_ALT)
    assert "jm_github" in pseudos and "jm_x" in pseudos


def test_forge_git_partage_la_meme_extraction(monkeypatch):
    """Codeberg et Gitee exposent la même API : une seule logique doit les servir."""
    from app.modules.forge_git import ModuleCodeberg, ModuleGitee

    reponse = {
        "login": "jeanmartin",
        "full_name": "Jean Martin",
        "description": "Développeur",
        "location": "Lyon",
        "email": "jean@exemple.fr",
        "website": "https://exemple.fr",
        "created": "2021-03-01T10:00:00Z",
    }

    for classe, chemin in ((ModuleCodeberg, "codeberg.org"), (ModuleGitee, "gitee.com")):
        module = classe()
        monkeypatch.setattr("app.modules.forge_git.ClientHttp", lambda *a, **k: FauxClient({"users": reponse}))
        resultat = module.enrichir(f"https://{chemin}/jeanmartin", "jeanmartin")
        assert resultat.erreur is None, f"{module.nom} en échec"
        assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
        assert resultat.valeurs(TypeDonnee.LOCALISATION) == ["Lyon"]


def test_mixcloud_assemble_ville_et_pays(monkeypatch):
    from app.modules.mixcloud import ModuleMixCloud

    faux = FauxClient(
        {
            "api.mixcloud.com": {
                "username": "jeanmartin",
                "name": "Jean Martin",
                "biog": "DJ lyonnais",
                "city": "Lyon",
                "country": "France",
                "follower_count": 42,
            }
        }
    )
    module = ModuleMixCloud()
    monkeypatch.setattr("app.modules.mixcloud.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://www.mixcloud.com/jeanmartin/", "jeanmartin")
    assert resultat.valeurs(TypeDonnee.LOCALISATION) == ["Lyon, France"]


def test_chaque_module_a_une_limite_de_debit_declaree():
    """Un module sans limite déclarée retombe sur le réglage par défaut, ce qui peut
    être trop agressif pour le site visé — ou trop lent. On vérifie que les
    domaines interrogés par nos modules sont bien tous paramétrés."""
    from app.config import config_metier

    par_domaine = config_metier().obtenir("rate_limiting.par_domaine", {})
    # Les domaines d'API réellement appelés, qui diffèrent parfois du domaine du profil
    domaines_appeles = {
        "api.github.com", "gitlab.com", "codeberg.org", "gitee.com",
        "www.reddit.com", "hacker-news.firebaseio.com", "keybase.io",
        "api.mixcloud.com", "public.api.bsky.app", "dev.to", "steamcommunity.com",
        "lobste.rs", "ws.audioscrobbler.com", "api.twitch.tv",
        "liberapay.com", "www.goodreads.com", "letterboxd.com",
    }
    manquants = domaines_appeles - set(par_domaine)
    assert not manquants, f"Limite de débit non déclarée pour : {sorted(manquants)}"


# --- Vague A : nouveaux modules (juillet 2026) ------------------------------


def test_pixelfed_reutilise_lextraction_mastodon(monkeypatch):
    """Pixelfed expose la même API que Mastodon : ModulePixelfed doit donc
    fonctionner sans code d'extraction propre."""
    from app.modules.pixelfed import ModulePixelfed

    faux = FauxClient(
        {
            "accounts/lookup": {
                "username": "jeanmartin",
                "display_name": "Jean Martin",
                "note": "Photographe. Contact : jean@exemple.fr",
                "created_at": "2022-01-01T00:00:00Z",
                "avatar": "https://pixelfed.social/avatar.png",
            }
        }
    )
    module = ModulePixelfed()
    # enrichir() est hérité de ModuleMastodon : ClientHttp y est résolu dans le
    # module où la fonction est définie, donc app.modules.mastodon.
    monkeypatch.setattr("app.modules.mastodon.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://pixelfed.social/jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)


def test_peertube_extrait_identifiant_et_bio(monkeypatch):
    from app.modules.peertube import ModulePeerTube

    assert ModulePeerTube._identifiant("https://peertube.social/accounts/jeanmartin") == "jeanmartin"
    assert ModulePeerTube._identifiant("https://peertube.social/a/jeanmartin/video-channels") == "jeanmartin"
    assert ModulePeerTube._identifiant("https://peertube.social/videos/watch/abc") is None

    faux = FauxClient(
        {
            "api/v1/accounts/": {
                "name": "jeanmartin",
                "displayName": "Jean Martin",
                "description": "Vidéaste. Contact : jean@exemple.fr",
                "createdAt": "2021-06-01T00:00:00Z",
                "followersCount": 10,
                "avatars": [{"path": "/lazy-static/avatars/x.png"}],
            }
        }
    )
    module = ModulePeerTube()
    monkeypatch.setattr("app.modules.peertube.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://peertube.social/accounts/jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
    assert resultat.valeurs(TypeDonnee.AVATAR_URL) == ["https://peertube.social/lazy-static/avatars/x.png"]


def test_lemmy_extrait_identifiant_et_bio(monkeypatch):
    from app.modules.lemmy import ModuleLemmy

    assert ModuleLemmy._identifiant("https://lemmy.world/u/jeanmartin") == "jeanmartin"
    assert ModuleLemmy._identifiant("https://lemmy.world/c/france") is None

    faux = FauxClient(
        {
            "api/v3/user": {
                "person_view": {
                    "person": {
                        "display_name": "Jean Martin",
                        "bio": "Contact : jean@exemple.fr, voir aussi @jm_alt",
                        "published": "2020-05-01T00:00:00Z",
                        "avatar": "https://lemmy.world/avatar.png",
                    }
                }
            }
        }
    )
    module = ModuleLemmy()
    monkeypatch.setattr("app.modules.lemmy.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://lemmy.world/u/jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
    assert "jm_alt" in resultat.valeurs(TypeDonnee.PSEUDO_ALT)


def test_lobsters_exploite_les_comptes_declares(monkeypatch):
    from app.modules.lobsters import ModuleLobsters

    faux = FauxClient(
        {
            "lobste.rs/u/": {
                "username": "jeanmartin",
                "about": "Développeur. Contact : jean@exemple.fr",
                "created_at": "2018-01-01T00:00:00Z",
                "github_username": "jm_github",
                "twitter_username": "jm_x",
                "avatar_url": "/avatars/jeanmartin-100.png",
            }
        }
    )
    module = ModuleLobsters()
    monkeypatch.setattr("app.modules.lobsters.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://lobste.rs/u/jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    pseudos = resultat.valeurs(TypeDonnee.PSEUDO_ALT)
    assert "jm_github" in pseudos and "jm_x" in pseudos
    # Un avatar servi en chemin relatif doit être complété avec le domaine du site
    assert resultat.valeurs(TypeDonnee.AVATAR_URL) == ["https://lobste.rs/avatars/jeanmartin-100.png"]


def test_nettoyage_wikitexte_retire_la_syntaxe():
    from app.modules.wikipedia import nettoyer_wikitexte

    texte = "{{Infobox}} Bonjour '''Jean''' voir [[Paris|la capitale]] et <br/> la suite."
    assert nettoyer_wikitexte(texte) == "Bonjour Jean voir la capitale et la suite."


def test_wikipedia_identifiant_depuis_url():
    from app.modules.wikipedia import ModuleWikipedia

    assert ModuleWikipedia._identifiant("https://fr.wikipedia.org/wiki/Utilisateur:JeanMartin") == "JeanMartin"
    assert ModuleWikipedia._identifiant("https://en.wikipedia.org/wiki/User:JeanMartin") == "JeanMartin"
    assert ModuleWikipedia._identifiant("https://fr.wikipedia.org/wiki/Paris") is None


def test_wikipedia_croise_inscription_et_page_utilisateur(monkeypatch):
    """Deux appels API distincts (liste des utilisateurs, puis contenu de la page) :
    le faux client doit distinguer les deux d'après leurs paramètres, l'URL de base
    étant identique."""
    from app.modules.wikipedia import ModuleWikipedia

    class FauxClientWikipedia:
        def obtenir_json(self, url, parametres_requete=None, **kwargs):
            parametres_requete = parametres_requete or {}
            if parametres_requete.get("action") == "query":
                return {"query": {"users": [{"name": "JeanMartin", "registration": "2015-03-12T10:00:00Z"}]}}
            if parametres_requete.get("action") == "parse":
                return {
                    "parse": {
                        "wikitext": {
                            "*": "Bonjour, je suis [[Jean Martin]]. Contact : jean@exemple.fr. "
                            "Voir aussi https://exemple.fr et @jm_alt."
                        }
                    }
                }
            return None

    module = ModuleWikipedia()
    monkeypatch.setattr("app.modules.wikipedia.ClientHttp", lambda *a, **k: FauxClientWikipedia())

    resultat = module.enrichir("https://fr.wikipedia.org/wiki/Utilisateur:JeanMartin", "JeanMartin")

    assert resultat.erreur is None
    assert resultat.valeurs(TypeDonnee.DATE_CREATION) == ["2015-03-12T10:00:00Z"]
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
    assert "https://exemple.fr" in resultat.valeurs(TypeDonnee.LIEN_EXTERNE)
    assert "jm_alt" in resultat.valeurs(TypeDonnee.PSEUDO_ALT)


def test_wikipedia_signale_un_compte_introuvable(monkeypatch):
    from app.modules.wikipedia import ModuleWikipedia

    class FauxClientWikipedia:
        def obtenir_json(self, url, parametres_requete=None, **kwargs):
            return {"query": {"users": [{"name": "Inconnu", "missing": ""}]}}

    module = ModuleWikipedia()
    monkeypatch.setattr("app.modules.wikipedia.ClientHttp", lambda *a, **k: FauxClientWikipedia())

    resultat = module.enrichir("https://en.wikipedia.org/wiki/User:Inconnu", "Inconnu")
    assert resultat.erreur is not None


def test_lastfm_extrait_le_nom_reel_et_le_pays(monkeypatch):
    from app.modules.lastfm import ModuleLastFm

    class FauxParametresLastFm:
        lastfm_api_key = "clef-test"

    monkeypatch.setattr("app.modules.lastfm.parametres", lambda: FauxParametresLastFm())

    faux = FauxClient(
        {
            "audioscrobbler.com": {
                "user": {
                    "realname": "Jean Martin",
                    "country": "France",
                    "registered": {"unixtime": "1420070400"},
                    "image": [
                        {"size": "small", "#text": "https://x/small.png"},
                        {"size": "extralarge", "#text": "https://x/large.png"},
                    ],
                }
            }
        }
    )
    module = ModuleLastFm()
    monkeypatch.setattr("app.modules.lastfm.ClientHttp", lambda *a, **k: faux)

    assert module.disponible() is True
    resultat = module.enrichir("https://www.last.fm/user/jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    assert resultat.valeurs(TypeDonnee.NOM_REEL) == ["Jean Martin"]
    assert resultat.valeurs(TypeDonnee.LOCALISATION) == ["France"]
    assert resultat.valeurs(TypeDonnee.AVATAR_URL) == ["https://x/large.png"]


def test_lastfm_indisponible_sans_cle(monkeypatch):
    from app.modules.lastfm import ModuleLastFm

    class FauxParametresLastFm:
        lastfm_api_key = ""

    monkeypatch.setattr("app.modules.lastfm.parametres", lambda: FauxParametresLastFm())
    assert ModuleLastFm().disponible() is False


def test_twitch_extrait_le_profil(monkeypatch):
    from app.modules import twitch as module_twitch

    class FauxParametresTwitch:
        twitch_client_id = "id-test"
        twitch_client_secret = "secret-test"

    monkeypatch.setattr(module_twitch, "_jeton_application", lambda: "jeton-test")
    monkeypatch.setattr(module_twitch, "parametres", lambda: FauxParametresTwitch())

    faux = FauxClient(
        {
            "helix/users": {
                "data": [
                    {
                        "display_name": "JeanMartin",
                        "description": "Streaming. Contact : jean@exemple.fr",
                        "created_at": "2019-01-01T00:00:00Z",
                        "profile_image_url": "https://x/avatar.png",
                    }
                ]
            }
        }
    )
    monkeypatch.setattr(module_twitch, "ClientHttp", lambda *a, **k: faux)

    resultat = module_twitch.ModuleTwitch().enrichir("https://twitch.tv/jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)


def test_twitch_indisponible_sans_cle(monkeypatch):
    from app.modules import twitch as module_twitch

    class FauxParametresTwitch:
        twitch_client_id = ""
        twitch_client_secret = ""

    monkeypatch.setattr(module_twitch, "parametres", lambda: FauxParametresTwitch())
    assert module_twitch.ModuleTwitch().disponible() is False


def test_liberapay_confirme_le_compte_et_lavatar(monkeypatch):
    from app.modules.liberapay import ModuleLiberapay

    faux = FauxClient(
        {
            "liberapay.com/jeanmartin/public.json": {
                "username": "jeanmartin",
                "avatar_url": "https://seccdn.libravatar.org/avatar/x",
                "npatrons": 12,
            }
        }
    )
    module = ModuleLiberapay()
    monkeypatch.setattr("app.modules.liberapay.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://liberapay.com/jeanmartin/", "jeanmartin")

    assert resultat.erreur is None
    assert resultat.valeurs(TypeDonnee.NB_ABONNES) == ["12"]


def test_goodreads_identifiant_numerique_depuis_url():
    from app.modules.goodreads import ModuleGoodreads

    assert (
        ModuleGoodreads._identifiant_numerique("https://www.goodreads.com/user/show/12345678-jean-martin")
        == "12345678"
    )
    assert ModuleGoodreads._identifiant_numerique("https://www.goodreads.com/user/show/jeanmartin") is None


def test_goodreads_scanne_le_flux_rss(monkeypatch):
    from app.modules.goodreads import ModuleGoodreads

    flux = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss version=\"2.0\"><channel>"
        "<title>Etagere de lecture de Jean Martin</title>"
        "<description>Contact : jean@exemple.fr</description>"
        "<item><title>Un livre par @jm_alt</title></item>"
        "</channel></rss>"
    )
    faux = FauxClient({"list_rss/12345678": flux})
    module = ModuleGoodreads()
    monkeypatch.setattr("app.modules.goodreads.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://www.goodreads.com/user/show/12345678-jean-martin", "jean-martin")

    assert resultat.erreur is None
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
    assert "jm_alt" in resultat.valeurs(TypeDonnee.PSEUDO_ALT)


def test_goodreads_signale_etagere_introuvable(monkeypatch):
    from app.modules.goodreads import ModuleGoodreads

    module = ModuleGoodreads()
    monkeypatch.setattr("app.modules.goodreads.ClientHttp", lambda *a, **k: FauxClient({}))

    resultat = module.enrichir("https://www.goodreads.com/user/show/999999-x", "x")
    assert resultat.erreur is not None


def test_letterboxd_scanne_le_journal_rss(monkeypatch):
    from app.modules.letterboxd import ModuleLetterboxd

    flux = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss version=\"2.0\"><channel>"
        "<title>Journal Letterboxd de Jean Martin</title>"
        "<description>Cinephile. jean@exemple.fr</description>"
        "<item><description>&lt;p&gt;Superbe film, merci @jm_alt !&lt;/p&gt;</description></item>"
        "</channel></rss>"
    )
    faux = FauxClient({"letterboxd.com/jeanmartin/rss": flux})
    module = ModuleLetterboxd()
    monkeypatch.setattr("app.modules.letterboxd.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://letterboxd.com/jeanmartin/", "jeanmartin")

    assert resultat.erreur is None
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
    assert "jm_alt" in resultat.valeurs(TypeDonnee.PSEUDO_ALT)


def test_letterboxd_signale_journal_introuvable(monkeypatch):
    from app.modules.letterboxd import ModuleLetterboxd

    module = ModuleLetterboxd()
    monkeypatch.setattr("app.modules.letterboxd.ClientHttp", lambda *a, **k: FauxClient({}))

    resultat = module.enrichir("https://letterboxd.com/inconnu/", "inconnu")
    assert resultat.erreur is not None
