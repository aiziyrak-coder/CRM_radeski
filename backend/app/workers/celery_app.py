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
    # OpenAI calls can wait minutes (flex tier): they run on their own worker (compose
    # `worker-ai`, queue "ai") so messages, reminders and recordings never queue behind them
    task_routes={
        "jobs.analyze_call": {"queue": "ai"},
        "jobs.weekly_digest": {"queue": "ai"},
        "jobs.ai_diagnoses": {"queue": "ai"},
    },
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
        "recordings-retry": {"task": "jobs.retry_recordings", "schedule": crontab(minute="*/30")},
        "stale-calls-10min": {"task": "jobs.close_stale_calls", "schedule": crontab(minute="*/10")},
        "analyses-retry": {"task": "jobs.retry_analyses", "schedule": crontab(minute="15,45")},
        "messages-every-minute": {"task": "jobs.deliver_due", "schedule": crontab()},
        "reminders-1000": {"task": "jobs.reminders", "schedule": crontab(hour=10, minute=0)},
        "digest-monday-0800": {
            "task": "jobs.weekly_digest",
            "schedule": crontab(hour=8, minute=0, day_of_week="mon"),
        },
    },
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"
