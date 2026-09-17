
from celery import Celery
from celery.schedules import crontab

from config import Config

celery_app = Celery(
    "trekking_tasks",
    broker=Config.CELERY_BROKER_URL,
    backend=Config.CELERY_RESULT_BACKEND,
    include=["tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=86400,  # keep task results for 24h
)

# --- Scheduled (Celery Beat) jobs -------------------------------------------------
celery_app.conf.beat_schedule = {
    "daily-trek-reminders": {
        "task": "tasks.send_daily_reminders",
        "schedule": crontab(hour=7, minute=0),  
    },
    "monthly-activity-report": {
        "task": "tasks.generate_monthly_report",
        "schedule": crontab(day_of_month=1, hour=6, minute=0),  #
    },
}