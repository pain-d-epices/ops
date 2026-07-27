"""Point d'entrée de l'API Searcher."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import parametres
from app.facturation.garde import FonctionnaliteIndisponible
from app.facturation.quotas import QuotaDepasse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
journal = logging.getLogger("searcher")

DESCRIPTION = """
API de recherche et de corrélation de pseudonymes à des fins d'investigation autorisée.

**Cadre d'usage** : cet outil traite des données personnelles de tiers. Son utilisation
est réservée aux finalités légitimes et légales (enquête autorisée, journalisme
d'investigation, sécurité défensive, vérification avec consentement). Toute recherche
est journalisée avec son auteur et sa cible.
"""


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    # Chargement anticipé des règles et des modules : une erreur de configuration
    # apparaît au démarrage plutôt qu'au milieu d'une investigation client.
    from app.modules.registre import charger_modules
    from app.moteur.correlation.registre import charger_regles

    regles = charger_regles()
    modules = charger_modules()
    journal.info(
        "Searcher démarré — %d règles de corrélation, %d modules de site, environnement %s",
        len(regles), len(modules), parametres().environnement,
    )
    yield
    journal.info("Arrêt de Searcher")


app = FastAPI(
    title="Searcher — API OSINT",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=cycle_de_vie,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=parametres().liste_origines,
    allow_credentials=True,     # indispensable : l'authentification passe par cookie
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Traduction des exceptions métier en réponses HTTP explicites -----------
# Un message clair sur un quota atteint vaut mieux qu'une erreur 500 : c'est aussi
# l'occasion d'expliquer au client comment débloquer la situation.


@app.exception_handler(QuotaDepasse)
async def gerer_quota_depasse(requete: Request, exc: QuotaDepasse) -> JSONResponse:
    del requete
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": str(exc),
            "code": "quota_depasse",
            "quota": exc.nom_quota,
            "limite": exc.limite,
            "consomme": exc.consomme,
        },
    )


@app.exception_handler(FonctionnaliteIndisponible)
async def gerer_fonctionnalite_indisponible(
    requete: Request, exc: FonctionnaliteIndisponible
) -> JSONResponse:
    del requete
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "detail": str(exc),
            "code": "fonctionnalite_indisponible",
            "fonctionnalite": exc.fonctionnalite,
            "plan_actuel": exc.code_plan,
        },
    )


# --- Routes ----------------------------------------------------------------

from app.api.v1 import (  # noqa: E402 — importés après la création de l'application
    abonnement,
    auth,
    graphe,
    gumroad,
    investigations,
    organisations,
    pivots,
    profils,
    ws,
)

PREFIXE = "/api/v1"
app.include_router(auth.routeur, prefix=PREFIXE)
app.include_router(organisations.routeur, prefix=PREFIXE)
app.include_router(investigations.routeur, prefix=PREFIXE)
app.include_router(profils.routeur, prefix=PREFIXE)
app.include_router(graphe.routeur, prefix=PREFIXE)
app.include_router(pivots.routeur, prefix=PREFIXE)
app.include_router(abonnement.routeur, prefix=PREFIXE)
app.include_router(gumroad.routeur, prefix=PREFIXE)
app.include_router(ws.routeur)


@app.get("/api/sante", tags=["Service"])
def sante() -> dict:
    """Sonde de vivacité, utilisée par Docker et le superviseur de production."""
    return {"statut": "ok", "version": app.version, "environnement": parametres().environnement}


@app.get("/api/v1/modules", tags=["Service"])
def lister_modules_disponibles() -> dict:
    """Sites couverts par un module d'enrichissement (information publique)."""
    from app.modules.registre import modules_disponibles

    return {
        "modules": [
            {"nom": m.nom, "libelle": m.libelle, "domaines": m.domaines}
            for m in modules_disponibles()
        ]
    }
