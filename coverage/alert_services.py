from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import CoverageAlert, CoverageSession
from .services import get_uncovered_players
from .session_times import get_operating_date, get_session_type


REMINDER_INTERVAL_MINUTES = 15

OPEN_ALERT_STATUSES = (
    CoverageAlert.Status.OPEN,
    CoverageAlert.Status.ACKNOWLEDGED,
    CoverageAlert.Status.ESCALATED,
)


@transaction.atomic
def create_coverage_alerts(*, moment=None):
    moment = moment or timezone.localtime()

    operating_date = get_operating_date(moment)
    session_type = get_session_type(moment)

    uncovered_players = get_uncovered_players(moment=moment)
    created_count = 0

    for player in uncovered_players:
        existing_alert = CoverageAlert.objects.filter(
            player=player,
            operating_date=operating_date,
            session_type=session_type,
            status__in=OPEN_ALERT_STATUSES,
        ).first()

        if existing_alert:
            continue

        CoverageAlert.objects.create(
            player=player,
            operating_date=operating_date,
            session_type=session_type,
            alert_type=CoverageAlert.AlertType.PLAYER_UNCOVERED,
            severity=CoverageAlert.Severity.CRITICAL,
            status=CoverageAlert.Status.OPEN,
            started_at=moment,
            next_reminder_at=moment + timedelta(
                minutes=REMINDER_INTERVAL_MINUTES
            ),
        )

        created_count += 1

    return created_count


@transaction.atomic
def resolve_covered_alerts(*, moment=None):
    moment = moment or timezone.localtime()

    operating_date = get_operating_date(moment)
    session_type = get_session_type(moment)

    covered_statuses = (
        CoverageSession.Status.OPEN,
        CoverageSession.Status.ACTIVE,
        CoverageSession.Status.REPLACEMENT_REQUESTED,
        CoverageSession.Status.HANDOVER,
    )

    covered_player_ids = CoverageSession.objects.filter(
        operating_date=operating_date,
        session_type=session_type,
        status__in=covered_statuses,
    ).values_list("player_id", flat=True)

    alerts = CoverageAlert.objects.select_for_update().filter(
        operating_date=operating_date,
        session_type=session_type,
        status__in=OPEN_ALERT_STATUSES,
        player_id__in=covered_player_ids,
    )

    resolved_count = alerts.update(
        status=CoverageAlert.Status.RESOLVED,
        resolved_at=moment,
        next_reminder_at=None,
    )

    return resolved_count


@transaction.atomic
def process_coverage_alerts(*, moment=None):
    moment = moment or timezone.localtime()

    resolved_count = resolve_covered_alerts(moment=moment)
    created_count = create_coverage_alerts(moment=moment)

    return {
        "processed_at": moment,
        "resolved_count": resolved_count,
        "created_count": created_count,
    }


@transaction.atomic
def process_due_reminders(*, moment=None):
    """
    Process all coverage alerts whose 15-minute reminder is due.

    Only unresolved alerts are processed. Once a Player becomes covered,
    the alert is resolved and no further reminders are generated.
    """
    moment = moment or timezone.localtime()

    due_alerts = CoverageAlert.objects.select_for_update().filter(
        status__in=OPEN_ALERT_STATUSES,
        next_reminder_at__isnull=False,
        next_reminder_at__lte=moment,
    )

    reminder_count = 0

    for alert in due_alerts:
        uncovered_players = get_uncovered_players(moment=moment)

        if alert.player_id not in {
            player.id for player in uncovered_players
        }:
            alert.status = CoverageAlert.Status.RESOLVED
            alert.resolved_at = moment
            alert.next_reminder_at = None
            alert.save(
                update_fields=[
                    "status",
                    "resolved_at",
                    "next_reminder_at",
                    "updated_at",
                ]
            )
            continue

        alert.last_reminder_at = moment
        alert.next_reminder_at = moment + timedelta(
            minutes=REMINDER_INTERVAL_MINUTES
        )
        alert.reminder_count += 1
        alert.save(
            update_fields=[
                "last_reminder_at",
                "next_reminder_at",
                "reminder_count",
                "updated_at",
            ]
        )

        reminder_count += 1

    return reminder_count
