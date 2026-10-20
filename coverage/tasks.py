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


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def send_continuation_prompts_task(self):
    """
    08:45 daily — send continuation prompts to every ACTIVE Day/Night
    coverage session and set continuation_deadline_at to 09:00 local time.
    """
    from django.utils import timezone
    from coverage.models import CoverageSession
    from coverage.services import prompt_coverage_continuation

    now = timezone.localtime()
    prompted = 0
    skipped = 0
    for session in CoverageSession.objects.filter(status="ACTIVE"):
        if not session.session_type:
            skipped += 1
            continue
        if session.continuation_prompted_at is not None:
            skipped += 1
            continue
        try:
            prompt_coverage_continuation(session=session, moment=now)
        except TypeError:
            prompt_coverage_continuation(session=session)
        prompted += 1
    return {"status": "success", "prompted": prompted, "skipped": skipped}


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def finalize_continuation_deadlines_task(self):
    """
    09:00 daily — finalize every CONTINUATION_PENDING session:
    sign out if no report was submitted, otherwise continue the same Player.
    """
    from django.utils import timezone
    from coverage.models import CoverageSession
    from coverage.services import finalize_coverage_continuation

    now = timezone.localtime()
    finalized = 0
    signed_out = 0
    continued = 0
    from coverage.services import handle_continuation_timeout
    for session in CoverageSession.objects.filter(status="CONTINUATION_PENDING"):
        try:
            handle_continuation_timeout(session=session, moment=now)
            new_session = finalize_coverage_continuation(session=session, moment=now)
        except Exception as exc:
            print(f"  session {session.id}: finalize failed: {exc}")
            continue
        finalized += 1
        if new_session is not None:
            continued += 1
        else:
            signed_out += 1
    return {
        "status": "success",
        "finalized": finalized,
        "continued": continued,
        "signed_out": signed_out,
    }


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def rollover_stale_coverage_alerts_task(self):
    """
    Runs once per day after the DAY/NIGHT boundaries. Marks OPEN alerts
    whose operating_date is in the past as EXPIRED. They remain in the
    table for audit, but stop generating reminders and stop inflating
    today's open-alert count.

    The alert is a historical record of a real coverage gap. Nothing
    is deleted. Nothing is fabricated. Just an honest state transition.
    """
    from django.utils import timezone
    from coverage.models import CoverageAlert

    today = timezone.localdate()
    now = timezone.now()

    expired_count = CoverageAlert.objects.filter(
        status="OPEN",
        operating_date__lt=today,
    ).update(
        status="EXPIRED",
        resolved_at=now,
    )

    return {"status": "success", "expired": expired_count}
