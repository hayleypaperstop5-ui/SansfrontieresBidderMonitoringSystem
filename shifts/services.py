from django.utils import timezone

from .models import Shift


def get_report_due_at(shift):
    """
    Return the report deadline for a shift in Africa/Nairobi time.

    Day Shift:
        Due at 8:30 PM on the shift date.

    Night Shift:
        Due at 8:30 AM on the following day.
    """
    from datetime import datetime, time, timedelta

    if shift.shift_type == shift.ShiftType.DAY:
        deadline_date = shift.date
        deadline_time = time(20, 30)
    else:
        deadline_date = shift.date + timedelta(days=1)
        deadline_time = time(8, 30)

    naive_datetime = datetime.combine(
        deadline_date,
        deadline_time,
    )

    return timezone.make_aware(
        naive_datetime,
        timezone.get_current_timezone(),
    )


def get_report_enforcement_at(shift):
    """
    Return the time when the worker becomes blocked.

    Day Shift:
        9:30 PM on the shift date.

    Night Shift:
        9:30 AM on the following day.
    """
    from datetime import datetime, time, timedelta

    if shift.shift_type == shift.ShiftType.DAY:
        enforcement_date = shift.date
        enforcement_time = time(21, 30)
    else:
        enforcement_date = shift.date + timedelta(days=1)
        enforcement_time = time(9, 30)

    naive_datetime = datetime.combine(
        enforcement_date,
        enforcement_time,
    )

    return timezone.make_aware(
        naive_datetime,
        timezone.get_current_timezone(),
    )


def has_outstanding_shift_report(user):
    """
    Return True only when a worker has a missing shift report
    and the enforcement deadline has passed.
    """
    now = timezone.now()

    shifts = Shift.objects.filter(
        actual_worker=user,
        status__in=(
            Shift.Status.AWAITING_REPORT,
            Shift.Status.REPORT_OVERDUE,
        ),
        report__isnull=True,
    )

    for shift in shifts:
        if now >= get_report_enforcement_at(shift):
            return True

    return False
