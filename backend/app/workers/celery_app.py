from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("radeski_crm", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    timezone=settings.tz,
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Periodic jobs (TZ 4.5 / ARXITEKTURA 4.1) are registered here as modules land.
    beat_schedule={},
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"
