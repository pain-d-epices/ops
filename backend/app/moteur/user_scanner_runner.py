"""Pilotage de `user-scanner` (licence MIT).

Cet outil teste l'existence d'un compte à partir d'une **adresse électronique** ou
d'un **pseudonyme**, en interrogeant les formulaires d'inscription et de récupération
de mot de passe de ~144 sites (e-mail) et ~220 sites (pseudonyme).

Il complète Maigret plutôt qu'il ne le remplace :

  - Maigret ne sait chercher qu'un **pseudonyme**, en construisant des URLs de profil.
  - `user-scanner` sait aussi partir d'une **adresse électronique**, ce que Maigret ne
    peut pas faire — c'est la seule voie gratuite vers cette question.

Deux garde-fous non négociables sont appliqués ici :

  1. **Jamais `--allow-loud`.** Vingt-trois modules déclenchent réellement l'envoi d'un
     courriel ou d'un SMS à la personne recherchée. Les utiliser reviendrait à prévenir
     la cible d'une investigation en cours : inacceptable, et contraire à la discrétion
     attendue de l'outil.
  2. **`--no-nsfw` par défaut.** Signaler qu'une adresse est inscrite sur un site
     pornographique est une information lourde de conséquences, et un faux positif y
     serait diffamatoire. Activable explicitement dans config.yaml pour les enquêtes
     qui le justifient.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import config_metier, parametres
from app.modeles.enums import StatutMaigret
from app.moteur.maigret_runner import ResultatSite

journal = logging.getLogger(__name__)

# Statuts renvoyés par user-scanner qui signifient « le compte existe »
STATUTS_TROUVE = {"registered", "found"}


@dataclass
class OptionsUserScanner:
    """Options d'exécution, bornées par la configuration métier."""

    timeout_par_site: int = 10
    concurrence: int = 20
    delai_entre_requetes: float = 0.0
    timeout_global: int = 600
    inclure_sites_adultes: bool = False
    categories: list[str] = field(default_factory=list)

    @classmethod
    def depuis_config(cls, **surcharges: Any) -> OptionsUserScanner:
        conf = config_metier()
        base = cls(
            timeout_par_site=int(conf.obtenir("user_scanner.timeout_par_site", 10)),
            concurrence=int(conf.obtenir("user_scanner.concurrence", 20)),
            delai_entre_requetes=float(conf.obtenir("user_scanner.delai_entre_requetes", 0)),
            timeout_global=int(conf.obtenir("user_scanner.timeout_global", 600)),
            inclure_sites_adultes=bool(conf.obtenir("user_scanner.inclure_sites_adultes", False)),
        )
        for cle, valeur in surcharges.items():
            if valeur is not None and hasattr(base, cle):
                setattr(base, cle, valeur)
        return base


@dataclass
class ResultatUserScanner:
    entree: str
    mode: str  # "email" ou "pseudo"
    sites: list[ResultatSite] = field(default_factory=list)
    nb_sites_testes: int = 0
    duree_secondes: float = 0.0
    erreur: str | None = None

    @property
    def reussie(self) -> bool:
        return self.erreur is None


class RunnerUserScanner(ABC):
    """Interface commune, pour substituer un faux runner dans les tests."""

    @abstractmethod
    def lancer(
        self, entree: str, mode: str, options: OptionsUserScanner | None = None
    ) -> ResultatUserScanner: ...


class RunnerUserScannerSousProcessus(RunnerUserScanner):
    """Implémentation réelle : lance `python -m user_scanner` et lit son rapport JSON."""

    def __init__(self, executable: str | None = None):
        self.executable = executable or sys.executable

    def _construire_commande(
        self, entree: str, mode: str, options: OptionsUserScanner, fichier_sortie: Path
    ) -> list[str]:
        commande = [
            self.executable, "-m", "user_scanner",
            "-e" if mode == "email" else "-u", entree,
            "--format", "json",
            "--output", str(fichier_sortie),
            "--timeout", str(options.timeout_par_site),
            "--concurrency", str(options.concurrence),
            # Ne conserver que les comptes existants : les « non inscrit » se comptent
            # par centaines et n'apprennent rien.
            "--only-found",
        ]

        # Voir l'explication détaillée en tête de module : ces deux options ne sont
        # jamais activées sans décision explicite.
        if not options.inclure_sites_adultes:
            commande.append("--no-nsfw")
        # `--allow-loud` n'apparaît volontairement nulle part.

        if options.delai_entre_requetes > 0:
            commande += ["--delay", str(options.delai_entre_requetes)]
        if options.categories:
            commande += ["--category", *options.categories]

        return commande

    def _environnement(self) -> dict[str, str]:
        env = os.environ.copy()
        # Même précaution que pour Maigret : la console Windows en cp1252 fait planter
        # l'outil dès qu'il écrit un caractère non représentable.
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    def lancer(
        self, entree: str, mode: str, options: OptionsUserScanner | None = None
    ) -> ResultatUserScanner:
        options = options or OptionsUserScanner.depuis_config()
        resultat = ResultatUserScanner(entree=entree, mode=mode)
        debut = time.monotonic()

        dossier = Path(tempfile.mkdtemp(prefix="userscan_", dir=str(parametres().chemin_donnees)))
        fichier_sortie = dossier / "resultats.json"
        commande = self._construire_commande(entree, mode, options, fichier_sortie)
        journal.info("Lancement de user-scanner (%s) pour « %s »", mode, entree)

        try:
            processus = subprocess.run(
                commande,
                capture_output=True,
                env=self._environnement(),
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=options.timeout_global,
                check=False,
            )
            if processus.returncode not in (0, None) and not fichier_sortie.exists():
                resultat.erreur = f"user-scanner a échoué (code {processus.returncode})."
                journal.warning("user-scanner : %s", (processus.stderr or "")[:300])

            resultat.sites = self._lire_rapport(fichier_sortie, entree, mode)
            resultat.nb_sites_testes = len(resultat.sites)

        except subprocess.TimeoutExpired:
            resultat.erreur = (
                f"Délai maximal dépassé ({options.timeout_global}s) pour user-scanner."
            )
            journal.warning("user-scanner interrompu par dépassement de délai pour « %s »", entree)
        except FileNotFoundError as exc:
            resultat.erreur = f"user-scanner introuvable : {exc}"
        except Exception as exc:  # noqa: BLE001 — ne jamais faire tomber le worker
            resultat.erreur = f"Erreur inattendue de user-scanner : {exc}"
            journal.exception("Échec de user-scanner pour « %s »", entree)
        finally:
            shutil.rmtree(dossier, ignore_errors=True)

        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        return resultat

    def _lire_rapport(self, fichier: Path, entree: str, mode: str) -> list[ResultatSite]:
        if not fichier.exists():
            return []
        try:
            donnees = json.loads(fichier.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            journal.warning("Rapport user-scanner illisible : %s", fichier)
            return []

        if not isinstance(donnees, list):
            return []

        sites: list[ResultatSite] = []
        for entree_json in donnees:
            site = self._convertir(entree_json, entree, mode)
            if site is not None:
                sites.append(site)
        return sites

    @staticmethod
    def _convertir(donnees: dict[str, Any], entree: str, mode: str) -> ResultatSite | None:
        if str(donnees.get("status", "")).lower() not in STATUTS_TROUVE:
            return None

        url = str(donnees.get("url") or "").strip()
        nom_site = str(donnees.get("site_name") or "inconnu")
        if not url:
            return None

        supplement = donnees.get("extra") or {}
        domaine = urlparse(url).netloc.lower()

        # En mode e-mail, l'outil confirme l'inscription mais ne connaît pas l'adresse
        # du profil : l'URL renvoyée n'est que celle du site. On le signale
        # explicitement pour que le moteur de corrélation ne la traite pas comme un
        # compte identifié — voir `est_similaire`.
        presence_seule = mode == "email"

        return ResultatSite(
            site_nom=nom_site,
            site_domaine=domaine,
            url=url,
            pseudo=str(donnees.get("username") or entree),
            statut=StatutMaigret.TROUVE,
            identifiants={str(cle): str(valeur) for cle, valeur in supplement.items()},
            tags=[str(donnees.get("category") or "")] if donnees.get("category") else [],
            est_similaire=presence_seule,
            brut={**donnees, "_source": "user-scanner", "_mode": mode},
        )


class RunnerUserScannerFactice(RunnerUserScanner):
    """Runner déterministe pour les tests : aucun accès réseau."""

    def __init__(self, resultats: dict[str, list[ResultatSite]] | None = None):
        self.resultats = resultats or {}
        self.appels: list[tuple[str, str]] = []

    def lancer(
        self, entree: str, mode: str, options: OptionsUserScanner | None = None
    ) -> ResultatUserScanner:
        del options
        self.appels.append((entree, mode))
        sites = self.resultats.get(entree, [])
        return ResultatUserScanner(
            entree=entree, mode=mode, sites=list(sites),
            nb_sites_testes=len(sites), duree_secondes=0.01,
        )


_runner: RunnerUserScanner | None = None


def runner_user_scanner() -> RunnerUserScanner:
    global _runner
    if _runner is None:
        _runner = RunnerUserScannerSousProcessus()
    return _runner


def definir_runner_user_scanner(nouveau: RunnerUserScanner | None) -> None:
    global _runner
    _runner = nouveau
