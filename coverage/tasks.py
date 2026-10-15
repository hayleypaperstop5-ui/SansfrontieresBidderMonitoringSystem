from config.celery import app

from .alert_services import (
    process_coverage_alerts,
    process_due_reminders,
)
from .services import close_expired_coverage_sessions, process_overdue_report_compliance


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
    process_coverage_alerts()

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

@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def process_report_compliance_overdue_task(self):
    """
    Mark expired pending report-compliance requirements as overdue
    and send the required notifications.
    """
    overdue_count = process_overdue_report_compliance()

    return {
        "status": "success",
        "overdue_count": overdue_count,
    }



# ============================================================
# PHASE 1 - AUTOMATIC SHIFT & COVERAGE LIFECYCLE
# ============================================================

from celery import shared_task
from django.utils import timezone


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def process_shift_coverage_automation(self):
    """
    Central background automation for deterministic
    Shift & Coverage lifecycle processing.

    Existing service functions remain the source of truth.
    This task only orchestrates them.
    """
    from coverage.services import close_expired_coverage_sessions
    from coverage.alert_services import (
        process_coverage_alerts,
        process_due_reminders,
    )

    moment = timezone.localtime()

    return {
        "processed_at": moment.isoformat(),
        "closed_sessions": close_expired_coverage_sessions(moment=moment),
        "alerts": process_coverage_alerts(moment=moment),
        "reminders": process_due_reminders(moment=moment),
    }

