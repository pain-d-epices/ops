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
from pydantic_settings import BaseSettings, SettingsConfigDict

RACINE_BACKEND = Path(__file__).resolve().parent.parent
RACINE_PROJET = RACINE_BACKEND.parent


class Parametres(BaseSettings):
    """Paramètres d'infrastructure, lus depuis les variables d'environnement (.env)."""

    model_config = SettingsConfigDict(
        env_file=(RACINE_PROJET / ".env", RACINE_BACKEND / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Général ---
    environnement: str = "developpement"
    debug: bool = True
    origines_autorisees: str = "http://localhost:5173"

    # --- Base de données ---
    postgres_utilisateur: str = "searcher"
    postgres_mot_de_passe: str = "searcher"
    postgres_base: str = "searcher"
    postgres_hote: str = "localhost"
    postgres_port: int = 5432
    # Renseigner cette variable court-circuite les cinq précédentes (utile pour les tests SQLite)
    url_base_de_donnees: str | None = None

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Sécurité ---
    cle_secrete: str = "cle_de_developpement_a_ne_jamais_utiliser_en_production"
    duree_jeton_acces_minutes: int = 15
    duree_jeton_rafraichissement_jours: int = 14

    # --- Gumroad ---
    gumroad_access_token: str = ""
    gumroad_webhook_secret: str = "change_moi"
    gumroad_produits: str = ""  # "id_produit:code_plan,id_produit:code_plan"

    # --- Clés API des modules de site ---
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
    def correspondance_produits_gumroad(self) -> dict[str, str]:
        """{identifiant_produit_gumroad: code_plan_interne}"""
        correspondance: dict[str, str] = {}
        for paire in self.gumroad_produits.split(","):
            if ":" in paire:
                produit, plan = paire.split(":", 1)
                correspondance[produit.strip()] = plan.strip()
        return correspondance

    @property
    def est_production(self) -> bool:
        return self.environnement.lower().startswith("prod")


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
