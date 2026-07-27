"""Configuration de Celery.

Deux files distinctes : les recherches Maigret durent plusieurs minutes et bloquent
un worker ; les enrichissements et pivots sont courts. Les séparer évite qu'une file
de recherches longues n'empêche l'enrichissement d'avancer.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import parametres

_params = parametres()

celery_app = Celery(
    "searcher",
    broker=_params.redis_url,
    backend=_params.redis_url,
    include=[
        "app.taches.recherche",
        "app.taches.enrichissement",
        "app.taches.pivot",
        "app.taches.maintenance",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Paris",
    enable_utc=True,
    # Une tâche n'est acquittée qu'une fois terminée : si un worker meurt en cours de
    # route, la recherche est reprise au lieu d'être silencieusement perdue.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=86400,
    task_routes={
        "app.taches.recherche.*": {"queue": "recherche"},
        "app.taches.enrichissement.*": {"queue": "enrichissement"},
        "app.taches.pivot.*": {"queue": "pivot"},
        "app.taches.maintenance.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "purge-retention-quotidienne": {
            "task": "app.taches.maintenance.purger_investigations_expirees",
            "schedule": crontab(hour=3, minute=30),
        },
        "expiration-abonnements": {
            "task": "app.taches.maintenance.expirer_abonnements",
            "schedule": crontab(hour="*/6", minute=0),
        },
        "purge-journaux": {
            "task": "app.taches.maintenance.purger_journaux_anciens",
            "schedule": crontab(hour=4, minute=0, day_of_week=0),
        },
    },
)
