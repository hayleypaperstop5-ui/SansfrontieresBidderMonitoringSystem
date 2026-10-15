from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from notifications.models import Notification
from django.utils import timezone

from accounts.models import User
from players.models import Player

from .models import CoverageSession, EndOfSessionReport, ReportCompliance
from .session_times import (
    get_operating_date,
    get_scheduled_close_at,
    get_session_type,
)


ACTIVE_STATUSES = (
    CoverageSession.Status.ACTIVE,
    CoverageSession.Status.CONTINUATION_PENDING,
    CoverageSession.Status.REPLACEMENT_REQUESTED,
    CoverageSession.Status.HANDOVER,
)


def _notify_management_team(*, title, message, alert_level):
    recipients = User.objects.filter(
        role__in=(
            User.Role.MANAGER,
            User.Role.DIRECTOR,
        ),
        is_active=True,
    )

    notifications = [
        Notification(
            recipient=recipient,
            notification_type=Notification.NotificationType.GENERAL,
            alert_level=alert_level,
            title=title,
            message=message,
        )
        for recipient in recipients
    ]

    if notifications:
        Notification.objects.bulk_create(notifications)

    return len(notifications)


def _notify_moderator(*, moderator, title, message, alert_level):
    return Notification.objects.create(
        recipient=moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=alert_level,
        title=title,
        message=message,
    )


def _email_management_team(*, subject, message):
    recipients = User.objects.filter(
        role__in=(
            User.Role.MANAGER,
            User.Role.DIRECTOR,
        ),
        is_active=True,
    ).exclude(email="").values_list("email", flat=True)

    for email in recipients:
        transaction.on_commit(
            lambda recipient_email=email: send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [recipient_email],
                fail_silently=False,
            )
        )


@transaction.atomic
def start_coverage_session(
    *,
    moderator: User,
    player: Player,
    moment=None,
) -> CoverageSession:
    if moderator.role != User.Role.MODERATOR:
        raise ValidationError("Only Moderators can start coverage sessions.")


    staff_profile = getattr(moderator, "staff_profile", None)

    if staff_profile is None:
        raise ValidationError("The Moderator does not have a staff profile.")

    if staff_profile.status != staff_profile.Status.ACTIVE:
        raise ValidationError(
            f"The Moderator is currently {staff_profile.get_status_display()} "
            "and cannot start a coverage session."
        )

    if player.status != Player.Status.ACTIVE:
        raise ValidationError(
            f"{player} is not active and cannot receive coverage."
        )

    if moment is None:
        moment = timezone.localtime()

    session_type = get_session_type(moment)
    operating_date = get_operating_date(moment, session_type)
    scheduled_close_at = get_scheduled_close_at(moment, session_type)

    if CoverageSession.objects.filter(
        moderator=moderator,
        status__in=ACTIVE_STATUSES,
    ).exists():
        raise ValidationError(
            "This Moderator already has an active Player coverage session."
        )

    if CoverageSession.objects.filter(
        player=player,
        status__in=ACTIVE_STATUSES,
    ).exists():
        raise ValidationError(
            "This Player is already being covered by another Moderator."
        )

    session = CoverageSession(
        player=player,
        moderator=moderator,
        operating_date=operating_date,
        session_type=session_type,
        signed_in_at=moment,
        scheduled_close_at=scheduled_close_at,
        status=CoverageSession.Status.ACTIVE,
    )

    session.full_clean()
    session.save()

    return session


@transaction.atomic
def assign_coverage_session(
    *,
    manager: User,
    moderator: User,
    player: Player,
    moment=None,
) -> CoverageSession:
    """
    Assign an active Moderator to an active Player.

    Assignment does not sign the Moderator in. The resulting CoverageSession
    remains OPEN until the Moderator explicitly signs in.
    """
    if manager.role not in (
        User.Role.ADMIN,
        User.Role.DIRECTOR,
        User.Role.MANAGER,
    ):
        raise ValidationError(
            "Only a Manager, Director, or System Administrator can assign coverage."
        )

    if moderator.role != User.Role.MODERATOR:
        raise ValidationError(
            "Coverage can only be assigned to a Moderator."
        )

    if not moderator.is_active:
        raise ValidationError(
            "This Moderator is inactive and cannot be assigned coverage."
        )

    staff_profile = getattr(moderator, "staff_profile", None)

    if staff_profile is None:
        raise ValidationError(
            "The Moderator does not have a staff profile."
        )

    if staff_profile.status != staff_profile.Status.ACTIVE:
        raise ValidationError(
            f"The Moderator is currently {staff_profile.get_status_display()} "
            "and cannot be assigned coverage."
        )

    if player.status != Player.Status.ACTIVE:
        raise ValidationError(
            f"{player} is not active and cannot receive coverage."
        )

    if CoverageSession.objects.filter(
        moderator=moderator,
        status=CoverageSession.Status.AWAITING_REPORT,
    ).exists():
        raise ValidationError(
            "This Moderator has an outstanding End-of-Session Report and cannot be assigned a new Player until the report is submitted."
        )

    if moment is None:
        moment = timezone.localtime()

    session_type = get_session_type(moment)
    operating_date = get_operating_date(moment, session_type)
    scheduled_close_at = get_scheduled_close_at(moment, session_type)

    if CoverageSession.objects.filter(
        moderator=moderator,
        status__in=(
            CoverageSession.Status.OPEN,
            *ACTIVE_STATUSES,
        ),
    ).exists():
        raise ValidationError(
            "This Moderator already has an assigned or active Player coverage session."
        )

    if CoverageSession.objects.filter(
        player=player,
        status__in=(
            CoverageSession.Status.OPEN,
            *ACTIVE_STATUSES,
        ),
    ).exists():
        raise ValidationError(
            "This Player is already assigned to or being covered by another Moderator."
        )

    session = CoverageSession(
        player=player,
        moderator=moderator,
        operating_date=operating_date,
        session_type=session_type,
        signed_in_at=None,
        sign_in_deadline_at=moment + timedelta(minutes=15),
        scheduled_close_at=scheduled_close_at,
        status=CoverageSession.Status.OPEN,
        notes=f"Coverage assigned by {manager.get_full_name() or manager.username}.",
    )

    session.full_clean()
    session.save()

    moderator_name = (
        moderator.get_full_name()
        or moderator.username
    )

    Notification.objects.create(
        recipient=moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=Notification.AlertLevel.IMPORTANT,
        title="New Player Coverage Assignment",
        message=(
            f"Hello {moderator_name}, please note that you've been assigned "
            f"{player}. You have 15 minutes to sign in. Failure to sign in "
            "within this period will cause this session to be marked as "
            '"Missed" and the Manager will do a replacement.'
        ),
    )

    if moderator.email:
        subject = "New Player Coverage Assignment"
        message = (
            f"Hello {moderator_name},\n\n"
            f"You have been assigned {player} for coverage.\n\n"
            "You have 15 minutes to sign in to the Moderator Portal. "
            "Failure to sign in within this period will cause this session "
            'to be marked as "Missed" and the Manager will do a replacement.\n\n'
            f"Sign-in deadline: "
            f"{session.sign_in_deadline_at.strftime('%d %B %Y at %H:%M')}\n\n"
            "Regards,\n\n"
            "Sansfrontieres Chat Moderation"
        )

        transaction.on_commit(
            lambda: send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [moderator.email],
                fail_silently=False,
            )
        )

    return session


@transaction.atomic
def activate_assigned_coverage(
    *,
    session: CoverageSession,
    moderator: User,
    moment=None,
) -> CoverageSession:
    """
    Activate an existing Manager-created OPEN coverage assignment
    when the assigned Moderator signs in.
    """
    if moderator.role != User.Role.MODERATOR:
        raise ValidationError(
            "Only Moderators can activate coverage sessions."
        )

    if session.moderator_id != moderator.id:
        raise ValidationError(
            "You can only sign in to your own assigned coverage session."
        )

    if session.status != CoverageSession.Status.OPEN:
        raise ValidationError(
            "Only an open assigned coverage session can be activated."
        )

    if moment is None:
        moment = timezone.localtime()

    if session.sign_in_deadline_at and moment >= session.sign_in_deadline_at:
        session.status = CoverageSession.Status.EXPIRED
        session.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )
        raise ValidationError(
            "The 15-minute sign-in window has expired. "
            "This assignment is now marked as missed."
        )

    staff_profile = getattr(moderator, "staff_profile", None)

    if staff_profile is None:
        raise ValidationError(
            "The Moderator does not have a staff profile."
        )

    if staff_profile.status != staff_profile.Status.ACTIVE:
        raise ValidationError(
            f"The Moderator is currently "
            f"{staff_profile.get_status_display()} "
            "and cannot start coverage."
        )

    if session.player.status != Player.Status.ACTIVE:
        raise ValidationError(
            f"{session.player} is not active and cannot receive coverage."
        )

    if CoverageSession.objects.filter(
        moderator=moderator,
        status__in=ACTIVE_STATUSES,
    ).exists():
        raise ValidationError(
            "This Moderator already has an active Player coverage session."
        )

    if CoverageSession.objects.filter(
        player=session.player,
        status__in=ACTIVE_STATUSES,
    ).exists():
        raise ValidationError(
            "This Player is already being covered by another Moderator."
        )

    if moment is None:
        moment = timezone.localtime()

    session.signed_in_at = moment
    session.status = CoverageSession.Status.ACTIVE
    session.save(
        update_fields=[
            "signed_in_at",
            "status",
            "updated_at",
        ]
    )

    moderator_name = (
        session.moderator.get_full_name()
        or session.moderator.username
    )

    sign_in_message = (
        f"{moderator_name} has successfully signed in to cover "
        f"{session.player}. No replacement is required at the moment."
    )

    _notify_management_team(
        title="Player Coverage Sign-In Successful",
        message=sign_in_message,
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    _email_management_team(
        subject="Player Coverage Sign-In Successful",
        message=(
            f"Hello,\n\n"
            f"{sign_in_message}\n\n"
            "Regards,\n\n"
            "Sansfrontieres Chat Moderation"
        ),
    )

    return session


@transaction.atomic
def request_replacement(
    *,
    session: CoverageSession,
    moderator: User,
    moment=None,
) -> CoverageSession:
    if moment is None:
        moment = timezone.localtime()

    if session.moderator_id != moderator.id:
        raise ValidationError(
            "Only the Moderator assigned to this coverage session can request a replacement."
        )

    if session.status != CoverageSession.Status.ACTIVE:
        raise ValidationError(
            "A replacement can only be requested for an active coverage session."
        )

    session.status = CoverageSession.Status.REPLACEMENT_REQUESTED
    session.replacement_requested_at = moment
    session.save(
        update_fields=[
            "status",
            "replacement_requested_at",
            "updated_at",
        ]
    )

    moderator_name = (
        session.moderator.get_full_name()
        or session.moderator.username
    )

    replacement_request_message = (
        f"{moderator_name} has requested a replacement for "
        f"Player {session.player}. Please review the request and "
        "assign an available eligible Moderator from the list "
        "provided to ensure continuous coverage."
    )

    _notify_management_team(
        title="Coverage Replacement Requested",
        message=replacement_request_message,
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    _email_management_team(
        subject="Coverage Replacement Requested",
        message=(
            f"Hello,\n\n"
            f"{replacement_request_message}\n\n"
            "Regards,\n\n"
            "Sansfrontieres Chat Moderation"
        ),
    )

    return session


@transaction.atomic

@transaction.atomic
def prompt_coverage_continuation(
    *,
    session: CoverageSession,
    moment=None,
) -> CoverageSession:
    """
    Put an active session into the 15-minute continuation window.

    The continuation window is:
        Day:     08:45 -> 09:00
        Evening: 20:45 -> 21:00

    scheduled_close_at is the HARD boundary, never the prompt time.
    """
    if moment is None:
        moment = timezone.localtime()

    if session.status != CoverageSession.Status.ACTIVE:
        raise ValidationError(
            "A continuation prompt can only be issued for an active coverage session."
        )

    if session.scheduled_close_at is None:
        raise ValidationError(
            "This coverage session does not have a scheduled continuation boundary."
        )

    prompt_start = session.scheduled_close_at - timedelta(minutes=15)

    if moment < prompt_start:
        raise ValidationError(
            "The continuation prompt window has not started yet."
        )

    if moment >= session.scheduled_close_at:
        raise ValidationError(
            "The continuation boundary has already been reached."
        )

    deadline = session.scheduled_close_at

    session.status = CoverageSession.Status.CONTINUATION_PENDING
    session.continuation_prompted_at = moment
    session.continuation_deadline_at = deadline
    session.continuation_response = ""
    session.continuation_responded_at = None

    session.save(
        update_fields=[
            "status",
            "continuation_prompted_at",
            "continuation_deadline_at",
            "continuation_response",
            "continuation_responded_at",
            "updated_at",
        ]
    )

    moderator = session.moderator
    moderator_name = (
        moderator.get_full_name()
        or moderator.username
    )

    prompt_title = "Coverage Continuation Required"

    prompt_message = (
        f"Your current coverage session for {session.player} is approaching "
        f"its hard boundary at {deadline.strftime('%d %B %Y at %H:%M')}. "
        "Choose YES to continue covering this Player or NO to end the "
        "current session. If you do not respond before the boundary, "
        "you will be signed out automatically and an End-of-Session Report "
        "will be required."
    )

    _notify_moderator(
        moderator=moderator,
        title=prompt_title,
        message=prompt_message,
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    _notify_management_team(
        title=prompt_title,
        message=(
            f"{moderator_name} has been prompted to confirm continuation "
            f"for {session.player}. The hard boundary is "
            f"{deadline.strftime('%d %B %Y at %H:%M')}."
        ),
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    return session



@transaction.atomic

@transaction.atomic
def respond_to_coverage_continuation(
    *,
    session: CoverageSession,
    moderator: User,
    response,
    moment=None,
) -> CoverageSession:
    """
    Process the Moderator's YES/NO decision.

    YES:
      - Evening/Night: keep the current session pending until the hard
        boundary, then close it and create a new active session.
      - Morning/Day: end the current session and require its report;
        after the report is successfully submitted, a new Day session
        is created at/after the 09:00 boundary.

    NO:
      - End the current session immediately.
      - Require the End-of-Session Report.
      - The Player becomes available to the normal assignment workflow.

    The existing session is NEVER extended.
    """
    if moment is None:
        moment = timezone.localtime()

    if session.moderator_id != moderator.id:
        raise ValidationError(
            "Only the Moderator assigned to this coverage session can respond."
        )

    response = (response or "").strip().upper()

    if response not in ("YES", "NO"):
        raise ValidationError(
            "Continuation response must be YES or NO."
        )

    if session.status != CoverageSession.Status.CONTINUATION_PENDING:
        raise ValidationError(
            "This coverage session is not awaiting a continuation response."
        )

    if session.continuation_deadline_at is None:
        raise ValidationError(
            "This coverage session does not have a continuation deadline."
        )

    if moment >= session.continuation_deadline_at:
        raise ValidationError(
            "The continuation response deadline has passed. "
            "The session must be processed as an automatic timeout."
        )

    session.continuation_response = response
    session.continuation_responded_at = moment
    session.continuation_deadline_at = None

    if response == "NO":
        session.status = CoverageSession.Status.AWAITING_REPORT
        session.signed_out_at = moment
        session.closure_reason = CoverageSession.ClosureReason.NORMAL

        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "closure_reason",
                "continuation_response",
                "continuation_responded_at",
                "continuation_deadline_at",
                "updated_at",
            ]
        )

        create_report_compliance(
            session=session,
            signed_out_at=moment,
        )

        moderator_name = (
            moderator.get_full_name()
            or moderator.username
        )

        message = (
            f"{moderator_name} chose not to continue coverage for "
            f"{session.player}. The current session has ended, the "
            "Moderator has been signed out, and an End-of-Session Report "
            "is required. The Player is now available to the normal "
            "coverage assignment workflow."
        )

        _notify_moderator(
            moderator=moderator,
            title="Coverage Session Ended",
            message=(
                f"You chose not to continue covering {session.player}. "
                "You have been signed out and must submit your "
                "End-of-Session Report."
            ),
            alert_level=Notification.AlertLevel.IMPORTANT,
        )

        _notify_management_team(
            title="Coverage Session Ended",
            message=message,
            alert_level=Notification.AlertLevel.IMPORTANT,
        )

        return session

    # YES: never extend the old session.
    # Determine whether this is the Day/Morning continuation boundary.
    if session.session_type == CoverageSession.SessionType.DAY:
        # Morning/day continuation requires the report before the new
        # session can be created.
        session.status = CoverageSession.Status.AWAITING_REPORT
        session.signed_out_at = moment
        session.closure_reason = CoverageSession.ClosureReason.NORMAL

        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "closure_reason",
                "continuation_response",
                "continuation_responded_at",
                "continuation_deadline_at",
                "updated_at",
            ]
        )

        create_report_compliance(
            session=session,
            signed_out_at=moment,
        )

        moderator_name = (
            moderator.get_full_name()
            or moderator.username
        )

        _notify_moderator(
            moderator=moderator,
            title="Morning Continuation Confirmed",
            message=(
                f"You chose YES to continue covering {session.player}. "
                "Your current session has ended and an End-of-Session "
                "Report is required before the next Day coverage session "
                "can begin at the 09:00 boundary."
            ),
            alert_level=Notification.AlertLevel.IMPORTANT,
        )

        _notify_management_team(
            title="Morning Continuation Confirmed",
            message=(
                f"{moderator_name} chose YES to continue covering "
                f"{session.player}. Session {session.id} has been closed "
                "for reporting and will continue in a new session after "
                "the End-of-Session Report is successfully submitted."
            ),
            alert_level=Notification.AlertLevel.IMPORTANT,
        )

        return session

    # Evening/Night YES:
    # Keep the current session in CONTINUATION_PENDING until 21:00.
    session.save(
        update_fields=[
            "continuation_response",
            "continuation_responded_at",
            "continuation_deadline_at",
            "updated_at",
        ]
    )

    moderator_name = (
        moderator.get_full_name()
        or moderator.username
    )

    _notify_moderator(
        moderator=moderator,
        title="Evening Continuation Confirmed",
        message=(
            f"You chose YES to continue covering {session.player}. "
            "At the 21:00 hard boundary, your current session will close "
            "and a new coverage session will start automatically. "
            "No End-of-Session Report is required for this evening "
            "continuation."
        ),
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    _notify_management_team(
        title="Evening Continuation Confirmed",
        message=(
            f"{moderator_name} chose YES to continue covering "
            f"{session.player}. A new coverage session will be created "
            "automatically at the 21:00 hard boundary."
        ),
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    return session




@transaction.atomic
def _create_continuation_session(
    *,
    previous_session: CoverageSession,
    moment=None,
) -> CoverageSession:
    """
    Create a genuinely new CoverageSession for continuation.

    The previous session is never extended. It must already be closed
    before this function creates the next session.
    """
    if moment is None:
        moment = timezone.localtime()

    if previous_session.status != CoverageSession.Status.COMPLETED:
        raise ValidationError(
            "The previous coverage session must be completed before "
            "a continuation session can be created."
        )

    moderator = previous_session.moderator
    player = previous_session.player

    if moderator.role != User.Role.MODERATOR:
        raise ValidationError(
            "Only a Moderator can receive a continuation session."
        )

    moderator_profile = getattr(moderator, "staff_profile", None)

    if moderator_profile is None:
        raise ValidationError(
            "The Moderator does not have a staff profile."
        )

    if moderator_profile.status != moderator_profile.Status.ACTIVE:
        raise ValidationError(
            "The Moderator is no longer active."
        )

    if player.status != Player.Status.ACTIVE:
        raise ValidationError(
            f"{player} is no longer active and cannot receive coverage."
        )

    if CoverageSession.objects.filter(
        moderator=moderator,
    ).filter(
        Q(status__in=ACTIVE_STATUSES)
        | Q(status=CoverageSession.Status.AWAITING_REPORT)
    ).exists():
        raise ValidationError(
            "The Moderator is still occupied by another coverage session "
            "or has a pending End-of-Session Report."
        )

    if CoverageSession.objects.filter(
        player=player,
    ).filter(
        Q(status__in=ACTIVE_STATUSES)
        | Q(status=CoverageSession.Status.AWAITING_REPORT)
    ).exists():
        raise ValidationError(
            "The Player is still occupied by another coverage session "
            "or has a pending End-of-Session Report."
        )

    session_type = get_session_type(moment)
    operating_date = get_operating_date(moment, session_type)
    scheduled_close_at = get_scheduled_close_at(moment, session_type)

    new_session = CoverageSession(
        player=player,
        moderator=moderator,
        operating_date=operating_date,
        session_type=session_type,
        signed_in_at=moment,
        sign_in_deadline_at=None,
        scheduled_close_at=scheduled_close_at,
        status=CoverageSession.Status.ACTIVE,
        notes=(
            f"Continuation of coverage session "
            f"{previous_session.id}."
        ),
    )

    new_session.full_clean()
    new_session.save()

    previous_session.replacement_session = new_session
    previous_session.save(
        update_fields=[
            "replacement_session",
            "updated_at",
        ]
    )

    moderator_name = (
        moderator.get_full_name()
        or moderator.username
    )

    _notify_moderator(
        moderator=moderator,
        title="Coverage Continued",
        message=(
            f"Coverage for {player} has continued in a new coverage "
            f"session. Your new session started at "
            f"{moment.strftime('%d %B %Y at %H:%M')} and its hard boundary is "
            f"{scheduled_close_at.strftime('%d %B %Y at %H:%M')}."
        ),
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    _notify_management_team(
        title="Coverage Continuation Started",
        message=(
            f"{moderator_name} has continued coverage for {player} "
            f"under new CoverageSession {new_session.id}. "
            f"The previous session {previous_session.id} has been closed."
        ),
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    return new_session



@transaction.atomic
def finalize_morning_continuation(
    *,
    session: CoverageSession,
    moment=None,
):
    """
    After a Day-session YES response and successful End-of-Session Report,
    create the new Day CoverageSession once the 09:00 hard boundary has
    been reached.

    Returns the new session when created, otherwise None.
    """
    if moment is None:
        moment = timezone.localtime()

    if session.session_type != CoverageSession.SessionType.DAY:
        return None

    if session.continuation_response != "YES":
        return None

    if session.status != CoverageSession.Status.COMPLETED:
        return None

    if session.scheduled_close_at is None:
        raise ValidationError(
            "The completed morning session has no continuation boundary."
        )

    if moment < session.scheduled_close_at:
        return None

    if not hasattr(session, "end_of_session_report"):
        return None

    # Prevent duplicate continuation sessions.
    existing = CoverageSession.objects.filter(
        replacement_session_id=session.id,
    ).first()

    if existing is not None:
        return existing

    new_session = _create_continuation_session(
        previous_session=session,
        moment=moment,
    )

    return new_session


def create_report_compliance(*, session, signed_out_at):
    """Create the 30-minute End-of-Session Report compliance requirement."""
    if signed_out_at is None:
        raise ValidationError("Report compliance requires a valid sign-out timestamp.")

    compliance, _ = ReportCompliance.objects.get_or_create(
        coverage_session=session,
        defaults={
            "signed_out_at": signed_out_at,
            "report_deadline": signed_out_at + timedelta(minutes=30),
        },
    )
    return compliance


@transaction.atomic
def process_overdue_report_compliance(*, moment=None) -> int:
    """Mark expired pending report-compliance requirements as overdue and notify."""
    if moment is None:
        moment = timezone.localtime()

    overdue_compliance = (
        ReportCompliance.objects.select_for_update()
        .filter(
            status=ReportCompliance.Status.PENDING,
            report_deadline__lte=moment,
        )
        .select_related(
            "coverage_session",
            "coverage_session__moderator",
            "coverage_session__player",
        )
    )

    overdue_count = 0

    for compliance in overdue_compliance:
        session = compliance.coverage_session
        moderator = session.moderator
        player = session.player

        compliance.status = ReportCompliance.Status.OVERDUE
        compliance.overdue_at = moment
        compliance.save(
            update_fields=[
                "status",
                "overdue_at",
                "updated_at",
            ]
        )

        moderator_name = moderator.get_full_name() or moderator.username
        player_name = str(player)

        title = "End-of-Session Report Overdue"

        Notification.objects.create(
            recipient=moderator,
            notification_type=Notification.NotificationType.OVERDUE_SHIFT_REPORT,
            alert_level=Notification.AlertLevel.CRITICAL,
            title=title,
            message=(
                f"Your End-of-Session Report for {player_name} is overdue. "
                f"It was due by "
                f"{compliance.report_deadline.strftime('%d %B %Y at %H:%M')}. "
                "Submit the report as soon as possible."
            ),
        )

        management_recipients = User.objects.filter(
            role__in=(
                User.Role.MANAGER,
                User.Role.DIRECTOR,
            ),
            is_active=True,
        )

        management_notifications = [
            Notification(
                recipient=recipient,
                notification_type=Notification.NotificationType.OVERDUE_SHIFT_REPORT,
                alert_level=Notification.AlertLevel.CRITICAL,
                title=title,
                message=(
                    f"{moderator_name}'s End-of-Session Report for "
                    f"{player_name} is overdue. "
                    f"The report was due by "
                    f"{compliance.report_deadline.strftime('%d %B %Y at %H:%M')}."
                ),
            )
            for recipient in management_recipients
        ]

        if management_notifications:
            Notification.objects.bulk_create(management_notifications)

        moderator_email = (moderator.email or "").strip()

        moderator_email_message = (
            f"Hello {moderator_name},\n\n"
            f"Your End-of-Session Report for {player_name} is overdue. "
            f"It was due by "
            f"{compliance.report_deadline.strftime('%d %B %Y at %H:%M')}. "
            "Submit the report as soon as possible.\n\n"
            "Regards,\n\n"
            "Sansfrontieres Chat Moderation"
        )

        if moderator_email:
            transaction.on_commit(
                lambda recipient_email=moderator_email, email_message=moderator_email_message: send_mail(
                    title,
                    email_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [recipient_email],
                    fail_silently=False,
                )
            )

        management_email_recipients = list(
            management_recipients
            .exclude(email="")
            .values_list("email", flat=True)
        )

        management_email_message = (
            f"Hello,\n\n"
            f"{moderator_name}'s End-of-Session Report for "
            f"{player_name} is overdue. "
            f"The report was due by "
            f"{compliance.report_deadline.strftime('%d %B %Y at %H:%M')}.\n\n"
            "Regards,\n\n"
            "Sansfrontieres Chat Moderation"
        )

        for recipient_email in management_email_recipients:
            transaction.on_commit(
                lambda email=recipient_email, email_message=management_email_message: send_mail(
                    title,
                    email_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=False,
                )
            )

        overdue_count += 1

    return overdue_count


@transaction.atomic
def assign_replacement(
    *,
    session: CoverageSession,
    replacement_moderator: User,
    moment=None,
) -> CoverageSession:
    if moment is None:
        moment = timezone.localtime()

    if session.status != CoverageSession.Status.REPLACEMENT_REQUESTED:
        raise ValidationError(
            "A replacement can only be assigned to a session with a pending replacement request."
        )

    if replacement_moderator.role != User.Role.MODERATOR:
        raise ValidationError(
            "Replacement coverage can only be assigned to a Moderator."
        )

    if replacement_moderator.id == session.moderator_id:
        raise ValidationError(
            "A Moderator cannot replace their own coverage session."
        )

    replacement_profile = getattr(
        replacement_moderator,
        "staff_profile",
        None,
    )

    if replacement_profile is None:
        raise ValidationError(
            "The replacement Moderator does not have a staff profile."
        )

    if replacement_profile.status != replacement_profile.Status.ACTIVE:
        raise ValidationError(
            f"The replacement Moderator is currently "
            f"{replacement_profile.get_status_display()} and cannot take coverage."
        )

    if session.player.status != Player.Status.ACTIVE:
        raise ValidationError(
            f"{session.player} is no longer active and cannot receive coverage."
        )

    if CoverageSession.objects.filter(
        moderator=replacement_moderator,
    ).filter(
        Q(status__in=ACTIVE_STATUSES)
        | Q(status=CoverageSession.Status.AWAITING_REPORT)
    ).exists():
        raise ValidationError(
            "The replacement Moderator is currently unavailable. "
            "They must complete their pending End-of-Session Report first."
        )

    session.status = CoverageSession.Status.AWAITING_REPORT
    session.signed_out_at = moment
    session.closure_reason = CoverageSession.ClosureReason.REPLACED
    session.replacement_moderator = replacement_moderator
    session.save(
        update_fields=[
            "status",
            "signed_out_at",
            "closure_reason",
            "replacement_moderator",
            "updated_at",
        ]
    )

    create_report_compliance(
        session=session,
        signed_out_at=session.signed_out_at,
    )

    new_session = CoverageSession(
        player=session.player,
        moderator=replacement_moderator,
        operating_date=session.operating_date,
        session_type=session.session_type,
        signed_in_at=None,
        sign_in_deadline_at=moment + timedelta(minutes=15),
        scheduled_close_at=session.scheduled_close_at,
        status=CoverageSession.Status.OPEN,
        notes=f"Replacement for coverage session {session.id}.",
    )

    new_session.full_clean()
    new_session.save()

    session.replacement_session = new_session
    session.save(update_fields=["replacement_session", "updated_at"])

    replacement_moderator_name = (
        replacement_moderator.get_full_name()
        or replacement_moderator.username
    )

    replacement_assignment_message = (
        f"You have successfully assigned {replacement_moderator_name} "
        f"as the replacement Moderator for Player {session.player}. "
        "The replacement Moderator must sign in within 15 minutes "
        "to continue covering the Player. If they fail to sign in "
        "within this period, the replacement session will expire "
        "and another eligible replacement will be required."
    )

    _notify_management_team(
        title="Replacement Successfully Implemented",
        message=replacement_assignment_message,
        alert_level=Notification.AlertLevel.IMPORTANT,
    )

    _email_management_team(
        subject="Replacement Successfully Implemented",
        message=(
            f"Hello,\n\n"
            f"{replacement_assignment_message}\n\n"
            "Regards,\n\n"
            "Sansfrontieres Chat Moderation"
        ),
    )

    Notification.objects.create(
        recipient=session.moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=Notification.AlertLevel.CRITICAL,
        title="Replacement Coverage Assigned",
        message=(
            f"Your replacement for {session.player} has been assigned successfully. "
            f"{replacement_moderator_name} has been assigned to take over coverage. "
            "You have been signed out automatically and your coverage session is "
            "now awaiting your End-of-Session Report."
        ),
    )

    replacement_notification_message = (
        f"You have been assigned as the replacement Moderator for {session.player}. "
        "You have 15 minutes to sign in to the Moderator Portal. "
        "You must sign in successfully before you can continue covering the Player. "
        "If you fail to sign in within this period, the replacement session will "
        "expire and the Manager will need to assign another eligible Moderator."
    )

    Notification.objects.create(
        recipient=replacement_moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=Notification.AlertLevel.IMPORTANT,
        title="New Player Coverage Assignment",
        message=replacement_notification_message,
    )

    if replacement_moderator.email:
        subject = "Replacement Coverage Assignment"
        message = (
            f"Hello {replacement_moderator_name},\n\n"
            f"You have been assigned as the replacement Moderator for "
            f"{session.player} for coverage.\n\n"
            "You have 15 minutes to sign in to the Moderator Portal. "
            "You must sign in successfully before you can continue covering "
            "the Player. Failure to sign in within this period will cause "
            "the replacement session to expire and the Manager will need "
            "to assign another eligible Moderator.\n\n"
            f"Sign-in deadline: "
            f"{new_session.sign_in_deadline_at.strftime('%d %B %Y at %H:%M')}\n\n"
            "Regards,\n\n"
            "Sansfrontieres Chat Moderation"
        )

        transaction.on_commit(
            lambda: send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [replacement_moderator.email],
                fail_silently=False,
            )
        )

    return new_session


@transaction.atomic
def end_coverage_session(
    *,
    session: CoverageSession,
    moderator: User,
    moment=None,
) -> CoverageSession:
    if moment is None:
        moment = timezone.localtime()

    if session.moderator_id != moderator.id:
        raise ValidationError(
            "Only the Moderator assigned to this coverage session can sign out."
        )

    if session.status == CoverageSession.Status.AWAITING_REPORT:
        if session.closure_reason != CoverageSession.ClosureReason.REPLACED:
            raise ValidationError(
                "This coverage session is not awaiting replacement sign-out."
            )

        if session.signed_out_at is not None:
            raise ValidationError(
                "You have already signed out of this coverage session."
            )

        session.signed_out_at = moment
        session.save(
            update_fields=[
                "signed_out_at",
                "updated_at",
            ]
        )

        create_report_compliance(
            session=session,
            signed_out_at=session.signed_out_at,
        )

        return session

    if session.status != CoverageSession.Status.ACTIVE:
        raise ValidationError(
            "Only an active coverage session can be signed out normally."
        )

    raise ValidationError(
        "You cannot sign out while covering this Player. "
        "Request a replacement first, and sign out once the replacement has been secured."
    )


@transaction.atomic

@transaction.atomic
def close_expired_coverage_sessions(*, moment=None) -> int:
    """
    Process coverage boundaries and continuation workflows.

    Important:
      - 20:45 / 08:45 are prompt times.
      - 21:00 / 09:00 are hard boundaries.
      - The old CoverageSession is never extended.
    """
    if moment is None:
        moment = timezone.localtime()

    closed_count = 0

    # ---------------------------------------------------------------
    # 1. Expire OPEN assignments whose sign-in deadline has passed.
    # ---------------------------------------------------------------
    open_sessions = CoverageSession.objects.select_for_update().filter(
        status=CoverageSession.Status.OPEN,
        sign_in_deadline_at__isnull=False,
        sign_in_deadline_at__lte=moment,
    ).select_related(
        "moderator",
        "player",
    )

    for session in open_sessions:
        session.status = CoverageSession.Status.EXPIRED
        session.signed_out_at = None
        session.closure_reason = CoverageSession.ClosureReason.AUTOMATIC

        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "closure_reason",
                "updated_at",
            ]
        )

        moderator_name = (
            session.moderator.get_full_name()
            or session.moderator.username
        )

        title = "Coverage Sign-In Missed"

        message = (
            f"Attention: {moderator_name} failed to sign in to cover "
            f"{session.player} within the required 15-minute period. "
            "The coverage assignment has expired. The Player is available "
            "for the normal coverage assignment workflow."
        )

        _notify_management_team(
            title=title,
            message=message,
            alert_level=Notification.AlertLevel.CRITICAL,
        )

        _email_management_team(
            subject=title,
            message=(
                f"Hello,\n\n{message}\n\n"
                "Regards,\nSansfrontieres Chat Moderation"
            ),
        )

        closed_count += 1

    # ---------------------------------------------------------------
    # 2. Prompt active sessions during the 15-minute window.
    #
    # Day:     08:45 -> 09:00
    # Evening: 20:45 -> 21:00
    # ---------------------------------------------------------------
    prompt_sessions = CoverageSession.objects.select_for_update().filter(
        status=CoverageSession.Status.ACTIVE,
        scheduled_close_at__isnull=False,
        scheduled_close_at__gt=moment,
        scheduled_close_at__lte=moment + timedelta(minutes=15),
        continuation_prompted_at__isnull=True,
    ).select_related(
        "moderator",
        "player",
    )

    for session in prompt_sessions:
        prompt_coverage_continuation(
            session=session,
            moment=moment,
        )

    # ---------------------------------------------------------------
    # 3. Process CONTINUATION_PENDING sessions whose hard boundary
    #    has arrived.
    # ---------------------------------------------------------------
    pending_sessions = CoverageSession.objects.select_for_update().filter(
        status=CoverageSession.Status.CONTINUATION_PENDING,
        scheduled_close_at__isnull=False,
        scheduled_close_at__lte=moment,
    ).select_related(
        "moderator",
        "player",
    )

    for session in pending_sessions:
        response = (session.continuation_response or "").strip().upper()

        # -----------------------------------------------------------
        # 3A. NO or no response -> end old session and require report.
        # -----------------------------------------------------------
        if response != "YES":
            signed_out_at = session.scheduled_close_at

            session.status = CoverageSession.Status.AWAITING_REPORT
            session.signed_out_at = signed_out_at
            session.closure_reason = CoverageSession.ClosureReason.AUTOMATIC
            session.continuation_deadline_at = None

            session.save(
                update_fields=[
                    "status",
                    "signed_out_at",
                    "closure_reason",
                    "continuation_deadline_at",
                    "updated_at",
                ]
            )

            create_report_compliance(
                session=session,
                signed_out_at=signed_out_at,
            )

            moderator_name = (
                session.moderator.get_full_name()
                or session.moderator.username
            )

            if response == "NO":
                title = "Coverage Session Ended"
                moderator_message = (
                    f"You chose NO to continue covering {session.player}. "
                    "You have been signed out and must submit your "
                    "End-of-Session Report."
                )
                management_message = (
                    f"{moderator_name} chose NO to continue covering "
                    f"{session.player}. The current session has ended at "
                    f"{signed_out_at.strftime('%d %B %Y at %H:%M')}. "
                    "The Player is available to the normal coverage "
                    "assignment workflow."
                )
            else:
                title = "Coverage Continuation Timed Out"
                moderator_message = (
                    f"You did not respond to the continuation prompt for "
                    f"{session.player} before the hard boundary. You have "
                    "been automatically signed out and must submit your "
                    "End-of-Session Report."
                )
                management_message = (
                    f"{moderator_name} did not respond to the continuation "
                    f"prompt for {session.player} before the hard boundary. "
                    f"The current session ended automatically at "
                    f"{signed_out_at.strftime('%d %B %Y at %H:%M')}. "
                    "The Player is available to the normal coverage "
                    "assignment workflow."
                )

            _notify_moderator(
                moderator=session.moderator,
                title=title,
                message=moderator_message,
                alert_level=Notification.AlertLevel.CRITICAL,
            )

            _notify_management_team(
                title=title,
                message=management_message,
                alert_level=Notification.AlertLevel.CRITICAL,
            )

            _email_management_team(
                subject=title,
                message=(
                    f"Hello,\n\n{management_message}\n\n"
                    "Regards,\nSansfrontieres Chat Moderation"
                ),
            )

            closed_count += 1
            continue

        # -----------------------------------------------------------
        # 3B. YES + Evening/Night -> close old session and immediately
        #     create a NEW Night session.
        # -----------------------------------------------------------
        if session.session_type == CoverageSession.SessionType.NIGHT:
            signed_out_at = session.scheduled_close_at

            session.status = CoverageSession.Status.COMPLETED
            session.signed_out_at = signed_out_at
            session.closure_reason = CoverageSession.ClosureReason.NORMAL
            session.continuation_deadline_at = None

            session.save(
                update_fields=[
                    "status",
                    "signed_out_at",
                    "closure_reason",
                    "continuation_deadline_at",
                    "updated_at",
                ]
            )

            try:
                new_session = _create_continuation_session(
                    previous_session=session,
                    moment=moment,
                )
            except ValidationError as exc:
                # The old session is safely closed. If a new session
                # cannot be created, management is notified so the
                # normal assignment workflow can resolve coverage.
                moderator_name = (
                    session.moderator.get_full_name()
                    or session.moderator.username
                )

                title = "Coverage Continuation Requires Attention"

                message = (
                    f"{moderator_name}'s evening continuation for "
                    f"{session.player} reached the 21:00 hard boundary, "
                    f"but a new session could not be created automatically: "
                    f"{exc}. The Player is available for the normal "
                    "coverage assignment workflow."
                )

                _notify_management_team(
                    title=title,
                    message=message,
                    alert_level=Notification.AlertLevel.CRITICAL,
                )

                _email_management_team(
                    subject=title,
                    message=(
                        f"Hello,\n\n{message}\n\n"
                        "Regards,\nSansfrontieres Chat Moderation"
                    ),
                )

                closed_count += 1
                continue

            closed_count += 1
            continue

        # -----------------------------------------------------------
        # 3C. YES + Day should already be AWAITING_REPORT after the
        #     Moderator's response. This branch is a safety fallback.
        # -----------------------------------------------------------
        session.status = CoverageSession.Status.AWAITING_REPORT
        session.signed_out_at = session.scheduled_close_at
        session.closure_reason = CoverageSession.ClosureReason.NORMAL
        session.continuation_deadline_at = None

        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "closure_reason",
                "continuation_deadline_at",
                "updated_at",
            ]
        )

        create_report_compliance(
            session=session,
            signed_out_at=session.signed_out_at,
        )

        closed_count += 1

    # ---------------------------------------------------------------
    # 4. Safety handling for ACTIVE sessions that somehow reached the
    #    hard boundary without receiving a prompt.
    # ---------------------------------------------------------------
    missed_prompt_sessions = CoverageSession.objects.select_for_update().filter(
        status=CoverageSession.Status.ACTIVE,
        scheduled_close_at__isnull=False,
        scheduled_close_at__lte=moment,
        continuation_prompted_at__isnull=True,
    ).select_related(
        "moderator",
        "player",
    )

    for session in missed_prompt_sessions:
        signed_out_at = session.scheduled_close_at

        session.status = CoverageSession.Status.AWAITING_REPORT
        session.signed_out_at = signed_out_at
        session.closure_reason = CoverageSession.ClosureReason.AUTOMATIC

        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "closure_reason",
                "updated_at",
            ]
        )

        create_report_compliance(
            session=session,
            signed_out_at=signed_out_at,
        )

        moderator_name = (
            session.moderator.get_full_name()
            or session.moderator.username
        )

        title = "Coverage Boundary Reached"

        message = (
            f"{moderator_name}'s coverage session for {session.player} "
            f"reached its hard boundary at "
            f"{signed_out_at.strftime('%d %B %Y at %H:%M')} without a "
            "continuation prompt being recorded. The Moderator has been "
            "signed out and an End-of-Session Report is required. The "
            "Player is available to the normal coverage assignment workflow."
        )

        _notify_moderator(
            moderator=session.moderator,
            title=title,
            message=(
                f"Your coverage session for {session.player} reached its "
                "hard boundary. You have been signed out automatically "
                "and must submit your End-of-Session Report."
            ),
            alert_level=Notification.AlertLevel.CRITICAL,
        )

        _notify_management_team(
            title=title,
            message=message,
            alert_level=Notification.AlertLevel.CRITICAL,
        )

        _email_management_team(
            subject=title,
            message=(
                f"Hello,\n\n{message}\n\n"
                "Regards,\nSansfrontieres Chat Moderation"
            ),
        )

        closed_count += 1

    # ---------------------------------------------------------------
    # 5. Existing replacement-request boundary handling.
    #    This remains separate from continuation.
    # ---------------------------------------------------------------
    replacement_sessions = CoverageSession.objects.select_for_update().filter(
        status=CoverageSession.Status.REPLACEMENT_REQUESTED,
        scheduled_close_at__isnull=False,
        scheduled_close_at__lte=moment,
    )

    for session in replacement_sessions:
        session.status = CoverageSession.Status.AWAITING_REPORT
        session.signed_out_at = session.scheduled_close_at
        session.closure_reason = CoverageSession.ClosureReason.AUTOMATIC
        session.replacement_requested_at = None

        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "closure_reason",
                "replacement_requested_at",
                "updated_at",
            ]
        )

        create_report_compliance(
            session=session,
            signed_out_at=session.signed_out_at,
        )

        closed_count += 1

    return closed_count



@transaction.atomic
def get_uncovered_players(*, moment=None):
    if moment is None:
        moment = timezone.localtime()

    session_type = get_session_type(moment)
    operating_date = get_operating_date(moment, session_type)

    covered_player_ids = set(
        CoverageSession.objects.filter(
            operating_date=operating_date,
            session_type=session_type,
            status__in=(
                CoverageSession.Status.ACTIVE,
                CoverageSession.Status.REPLACEMENT_REQUESTED,
                CoverageSession.Status.HANDOVER,
            ),
        ).values_list("player_id", flat=True)
    )

    open_sessions = CoverageSession.objects.filter(
        operating_date=operating_date,
        session_type=session_type,
        status=CoverageSession.Status.OPEN,
        sign_in_deadline_at__gt=moment,
    ).values_list("player_id", flat=True)

    covered_player_ids.update(open_sessions)

    return Player.objects.filter(
        status=Player.Status.ACTIVE,
    ).exclude(
        id__in=covered_player_ids
    ).order_by("player_number")


def monitor_coverage_checkpoint(*, moment=None):
    if moment is None:
        moment = timezone.localtime()

    session_type = get_session_type(moment)
    operating_date = get_operating_date(moment, session_type)

    active_players = Player.objects.filter(
        status=Player.Status.ACTIVE,
    ).order_by("player_number")

    uncovered_players = list(
        get_uncovered_players(moment=moment)
    )

    uncovered_ids = {player.id for player in uncovered_players}

    covered_count = active_players.exclude(
        id__in=uncovered_ids
    ).count()

    return {
        "checkpoint_at": moment,
        "session_type": session_type,
        "operating_date": operating_date,
        "total_active_players": active_players.count(),
        "covered_players": covered_count,
        "uncovered_players": len(uncovered_players),
        "uncovered_player_list": uncovered_players,
    }

@transaction.atomic
def manager_override_end_coverage(
    *,
    session: CoverageSession,
    manager: User,
    moment=None,
) -> CoverageSession:
    if moment is None:
        moment = timezone.localtime()

    if manager.role not in (
        User.Role.ADMIN,
        User.Role.DIRECTOR,
        User.Role.MANAGER,
    ):
        raise ValidationError(
            "Only a Manager, Director, or System Administrator can override coverage sign-out."
        )

    if session.status not in ACTIVE_STATUSES:
        raise ValidationError(
            "Only an active coverage session can be ended by Manager override."
        )

    session.status = CoverageSession.Status.AWAITING_REPORT
    session.signed_out_at = moment
    session.closure_reason = CoverageSession.ClosureReason.MANAGER_OVERRIDE

    session.save(
        update_fields=[
            "status",
            "signed_out_at",
            "closure_reason",
            "updated_at",
        ]
    )

    create_report_compliance(
        session=session,
        signed_out_at=session.signed_out_at,
    )

    return session






