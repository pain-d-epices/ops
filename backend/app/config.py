"""Configuration centralisée de l'application.

Deux sources distinctes, volontairement séparées :
  - .env        -> secrets et paramètres d'infrastructure (mots de passe, URLs, clés API)
  - config.yaml -> réglages métier ajustables sans redéployer (poids de scoring, seuils, quotas techniques)
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RACINE_BACKEND = Path(__file__).resolve().parent.parent
RACINE_PROJET = RACINE_BACKEND.parent

#: Clé de signature des jetons utilisée tant qu'aucune n'est fournie. Elle est publique
#: (ce dépôt est ouvert) : quiconque la connaît peut forger un jeton d'authentification.
#: Le garde-fou en bas de classe interdit donc de démarrer en production avec elle.
CLE_SECRETE_DEVELOPPEMENT = "cle_de_developpement_a_ne_jamais_utiliser_en_production"


class Parametres(BaseSettings):
    """Paramètres d'infrastructure, lus depuis les variables d'environnement (.env)."""

    model_config = SettingsConfigDict(
        env_file=(RACINE_PROJET / ".env", RACINE_BACKEND / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Général ---
    #: Mode autohébergé (par défaut) : l'instance appartient à celui qui l'installe,
    #: tout est ouvert et la facturation est inerte. Le passer à `false` rétablit les
    #: paliers payants et les quotas, pour qui veut exploiter l'outil comme un service.
    mode_autoheberge: bool = True
    environnement: str = "developpement"
    origines_autorisees: str = "http://localhost:5183"

    # --- Base de données ---
    postgres_utilisateur: str = "searcher"
    postgres_mot_de_passe: str = "searcher"
    postgres_base: str = "searcher"
    postgres_hote: str = "localhost"
    postgres_port: int = 5442
    # Renseigner cette variable court-circuite les cinq précédentes (utile pour les tests SQLite)
    url_base_de_donnees: str | None = None

    # --- Redis ---
    redis_url: str = "redis://localhost:6389/0"

    # --- Sécurité ---
    cle_secrete: str = CLE_SECRETE_DEVELOPPEMENT
    duree_jeton_acces_minutes: int = 15
    duree_jeton_rafraichissement_jours: int = 14

    # --- Stripe (facturation) ---
    # Inutile en mode autohébergé : laisser vide. Ne sert qu'à qui exploite l'outil
    # comme un service payant (MODE_AUTOHEBERGE=false). Sans ces valeurs, les routes
    # de paiement répondent une erreur explicite et le reste fonctionne normalement.
    stripe_cle_secrete: str = ""             # sk_test_... ou sk_live_...
    stripe_webhook_secret: str = ""          # whsec_..., depuis le tableau de bord Stripe
    stripe_url_retour_succes: str = "http://localhost:5183/abonnement?paiement=succes"
    stripe_url_retour_annulation: str = "http://localhost:5183/abonnement?paiement=annule"
    stripe_url_retour_portail: str = "http://localhost:5183/abonnement"
    # Correspondance entre identifiants de prix Stripe et codes de plan internes,
    # utilisée en repli si la colonne `plans.stripe_price_id` n'est pas renseignée.
    # Format : id_prix_stripe:code_plan,id_prix_stripe:code_plan
    stripe_prix: str = ""

    # --- Clés API des modules de site ---
    # Toutes facultatives, toutes gratuites, et toutes à renseigner dans VOTRE fichier
    # .env (jamais ici : ce fichier est versionné). Un module sans sa clé s'abstient
    # simplement, sans faire échouer la recherche.
    #   GITHUB_TOKEN  github.com/settings/tokens — aucune permission à cocher.
    #                 Sans lui : 60 requêtes/heure au lieu de 5000. La plus utile.
    #   REDDIT_*      reddit.com/prefs/apps, application de type « script »
    #   LASTFM_API_KEY  last.fm/api/account/create
    #   TWITCH_*      dev.twitch.tv/console/apps
    # Mode opératoire détaillé : section « Vos clés d'API » du README.
    github_token: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    lastfm_api_key: str = ""
    twitch_client_id: str = ""
    twitch_client_secret: str = ""

    # --- Chemins ---
    dossier_donnees: str = "./donnees"

    @property
    def dsn(self) -> str:
        """Chaîne de connexion SQLAlchemy vers PostgreSQL."""
        if self.url_base_de_donnees:
            return self.url_base_de_donnees
        return (
            f"postgresql+psycopg://{self.postgres_utilisateur}:{self.postgres_mot_de_passe}"
            f"@{self.postgres_hote}:{self.postgres_port}/{self.postgres_base}"
        )

    @property
    def liste_origines(self) -> list[str]:
        return [o.strip() for o in self.origines_autorisees.split(",") if o.strip()]

    @property
    def chemin_donnees(self) -> Path:
        chemin = Path(self.dossier_donnees)
        if not chemin.is_absolute():
            chemin = RACINE_BACKEND / chemin
        chemin.mkdir(parents=True, exist_ok=True)
        return chemin

    @property
    def correspondance_prix_stripe(self) -> dict[str, str]:
        """{identifiant_prix_stripe: code_plan_interne}"""
        correspondance: dict[str, str] = {}
        for paire in self.stripe_prix.split(","):
            if ":" in paire:
                prix, plan = paire.split(":", 1)
                correspondance[prix.strip()] = plan.strip()
        return correspondance

    @property
    def est_production(self) -> bool:
        return self.environnement.lower().startswith("prod")

    @model_validator(mode="after")
    def _refuser_secrets_de_developpement_en_production(self) -> Parametres:
        """Interdit de démarrer en production avec les secrets d'exemple du dépôt.

        Volontairement placé ici plutôt que dans `main.py` : l'API, les workers Celery
        et les scripts d'administration construisent tous ces paramètres, et doivent
        tous être couverts.
        """
        if not self.est_production:
            return self
        manquants = []
        if (
            self.cle_secrete == CLE_SECRETE_DEVELOPPEMENT
            or "change_moi" in self.cle_secrete.lower()
            or len(self.cle_secrete) < 32
        ):
            manquants.append("CLE_SECRETE")
        if not self.url_base_de_donnees and (
            self.postgres_mot_de_passe == "searcher"
            or "change_moi" in self.postgres_mot_de_passe.lower()
        ):
            manquants.append("POSTGRES_MOT_DE_PASSE")
        if manquants:
            raise ValueError(
                "ENVIRONNEMENT=production mais "
                + " et ".join(manquants)
                + " vaut encore une valeur d'exemple du dépôt (publique) ou est trop court. "
                "Renseigner ces variables dans .env avant de démarrer "
                '(ex. : python -c "import secrets; print(secrets.token_urlsafe(48))").'
            )
        return self


class ConfigMetier:
    """Accès en lecture au fichier config.yaml, avec chemins pointés (`correlation.seuils.eleve`)."""

    def __init__(self, donnees: dict[str, Any]):
        self._donnees = donnees

    def obtenir(self, chemin: str, defaut: Any = None) -> Any:
        courant: Any = self._donnees
        for cle in chemin.split("."):
            if not isinstance(courant, dict) or cle not in courant:
                return defaut
            courant = courant[cle]
        return courant

    def section(self, nom: str) -> dict[str, Any]:
        valeur = self.obtenir(nom, {})
        return valeur if isinstance(valeur, dict) else {}

    @property
    def brut(self) -> dict[str, Any]:
        return self._donnees


@functools.lru_cache
def parametres() -> Parametres:
    """Paramètres d'infrastructure (mis en cache : lus une seule fois par processus)."""
    return Parametres()


@functools.lru_cache
def config_metier() -> ConfigMetier:
    """Configuration métier issue de config.yaml."""
    chemin = RACINE_BACKEND / "config.yaml"
    if not chemin.exists():
        return ConfigMetier({})
    with chemin.open(encoding="utf-8") as fichier:
        return ConfigMetier(yaml.safe_load(fichier) or {})


def recharger_config_metier() -> None:
    """Vide le cache : utile en tests, ou pour recharger config.yaml sans redémarrer."""
    config_metier.cache_clear()


def surcharger_config_metier(chemin: str, valeur: Any) -> None:
    """Remplace une valeur de configuration en mémoire, pour le processus courant.

    **Prévu pour les tests automatisés**, qui doivent pouvoir désactiver une
    protection ou en durcir un seuil sans réécrire `config.yaml`.

    Agit sur l'instance mise en cache, donc sur tous les modules à la fois : c'est
    nécessaire, car ils importent `config_metier` par valeur (`from app.config import
    config_metier`) et un remplacement de l'attribut de module ne les atteindrait pas.

    `recharger_config_metier()` annule toutes les surcharges.
    """
    conf = config_metier()
    courant = conf.brut
    cles = chemin.split(".")
    for cle in cles[:-1]:
        suivant = courant.get(cle)
        if not isinstance(suivant, dict):
            suivant = {}
            courant[cle] = suivant
        courant = suivant
    courant[cles[-1]] = valeur
