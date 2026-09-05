from config.celery import app

from .alert_services import (
    process_coverage_alerts,
    process_due_reminders,
)
from .services import close_expired_coverage_sessions


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def close_expired_coverage_sessions_task(self):
    """
    Automatically close Player Coverage Sessions that have reached
    their system-calculated scheduled closure time.

    The actual business logic remains in coverage.services so that
    website actions and scheduled automation use the same rules.
    """
    closed_count = close_expired_coverage_sessions()

    return {
        "status": "success",
        "closed_count": closed_count,
    }


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def check_player_coverage_task(self):
    """
    Automatically check active Players for uncovered coverage.

    The actual alert logic remains in coverage.alert_services so that
    scheduled automation and future website actions use the same rules.
    """
    result = process_coverage_alerts()

    return {
        "status": "success",
        "processed_at": result["processed_at"].isoformat(),
        "resolved_count": result["resolved_count"],
        "created_count": result["created_count"],
    }


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def process_coverage_reminders_task(self):
    """
    Process due reminders for uncovered Players.

    Reminders continue every 15 minutes until the Player becomes covered.
    Once coverage is secured, the underlying alert service resolves the
    alert and no further reminders are generated.
    """
    reminder_count = process_due_reminders()

    return {
        "status": "success",
        "reminder_count": reminder_count,
    }