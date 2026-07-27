"""Pilotage de Maigret.

Maigret est appelé en **sous-processus** plutôt qu'en librairie : ses dépendances
(aiohttp, résolveur DNS, base de sites auto-mise à jour) sont lourdes et son API
interne n'est pas stable entre versions. Un sous-processus isole ces risques et
permet d'imposer un délai maximal strict.

Deux options de ligne de commande conditionnent directement le modèle commercial :

  --no-recursion   TOUJOURS activé. Sans lui, Maigret relance de lui-même des
                   recherches sur les pseudonymes qu'il découvre — c'est-à-dire
                   qu'il pivote. Le pivot étant une fonctionnalité payante pilotée
                   par notre propre orchestrateur, le laisser faire reviendrait à
                   offrir la fonctionnalité au palier gratuit et à rendre la
                   profondeur de recherche incontrôlable.

  --no-extracting  activé pour les plans SANS la fonctionnalité « modules ».
                   L'extraction fournit gratuitement bio, avatar et identifiants
                   annexes, ce qui recouvre la fonctionnalité 3 du produit.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import config_metier, parametres
from app.modeles.enums import StatutMaigret

journal = logging.getLogger(__name__)

# Correspondance entre les statuts de Maigret et les nôtres
CORRESPONDANCE_STATUTS = {
    "claimed": StatutMaigret.TROUVE,
    "available": StatutMaigret.ABSENT,
    "unknown": StatutMaigret.ERREUR,
    "illegal": StatutMaigret.ERREUR,
}

# Extrait « 123/456 » de la barre de progression écrite par Maigret sur la sortie d'erreur
MOTIF_PROGRESSION = re.compile(r"(\d+)\s*/\s*(\d+)")


@dataclass
class ResultatSite:
    """Un compte trouvé sur un site."""

    site_nom: str
    site_domaine: str
    url: str
    pseudo: str
    statut: StatutMaigret
    # Informations extraites par Maigret lui-même (uid, image, date de création...).
    # Absentes quand l'extraction est désactivée (palier gratuit).
    identifiants: dict[str, Any] = field(default_factory=dict)
    pseudos_annexes: dict[str, str] = field(default_factory=dict)
    liens_annexes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    rang_alexa: int | None = None
    # Vrai si Maigret a trouvé ce compte par recherche approximative et non par URL
    # exacte : source majeure de faux positifs, exploitée par le moteur de corrélation.
    est_similaire: bool = False
    code_http: int | None = None
    brut: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptionsRecherche:
    """Options d'une exécution, déjà bornées par le plan de l'organisation."""

    top_sites: int = 500
    timeout_par_site: int = 20
    timeout_global: int = 900
    concurrence: int = 10
    sites_exclus: list[str] = field(default_factory=list)
    # Piloté par le plan : l'extraction d'informations complémentaires relève de la
    # fonctionnalité payante « modules ».
    extraction_activee: bool = False
    tous_les_sites: bool = False

    @classmethod
    def depuis_config(cls, **surcharges: Any) -> OptionsRecherche:
        conf = config_metier()
        base = cls(
            top_sites=int(conf.obtenir("maigret.top_sites", 500)),
            timeout_par_site=int(conf.obtenir("maigret.timeout_par_site", 20)),
            timeout_global=int(conf.obtenir("maigret.timeout_global", 900)),
            concurrence=int(conf.obtenir("maigret.concurrence", 10)),
        )
        for cle, valeur in surcharges.items():
            if valeur is not None and hasattr(base, cle):
                setattr(base, cle, valeur)
        return base


@dataclass
class ResultatRecherche:
    pseudo: str
    sites: list[ResultatSite] = field(default_factory=list)
    nb_sites_total: int = 0
    nb_sites_scannes: int = 0
    duree_secondes: float = 0.0
    erreur: str | None = None
    code_retour: int | None = None

    @property
    def reussie(self) -> bool:
        return self.erreur is None

    @property
    def comptes_trouves(self) -> list[ResultatSite]:
        return [s for s in self.sites if s.statut == StatutMaigret.TROUVE]


# Signature du rappel de progression : (sites_scannes, sites_total, message)
RappelProgression = Callable[[int, int, str], None]


class RunnerMaigret(ABC):
    """Interface commune, pour pouvoir substituer un faux runner dans les tests."""

    @abstractmethod
    def lancer(
        self,
        pseudo: str,
        options: OptionsRecherche | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatRecherche: ...


class RunnerMaigretSousProcessus(RunnerMaigret):
    """Implémentation réelle : lance `python -m maigret` et lit son rapport ndjson."""

    def __init__(self, executable: str | None = None):
        self.executable = executable or sys.executable

    def _construire_commande(self, pseudo: str, options: OptionsRecherche, dossier: Path) -> list[str]:
        commande = [
            self.executable, "-m", "maigret", pseudo,
            "--timeout", str(options.timeout_par_site),
            "--max-connections", str(options.concurrence),
            "--no-color",
            "--json", "ndjson",
            "--folderoutput", str(dossier),
            # Voir l'explication détaillée en tête de module : jamais de récursion
            # automatique, le pivot est piloté par notre orchestrateur.
            "--no-recursion",
            # Évite un téléchargement de la base de sites à chaque exécution ; la mise
            # à jour est faite par une tâche planifiée, pas dans le chemin critique.
            "--no-autoupdate",
        ]
        if options.tous_les_sites:
            commande.append("--all-sites")
        else:
            commande += ["--top-sites", str(options.top_sites)]

        if not options.extraction_activee:
            commande.append("--no-extracting")

        # Maigret n'offre pas d'option d'exclusion de sites (`--site` ne fait que
        # restreindre à une liste). Les sites exclus par l'utilisateur sont donc
        # filtrés après lecture du rapport, dans `_lire_rapports`.
        return commande

    def _environnement(self) -> dict[str, str]:
        env = os.environ.copy()
        # Sans cela, Maigret plante sur Windows en écrivant sa bannière (caractère ♥
        # non représentable en cp1252). Sans effet sur Linux, où l'UTF-8 est déjà par défaut.
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    def lancer(
        self,
        pseudo: str,
        options: OptionsRecherche | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatRecherche:
        options = options or OptionsRecherche.depuis_config()
        resultat = ResultatRecherche(pseudo=pseudo)
        debut = time.monotonic()

        dossier_sortie = Path(tempfile.mkdtemp(prefix="maigret_", dir=str(parametres().chemin_donnees)))
        commande = self._construire_commande(pseudo, options, dossier_sortie)
        journal.info("Lancement de Maigret pour « %s » (%d sites)", pseudo, options.top_sites)

        try:
            processus = subprocess.Popen(
                commande,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._environnement(),
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            suiveur = threading.Thread(
                target=self._suivre_progression,
                args=(processus, resultat, rappel),
                daemon=True,
            )
            suiveur.start()

            try:
                processus.communicate(timeout=options.timeout_global)
            except subprocess.TimeoutExpired:
                processus.kill()
                processus.communicate()
                resultat.erreur = (
                    f"Délai maximal dépassé ({options.timeout_global}s). "
                    "Les résultats partiels obtenus sont conservés."
                )
                journal.warning("Maigret interrompu par dépassement de délai pour « %s »", pseudo)

            resultat.code_retour = processus.returncode
            suiveur.join(timeout=2)

            # Le code de retour de Maigret n'est pas fiable (il renvoie parfois une
            # valeur non nulle malgré une recherche complète). C'est la présence du
            # rapport qui fait foi.
            sites = self._lire_rapports(dossier_sortie, pseudo)
            resultat.sites = self._filtrer_exclusions(sites, options.sites_exclus)
            if not sites and resultat.erreur is None and processus.returncode not in (0, None):
                resultat.erreur = f"Maigret a échoué (code {processus.returncode})."

        except FileNotFoundError as exc:
            resultat.erreur = f"Maigret introuvable : {exc}"
            journal.exception("Maigret introuvable")
        except Exception as exc:  # noqa: BLE001 — on ne veut jamais faire tomber le worker
            resultat.erreur = f"Erreur inattendue pendant la recherche : {exc}"
            journal.exception("Échec de la recherche Maigret pour « %s »", pseudo)
        finally:
            shutil.rmtree(dossier_sortie, ignore_errors=True)

        resultat.duree_secondes = round(time.monotonic() - debut, 2)
        if resultat.nb_sites_total == 0:
            resultat.nb_sites_total = options.top_sites
        resultat.nb_sites_scannes = max(resultat.nb_sites_scannes, len(resultat.sites))
        return resultat

    def _suivre_progression(
        self,
        processus: subprocess.Popen,
        resultat: ResultatRecherche,
        rappel: RappelProgression | None,
    ) -> None:
        """Lit la sortie d'erreur pour alimenter la progression.

        La barre de progression de Maigret utilise des retours chariot (\\r) et non des
        sauts de ligne : une lecture ligne par ligne bloquerait. On lit donc par blocs.
        Si le format change, la progression se dégrade sans faire échouer la recherche.
        """
        if processus.stderr is None:
            return
        tampon = ""
        try:
            while True:
                morceau = processus.stderr.read(256)
                if not morceau:
                    break
                tampon += morceau
                segments = re.split(r"[\r\n]", tampon)
                tampon = segments.pop()
                for segment in segments:
                    correspondance = MOTIF_PROGRESSION.search(segment)
                    if not correspondance:
                        continue
                    scannes, total = int(correspondance.group(1)), int(correspondance.group(2))
                    if total <= 0 or scannes > total:
                        continue
                    resultat.nb_sites_scannes = scannes
                    resultat.nb_sites_total = total
                    if rappel:
                        try:
                            rappel(scannes, total, f"{scannes}/{total} sites analysés")
                        except Exception:  # noqa: BLE001 — un rappel défaillant ne doit rien casser
                            journal.debug("Rappel de progression en échec", exc_info=True)
        except Exception:  # noqa: BLE001
            journal.debug("Suivi de progression interrompu", exc_info=True)

    def _lire_rapports(self, dossier: Path, pseudo: str) -> list[ResultatSite]:
        """Lit tous les rapports ndjson produits dans le dossier temporaire.

        Le nom du fichier est dérivé du pseudonyme et peut contenir des espaces ; on
        parcourt donc tout le dossier plutôt que de reconstruire le nom attendu.
        """
        sites: list[ResultatSite] = []
        for fichier in dossier.glob("*.json"):
            try:
                contenu = fichier.read_text(encoding="utf-8", errors="replace")
            except OSError:
                journal.warning("Rapport illisible : %s", fichier)
                continue

            for ligne in contenu.splitlines():
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    donnees = json.loads(ligne)
                except json.JSONDecodeError:
                    journal.debug("Ligne ndjson ignorée (JSON invalide)")
                    continue
                site = self._convertir(donnees, pseudo)
                if site is not None:
                    sites.append(site)
        return sites

    @staticmethod
    def _filtrer_exclusions(sites: list[ResultatSite], exclusions: list[str]) -> list[ResultatSite]:
        """Écarte les sites exclus par l'utilisateur (comparaison sur le nom et le domaine)."""
        if not exclusions:
            return sites
        exclus = {e.strip().lower() for e in exclusions if e.strip()}
        return [
            site
            for site in sites
            if site.site_nom.lower() not in exclus and site.site_domaine.lower() not in exclus
        ]

    @staticmethod
    def _convertir(donnees: dict[str, Any], pseudo_demande: str) -> ResultatSite | None:
        statut_brut = (donnees.get("status") or {}).get("status", "")
        statut = CORRESPONDANCE_STATUTS.get(str(statut_brut).lower(), StatutMaigret.ERREUR)
        # Le rapport ndjson ne contient que des comptes existants ; on écarte le reste
        # par précaution si le format venait à changer.
        if statut != StatutMaigret.TROUVE:
            return None

        url = donnees.get("url_user") or (donnees.get("status") or {}).get("url") or ""
        if not url:
            return None

        nom_site = donnees.get("sitename") or (donnees.get("status") or {}).get("site_name") or "inconnu"
        info_site = donnees.get("site") or {}
        domaine = urlparse(donnees.get("url_main") or info_site.get("urlMain") or url).netloc.lower()

        identifiants = dict((donnees.get("status") or {}).get("ids") or {})
        identifiants.pop("_extractor", None)

        return ResultatSite(
            site_nom=str(nom_site),
            site_domaine=domaine,
            url=str(url),
            pseudo=str(donnees.get("username") or pseudo_demande),
            statut=statut,
            identifiants=identifiants,
            pseudos_annexes=dict(donnees.get("ids_usernames") or {}),
            liens_annexes=list(donnees.get("ids_links") or []),
            tags=list((donnees.get("status") or {}).get("tags") or info_site.get("tags") or []),
            rang_alexa=donnees.get("rank") or info_site.get("alexaRank"),
            est_similaire=bool(donnees.get("is_similar")),
            code_http=donnees.get("http_status"),
            brut=donnees,
        )


class RunnerMaigretFactice(RunnerMaigret):
    """Runner déterministe pour les tests : aucun accès réseau."""

    def __init__(self, resultats: dict[str, list[ResultatSite]] | None = None, duree: float = 0.01):
        self.resultats = resultats or {}
        self.duree = duree
        self.appels: list[str] = []

    def lancer(
        self,
        pseudo: str,
        options: OptionsRecherche | None = None,
        rappel: RappelProgression | None = None,
    ) -> ResultatRecherche:
        self.appels.append(pseudo)
        sites = self.resultats.get(pseudo, [])
        if rappel:
            rappel(len(sites), max(len(sites), 1), "recherche factice terminée")
        return ResultatRecherche(
            pseudo=pseudo,
            sites=list(sites),
            nb_sites_total=max(len(sites), 1),
            nb_sites_scannes=max(len(sites), 1),
            duree_secondes=self.duree,
            code_retour=0,
        )


_runner_par_defaut: RunnerMaigret | None = None


def runner() -> RunnerMaigret:
    """Runner partagé par l'application (remplaçable dans les tests)."""
    global _runner_par_defaut
    if _runner_par_defaut is None:
        _runner_par_defaut = RunnerMaigretSousProcessus()
    return _runner_par_defaut


def definir_runner(nouveau: RunnerMaigret | None) -> None:
    global _runner_par_defaut
    _runner_par_defaut = nouveau
