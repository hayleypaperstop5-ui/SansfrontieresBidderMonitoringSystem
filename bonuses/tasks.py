from config.celery import app

from .services import determine_daily_moderator_bonuses


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def determine_daily_moderator_bonuses_task(self):
    """
    Perform the official daily Moderator bonus determination.

    Celery Beat schedules this task for 09:45 local time each day.
    The business logic remains in bonuses.services so that scheduled
    automation and future manual/admin actions use the same rules.
    """
    awards = determine_daily_moderator_bonuses()

    return {
        "status": "success",
        "awards_count": len(awards),
    }
