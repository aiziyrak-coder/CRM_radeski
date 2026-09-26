from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "radeski_crm",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.jobs"],
)
celery_app.conf.update(
    timezone=settings.tz,
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # ARXITEKTURA 4.1 — times are clinic local (Asia/Tashkent)
    beat_schedule={
        "confirmations-0730": {
            "task": "jobs.confirmations",
            "schedule": crontab(hour=7, minute=30),
        },
        "campaigns-0745": {"task": "jobs.campaigns", "schedule": crontab(hour=7, minute=45)},
        "reactivation-0750": {"task": "jobs.reactivation", "schedule": crontab(hour=7, minute=50)},
        "lost-leads-hourly": {"task": "jobs.lost_leads", "schedule": crontab(minute=5)},
        "site-poll-5min": {"task": "jobs.poll_site", "schedule": crontab(minute="*/5")},
        "catalog-0200": {"task": "jobs.sync_catalog", "schedule": crontab(hour=2, minute=0)},
        "diagnoses-0210": {"task": "jobs.sync_diagnoses", "schedule": crontab(hour=2, minute=10)},
    },
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"
