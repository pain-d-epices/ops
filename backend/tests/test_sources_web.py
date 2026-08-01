"""Tests des sources complémentaires : recherche web (DuckDuckGo) et dark web (Ahmia).

Aucun accès réseau : les réponses HTTP sont simulées. Un test qui interroge les
vrais services échouerait un jour de panne ou de changement de gabarit HTML, pour une
raison sans rapport avec notre code — Ahmia en particulier est connu pour son
instabilité (voir le commentaire en tête de `app/moteur/sources/ahmia.py`).
"""

from __future__ import annotations

from app.config import recharger_config_metier, surcharger_config_metier
from app.moteur.sources.ahmia import SourceRechercheDarkWeb, _url_onion
from app.moteur.sources.base import ResultatSource, SourceComplementaire
from app.moteur.sources.duckduckgo import SourceRechercheWeb, _url_cible
from app.moteur.sources.registre import charger_sources, sources_disponibles


class FauxReponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class FauxClientParURL:
    """Simule `ClientHttp.obtenir` : une réponse par URL exacte (avant paramètres)."""

    def __init__(self, reponses: dict[str, FauxReponse]):
        self.reponses = reponses
        self.appels: list[str] = []

    def obtenir(self, url: str, **kwargs) -> FauxReponse:
        self.appels.append(url)
        return self.reponses.get(url, FauxReponse(404, ""))


# --- Registre ----------------------------------------------------------------


def test_les_deux_sources_sont_decouvertes():
    sources = charger_sources()
    assert set(sources) == {"recherche_web", "recherche_darkweb"}


def test_toutes_les_sources_declarent_nom_et_categorie():
    for source in sources_disponibles():
        assert isinstance(source, SourceComplementaire)
        assert source.nom
        assert source.libelle
        assert source.categorie in {"web", "dark_web"}


# --- DuckDuckGo ----------------------------------------------------------------

HTML_DUCKDUCKGO = """
<html><body>
<table>
<tr><td>1.</td><td>
  <a rel="nofollow" class="result-link"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fjeanmartin&amp;rut=abc">
     Jean Martin - GitHub</a>
</td></tr>
<tr><td>&nbsp;</td><td class="result-snippet">Profil <b>jeanmartin</b> sur GitHub.</td></tr>
<tr><td>2.</td><td>
  <a rel="nofollow" class="result-link"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FSomething&amp;rut=def">
     Sans rapport - Wikipedia</a>
</td></tr>
<tr><td>&nbsp;</td><td class="result-snippet">Rien à voir.</td></tr>
<tr><td>3.</td><td>
  <a rel="nofollow" class="result-link"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgitlab.com%2Fjeanmartin&amp;rut=ghi">
     jeanmartin - GitLab</a>
</td></tr>
<tr><td>&nbsp;</td><td class="result-snippet">Profil GitLab.</td></tr>
</table>
</body></html>
"""


def test_url_cible_decode_le_lien_de_redirection():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fjeanmartin&rut=abc"
    assert _url_cible(href) == "https://github.com/jeanmartin"


def test_url_cible_sans_parametre_renvoie_none():
    assert _url_cible("//duckduckgo.com/l/?rut=abc") is None


def test_recherche_web_ne_retient_que_les_pages_de_profil(monkeypatch):
    """Une page *au sujet de* quelqu'un n'est pas un compte lui appartenant.

    Mesure réelle ayant motivé ce filtre : sur une recherche « torvalds », 10 des 11
    résultats web étaient des articles (Britannica, ZDNet, Wikipédia, Google Scholar),
    enregistrés comme autant de faux comptes dans la liste de profils.
    """
    faux = FauxClientParURL(
        {"https://lite.duckduckgo.com/lite/": FauxReponse(200, HTML_DUCKDUCKGO)}
    )
    monkeypatch.setattr("app.moteur.sources.duckduckgo.ClientHttp", lambda *a, **k: faux)

    resultat = SourceRechercheWeb().rechercher("jeanmartin")

    assert resultat.reussie
    # Les trois résultats bruts sont bien vus…
    assert resultat.nb_resultats_bruts == 3
    urls = {site.url for site in resultat.sites}
    # …mais seules les deux pages de profil sont retenues ; la page encyclopédique
    # « en.wikipedia.org/wiki/Something » est écartée.
    assert urls == {"https://github.com/jeanmartin", "https://gitlab.com/jeanmartin"}

    site = next(s for s in resultat.sites if "github" in s.url)
    assert site.site_domaine == "github.com"
    assert site.tags == ["recherche_web"]
    # Signal plus faible qu'une URL de profil connue d'avance : traité comme une
    # correspondance approximative par le moteur de corrélation.
    assert site.est_similaire is True
    # La provenance doit rester lisible en aval : sans elle, impossible de distinguer
    # un compte trouvé par Maigret d'un compte trouvé par la recherche web.
    assert site.brut["_source"] == "duckduckgo"


def test_recherche_web_ecarte_une_page_au_sujet_de_la_personne(monkeypatch):
    """Cas réels relevés en production : ces adresses ne doivent jamais passer."""
    from app.moteur.sources.base import url_de_profil_plausible

    for url in (
        "https://en.wikipedia.org/wiki/Linus_Torvalds",
        "https://www.britannica.com/biography/Linus-Torvalds",
        "https://www.zdnet.com/article/open-source-summit-linus-torvalds/",
        "https://scholar.google.com/scholar?hl=en&q=torvalds",
        "https://stackoverflow.com/users/filter?search=torvalds",
        "https://grokipedia.com/page/Linus_Torvalds",
    ):
        assert not url_de_profil_plausible(url, "torvalds"), url

    # …et le vrai profil, lui, doit passer.
    assert url_de_profil_plausible("https://github.com/torvalds/linux", "torvalds")


def test_cle_url_neutralise_le_prefixe_www():
    """Maigret renvoie « www.github.com », la recherche web « github.com » : sans
    normalisation, le même compte apparaissait deux fois dans les résultats."""
    from app.moteur.sources.base import cle_url

    assert cle_url("https://www.github.com/torvalds") == cle_url("https://github.com/torvalds/")
    assert cle_url("https://github.com/torvalds") != cle_url("https://gitlab.com/torvalds")


def test_cle_compte_identifie_le_compte_et_non_la_page():
    """Cas réel du 01/08/2026 : Maigret trouve `www.github.com/torvalds` (le profil)
    et la recherche web `github.com/torvalds/linux` (un dépôt de ce profil). Deux
    adresses, un seul compte — sans cette clé, il apparaissait deux fois."""
    from app.moteur.sources.base import cle_compte

    assert cle_compte("https://www.github.com/torvalds") == cle_compte(
        "https://github.com/torvalds/linux"
    )
    # Un sous-domaine reste un service distinct, donc un compte distinct.
    assert cle_compte("https://gist.github.com/torvalds") != cle_compte(
        "https://github.com/torvalds"
    )
    # Deux personnes différentes sur le même site restent distinctes.
    assert cle_compte("https://github.com/torvalds") != cle_compte("https://github.com/soxoj")


def test_recherche_web_respecte_la_limite_configuree(monkeypatch):
    faux = FauxClientParURL(
        {"https://lite.duckduckgo.com/lite/": FauxReponse(200, HTML_DUCKDUCKGO)}
    )
    monkeypatch.setattr("app.moteur.sources.duckduckgo.ClientHttp", lambda *a, **k: faux)
    surcharger_config_metier("recherche_web.nb_resultats_max", 1)
    try:
        resultat = SourceRechercheWeb().rechercher("jeanmartin")
    finally:
        recharger_config_metier()

    assert resultat.nb_resultats_bruts == 3  # le brut reste le total constaté
    # Deux profils étaient éligibles ; la limite en retient un seul.
    assert len(resultat.sites) == 1


def test_recherche_web_page_indisponible_ne_leve_pas(monkeypatch):
    faux = FauxClientParURL({"https://lite.duckduckgo.com/lite/": FauxReponse(503, "")})
    monkeypatch.setattr("app.moteur.sources.duckduckgo.ClientHttp", lambda *a, **k: faux)

    resultat = SourceRechercheWeb().rechercher("jeanmartin")

    assert not resultat.reussie
    assert resultat.sites == []


# --- Ahmia -----------------------------------------------------------------

HTML_ACCUEIL_AHMIA = """
<html><body>
<form id="searchForm" action="/search/" method="get">
  <input id="id_q" type="search" name="q">
  <input type="hidden" name="833aed" value="f09bb7">
  <input type="submit" value="Search">
</form>
</body></html>
"""

ONION = "juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"

HTML_RESULTATS_AHMIA = f"""
<html><body>
<ol class="searchResults">
  <li class="result">
    <h4><a href="/search/redirect?search_term=jeanmartin&redirect_url=http%3A%2F%2F{ONION}%2Fprofil%2Fjeanmartin">
      Profil de jeanmartin</a></h4>
    <p>Un extrait mentionnant jeanmartin sur ce service caché.</p>
    <cite>{ONION}</cite>
  </li>
  <li class="result">
    <h4><a href="/search/redirect?search_term=jeanmartin&redirect_url=https%3A%2F%2Fexemple-clearnet.fr%2Fpage">
      Lien suspect hors Tor</a></h4>
    <p>Ne doit jamais être retenu : ce n'est pas une adresse .onion.</p>
    <cite>exemple-clearnet.fr</cite>
  </li>
</ol>
</body></html>
"""


def test_url_onion_accepte_une_adresse_onion_valide():
    href = f"/search/redirect?redirect_url=http%3A%2F%2F{ONION}%2Fprofil"
    assert _url_onion(href) == f"http://{ONION}/profil"


def test_url_onion_rejette_une_url_clearnet():
    """Protection contre un gabarit changé ou une page compromise qui glisserait un
    lien hors du réseau Tor parmi les résultats."""
    href = "/search/redirect?redirect_url=https%3A%2F%2Fexemple.fr%2Fpage"
    assert _url_onion(href) is None


def test_recherche_darkweb_extrait_les_resultats_et_filtre_le_hors_onion(monkeypatch):
    faux = FauxClientParURL(
        {
            "https://ahmia.fi/": FauxReponse(200, HTML_ACCUEIL_AHMIA),
            "https://ahmia.fi/search/": FauxReponse(200, HTML_RESULTATS_AHMIA),
        }
    )
    monkeypatch.setattr("app.moteur.sources.ahmia.ClientHttp", lambda *a, **k: faux)

    resultat = SourceRechercheDarkWeb().rechercher("jeanmartin")

    assert resultat.reussie
    assert resultat.nb_resultats_bruts == 2
    # Le lien clearnet glissé dans la page de résultats est écarté : une seule
    # adresse .onion valide subsiste.
    assert len(resultat.sites) == 1
    site = resultat.sites[0]
    assert site.site_domaine == ONION
    assert site.tags == ["dark_web"]
    assert site.est_similaire is True


def test_recherche_darkweb_transmet_le_jeton_lu_sur_laccueil(monkeypatch):
    captures: dict[str, dict] = {}

    class ClientCapturant(FauxClientParURL):
        def obtenir(self, url: str, **kwargs):
            if "parametres_requete" in kwargs:
                captures["parametres"] = kwargs["parametres_requete"]
            return super().obtenir(url, **kwargs)

    faux = ClientCapturant(
        {
            "https://ahmia.fi/": FauxReponse(200, HTML_ACCUEIL_AHMIA),
            "https://ahmia.fi/search/": FauxReponse(200, HTML_RESULTATS_AHMIA),
        }
    )
    monkeypatch.setattr("app.moteur.sources.ahmia.ClientHttp", lambda *a, **k: faux)

    SourceRechercheDarkWeb().rechercher("jeanmartin")

    assert captures["parametres"] == {"q": "jeanmartin", "833aed": "f09bb7"}


def test_recherche_darkweb_accueil_indisponible_ne_leve_pas(monkeypatch):
    faux = FauxClientParURL({"https://ahmia.fi/": FauxReponse(504, "")})
    monkeypatch.setattr("app.moteur.sources.ahmia.ClientHttp", lambda *a, **k: faux)

    resultat = SourceRechercheDarkWeb().rechercher("jeanmartin")

    assert not resultat.reussie
    assert resultat.sites == []


def test_resultat_source_par_defaut_est_reussi():
    assert ResultatSource(source="x").reussie is True
    assert ResultatSource(source="x", erreur="panne").reussie is False
