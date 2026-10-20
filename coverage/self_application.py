import os
from datetime import timedelta
from django.conf import settings
from django.core.mail import send_mass_mail
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone

from accounts.models import StaffProfile, User
from coverage.models import CoverageApplication, CoverageSession, EndOfSessionReport
from players.models import Player
from notifications.models import Notification

# Statuses that mean a moderator is still occupied.
# HANDOVER and AWAITING_REPORT remain here because the outgoing moderator
# still has an outstanding coverage/report obligation.
ACTIVE_COVERAGE_STATUSES = (
    CoverageSession.Status.OPEN,
    CoverageSession.Status.ACTIVE,
    CoverageSession.Status.CONTINUATION_PENDING,
    CoverageSession.Status.REPLACEMENT_REQUESTED,
    CoverageSession.Status.HANDOVER,
    CoverageSession.Status.AWAITING_REPORT,
)

# Statuses that mean a player is already covered.
# HANDOVER is deliberately excluded because replacement temporarily allows:
#   old session = HANDOVER
#   new session = OPEN
#
# This mirrors the unique_active_coverage_per_player database constraint.
PLAYER_COVERAGE_STATUSES = (
    CoverageSession.Status.OPEN,
    CoverageSession.Status.ACTIVE,
    CoverageSession.Status.CONTINUATION_PENDING,
    CoverageSession.Status.REPLACEMENT_REQUESTED,
)

def _week_start(moment):
    local = timezone.localtime(moment)
    return (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

def get_chats_this_week(moderator, moment=None):
    moment = moment or timezone.localtime()
    start = _week_start(moment)
    from coverage.models import EndOfSessionReport
    total = (
        EndOfSessionReport.objects.filter(
            moderator=moderator,
            submitted_at__gte=start,
            submitted_at__lte=moment,
        ).aggregate(total=Sum("chats_responded"))["total"]
        or 0
    )
    return int(total)

def moderator_is_eligible(moderator, moment=None):
    if moderator is None or getattr(moderator, "role", None) != "MODERATOR" or not moderator.is_active:
        return False
    try:
        profile = moderator.staff_profile
    except StaffProfile.DoesNotExist:
        return False

    if profile.status != StaffProfile.Status.ACTIVE:
        return False

    # Exclude moderators with active/covering sessions
    if CoverageSession.objects.filter(
        moderator=moderator, status__in=ACTIVE_COVERAGE_STATUSES
    ).exists():
        return False

    # Also exclude moderators who owe an End-of-Session Report
    if CoverageSession.objects.filter(
        moderator=moderator, status=CoverageSession.Status.AWAITING_REPORT
    ).exists():
        return False

    return True

def _new_coverage_players(moment):
    covered_ids = set(
        CoverageSession.objects.filter(
            status__in=PLAYER_COVERAGE_STATUSES,
        ).values_list("player_id", flat=True)
    )

    return (
        Player.objects
        .filter(status=Player.Status.ACTIVE)
        .exclude(id__in=covered_ids)
        .order_by("player_number")
    )

def _replacement_players(moment):
    return CoverageSession.objects.filter(
        # Replacement requested (new style: ACTIVE + flag)
        # OR legacy REPLACEMENT_REQUESTED status
        (
            Q(status=CoverageSession.Status.ACTIVE, replacement_requested_at__isnull=False)
            | Q(status=CoverageSession.Status.REPLACEMENT_REQUESTED)
        ),
        player__status=Player.Status.ACTIVE,
    ).select_related("player", "moderator").order_by("player__player_number", "id")

def get_coverage_opportunities(moderator, moment=None):
    moment = moment or timezone.localtime()
    if not moderator_is_eligible(moderator, moment):
        return {
            "eligible": False,
            "weekly_chats": 0,
            "new_players": Player.objects.none(),
            "replacement_sessions": CoverageSession.objects.none(),
        }
    return {
        "eligible": True,
        "weekly_chats": get_chats_this_week(moderator, moment),
        "new_players": _new_coverage_players(moment),
        "replacement_sessions": _replacement_players(moment),
    }

def _notify(recipient, title, message, alert_level="INFO"):
    Notification.objects.create(
        recipient=recipient,
        notification_type=Notification.NotificationType.GENERAL,
        title=title,
        message=message,
        alert_level=alert_level,
    )

def _management_users():
    return User.objects.filter(
        role__in=("ADMIN", "DIRECTOR", "MANAGER"), is_active=True
    ).exclude(email="")

def _email_users(users, subject, message):
    recipients = [user.email for user in users if getattr(user, "email", None)]
    if not recipients:
        return
    send_mass_mail(
        ((subject, message, getattr(settings, "DEFAULT_FROM_EMAIL", None), [email]) for email in recipients),
        fail_silently=True,
    )

def _assign_new_coverage_locked(application, moment):
    from coverage.services import get_session_type, get_operating_date
    moderator, player = application.moderator, application.player
    session_type = get_session_type(moment)
    operating_date = get_operating_date(moment, session_type)

    if CoverageSession.objects.filter(
        player=player, operating_date=operating_date, session_type=session_type, status__in=PLAYER_COVERAGE_STATUSES
    ).exists():
        return None

    return CoverageSession.objects.create(
        moderator=moderator,
        player=player,
        operating_date=operating_date,
        session_type=session_type,
        status=CoverageSession.Status.OPEN,
    )

def _assign_replacement_locked(application, replacement_session, moment):
    """
    DEPRECATED SHIM.

    This function historically duplicated replacement handover logic that
    now lives in coverage.services.assign_replacement(). It is retained as
    a delegating shim so existing callers do not break, but all logic is
    unified in the service function to avoid divergent behavior.
    """
    from coverage.services import assign_replacement
    try:
        return assign_replacement(
            session=replacement_session,
            replacement_moderator=application.moderator,
            moment=moment,
        )
    except Exception:
        return None


def _competition_seconds():
    """
    Length of the small competition window used to handle applicants
    arriving at approximately the same time.

    Default: 3 seconds.
    """

    raw = os.environ.get("SELF_APPLICATION_COMPETITION_SECONDS", "3")

    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 3.0

    return max(0.0, min(value, 30.0))


def _select_winning_application(player, opportunity_type):
    """
    Select the highest-ranked pending application.

    Ranking:
        1. Highest chats_this_week
        2. Earliest applied_at
        3. Lowest id
    """
    return (
        CoverageApplication.objects
        .select_related("moderator", "player")
        .filter(
            player=player,
            opportunity_type=opportunity_type,
            status=CoverageApplication.Status.PENDING,
        )
        .order_by(
            "-chats_this_week",
            "applied_at",
            "id",
        )
        .first()
    )


def _mark_losing_applications(player, opportunity_type, winner):
    """
    Mark all remaining pending applications as LOST.
    """
    losing = (
        CoverageApplication.objects
        .filter(
            player=player,
            opportunity_type=opportunity_type,
            status=CoverageApplication.Status.PENDING,
        )
        .exclude(pk=winner.pk)
    )

    losing.update(status=CoverageApplication.Status.LOST)


def apply_for_player(
    moderator,
    player_id,
    opportunity_type=None,
    moment=None,
):
    """
    Submit and resolve a moderator coverage application.

    Compatible API:

        apply_for_player(
            moderator,
            player_id,
            opportunity_type,
            moment,
        )

    Competition:

        - Snapshot weekly chats when application is created.
        - Allow competing applications to exist.
        - Highest weekly chat snapshot wins.
        - Earliest application wins ties.
        - Exactly one coverage session is created.
        - Other applications become LOST.

    The optional `moment` argument exists so the test suite can
    control the date/time used for the weekly-chat snapshot.
    """

    import time
    from django.contrib.auth import get_user_model
    from django.db import transaction

    User = get_user_model()

    # --------------------------------------------------------
    # Resolve player.
    # --------------------------------------------------------

    try:
        player_pk = int(player_id)
    except (TypeError, ValueError):
        raise ValueError("Invalid player ID.")

    player_model = (
        CoverageApplication
        ._meta
        .get_field("player")
        .remote_field
        .model
    )

    # --------------------------------------------------------
    # Default opportunity.
    # --------------------------------------------------------

    if opportunity_type is None:
        opportunity_type = CoverageApplication.OpportunityType.NEW

    valid_opportunities = {
        CoverageApplication.OpportunityType.NEW,
        CoverageApplication.OpportunityType.REPLACEMENT,
    }

    if opportunity_type not in valid_opportunities:
        raise ValueError(
            f"Unsupported opportunity type: {opportunity_type}"
        )

    # ========================================================
    # PHASE 1 ? CREATE / REUSE APPLICATION
    # ========================================================

    with transaction.atomic():

        locked_moderator = (
            User.objects
            .select_for_update()
            .get(pk=moderator.pk)
        )

        locked_player = (
            player_model.objects
            .select_for_update()
            .get(pk=player_pk)
        )

        # ----------------------------------------------------
        # Idempotency must be checked BEFORE eligibility.
        #
        # A successful application normally makes the moderator
        # ineligible immediately because they now have an active
        # coverage session. A repeated request must therefore
        # return the existing application instead of raising
        # "not eligible".
        # ----------------------------------------------------

        existing = (
            CoverageApplication.objects
            .select_for_update()
            .filter(
                moderator=locked_moderator,
                player=locked_player,
                opportunity_type=opportunity_type,
            )
            .order_by("-applied_at", "-id")
            .first()
        )

        if existing is not None:
            # A previously completed application is fully
            # idempotent: return it and its resulting session.
            if existing.status == CoverageApplication.Status.WON:
                return (
                    existing,
                    existing.resulting_session,
                    False,
                )

            # A pending application belongs to the current
            # competition and must be reused rather than
            # duplicated.
            if existing.status == CoverageApplication.Status.PENDING:
                application = existing

            # LOST/CANCELLED applications are not reusable.
            else:
                existing = None

        if existing is None:
            # ------------------------------------------------
            # IMPORTANT:
            # moderator_is_eligible() returns BOOL.
            # Do NOT unpack it.
            # ------------------------------------------------

            if not moderator_is_eligible(locked_moderator):
                raise ValueError(
                    "Moderator is not eligible to apply for coverage."
                )

            # A NEW opportunity is only valid while the player
            # is uncovered. Check this before creating an application.
            if opportunity_type == CoverageApplication.OpportunityType.NEW:
                already_covered = (
                    CoverageSession.objects
                    .filter(
                        player=locked_player,
                        status__in=PLAYER_COVERAGE_STATUSES,
                    )
                    .exists()
                )

                if already_covered:
                    raise ValueError("This player is already covered.")

            snapshot_time = moment or timezone.localtime()

            weekly_chats = get_chats_this_week(
                locked_moderator,
                snapshot_time,
            )

            application = CoverageApplication.objects.create(
                player=locked_player,
                moderator=locked_moderator,
                opportunity_type=opportunity_type,
                chats_this_week=weekly_chats,
                status=CoverageApplication.Status.PENDING,
            )

    # ========================================================
    # PHASE 2 ? COMPETITION WINDOW
    # ========================================================

    raw_window = os.environ.get(
        "SELF_APPLICATION_COMPETITION_SECONDS",
        "3",
    )

    try:
        competition_window = float(raw_window)
    except (TypeError, ValueError):
        competition_window = 3.0

    competition_window = max(
        0.0,
        min(competition_window, 30.0),
    )

    if competition_window:
        time.sleep(competition_window)

    # ========================================================
    # PHASE 3 ? FINAL AWARD
    # ========================================================

    with transaction.atomic():

        locked_player = (
            player_model.objects
            .select_for_update()
            .get(pk=player_pk)
        )

        application = (
            CoverageApplication.objects
            .select_for_update()
            .get(pk=application.pk)
        )

        # ----------------------------------------------------
        # Somebody already resolved this competition.
        # ----------------------------------------------------

        if application.status != CoverageApplication.Status.PENDING:

            if application.status == CoverageApplication.Status.WON:
                return (
                    application,
                    application.resulting_session,
                    False,
                )

            if application.status == CoverageApplication.Status.LOST:
                raise ValueError(
                    "The coverage opportunity was awarded to another moderator."
                )

            raise ValueError(
                "This coverage application is no longer available."
            )

        # ====================================================
        # NEW COVERAGE
        # ====================================================

        if opportunity_type == CoverageApplication.OpportunityType.NEW:

            # ------------------------------------------------
            # The player row is locked above. From this point
            # onward this transaction is the sole authority for
            # deciding whether a NEW assignment can be created.
            # ------------------------------------------------

            # ------------------------------------------------
            # Check whether another request already assigned
            # this player.
            # ------------------------------------------------

            existing_session = (
                CoverageSession.objects
                .filter(
                    player=locked_player,
                    status__in=PLAYER_COVERAGE_STATUSES,
                )
                .order_by("-created_at", "-id")
                .first()
            )

            if existing_session is not None:

                application.status = CoverageApplication.Status.LOST
                application.save(update_fields=["status"])

                return (
                    application,
                    existing_session,
                    False,
                )

            # ------------------------------------------------
            # LOCK + LOAD ALL APPLICATIONS
            # ------------------------------------------------

            candidates = list(
                CoverageApplication.objects
                .select_related("moderator")
                .select_for_update()
                .filter(
                    player=locked_player,
                    opportunity_type=CoverageApplication.OpportunityType.NEW,
                    status=CoverageApplication.Status.PENDING,
                )
                .order_by(
                    "-chats_this_week",
                    "applied_at",
                    "id",
                )
            )

            winner = None

            # ------------------------------------------------
            # Validate candidates at award time.
            # ------------------------------------------------

            for candidate in candidates:

                if not moderator_is_eligible(
                    candidate.moderator
                ):
                    candidate.status = (
                        CoverageApplication.Status.LOST
                    )
                    candidate.save(
                        update_fields=["status"]
                    )
                    continue

                already_assigned = (
                    CoverageSession.objects
                    .filter(
                        moderator=candidate.moderator,
                        status__in=ACTIVE_COVERAGE_STATUSES,
                    )
                    .exists()
                )

                if already_assigned:
                    candidate.status = (
                        CoverageApplication.Status.LOST
                    )
                    candidate.save(
                        update_fields=["status"]
                    )
                    continue

                winner = candidate
                break

            # ------------------------------------------------
            # Nothing valid.
            # ------------------------------------------------

            if winner is None:

                application.refresh_from_db()

                return (
                    application,
                    None,
                    False,
                )

            # ------------------------------------------------
            # Create the ONE assignment.
            # ------------------------------------------------

            from coverage.services import get_session_type, get_operating_date

            session_type = get_session_type(moment)
            operating_date = get_operating_date(moment, session_type)

            # Self-application winners receive an ACTIVE assignment
            # immediately. Coverage starts at the acceptance time.
            session = CoverageSession.objects.create(
                player=locked_player,
                moderator=winner.moderator,
                operating_date=operating_date,
                signed_in_at=moment,
                status=CoverageSession.Status.ACTIVE,
                session_type=session_type,
                sign_in_deadline_at=None,
            )

            # ------------------------------------------------
            # Winner.
            # ------------------------------------------------

            winner.status = CoverageApplication.Status.WON
            winner.resulting_session = session

            winner.save(
                update_fields=[
                    "status",
                    "resulting_session",
                ]
            )

            # ------------------------------------------------
            # Losers.
            # ------------------------------------------------

            CoverageApplication.objects.filter(
                player=locked_player,
                opportunity_type=CoverageApplication.OpportunityType.NEW,
                status=CoverageApplication.Status.PENDING,
            ).exclude(
                pk=winner.pk,
            ).update(
                status=CoverageApplication.Status.LOST,
            )

            # ------------------------------------------------
            # Notify management after successful self-assignment.
            # ------------------------------------------------

            management_users = list(_management_users())

            winner_name = (
                winner.moderator.get_full_name()
                or winner.moderator.username
            )

            management_message = (
                f"{winner_name} has been assigned to cover "
                f"Player {locked_player.player_number}. "
                f"Coverage session {session.session_code} "
                "has been created successfully."
            )

            for recipient in management_users:
                _notify(
                    recipient,
                    "New Coverage Assignment",
                    management_message,
                    Notification.AlertLevel.IMPORTANT,
                )

            _email_users(
                management_users,
                "New Coverage Assignment",
                (
                    "Hello,\n\n"
                    f"{management_message}\n\n"
                    "Regards,\n\n"
                    "Sansfrontieres Chat Moderation"
                ),
            )

            # [self_apply_new_player_disclosure] create the credential
            # disclosure for the self-applied moderator.
            try:
                from players.models import CredentialDisclosure
                CredentialDisclosure.objects.get_or_create(
                    moderator=winner.moderator,
                    player=locked_player,
                    coverage_session=session,
                    defaults={'disclosed_at': moment},
                )
            except Exception:
                pass

            return (
                winner,
                session,
                True,
            )

        # ====================================================
        # REPLACEMENT
        # ====================================================

        replacement_session = (
            CoverageSession.objects
            .select_for_update()
            .filter(
                player=locked_player,
            )
            .filter(
                # New style: ACTIVE + replacement flag.
                # Legacy: REPLACEMENT_REQUESTED status.
                (
                    Q(status=CoverageSession.Status.ACTIVE, replacement_requested_at__isnull=False)
                    | Q(status=CoverageSession.Status.REPLACEMENT_REQUESTED)
                ),
            )
            .order_by("-created_at", "-id")
            .first()
        )

        if replacement_session is None:

            application.status = CoverageApplication.Status.LOST
            application.save(update_fields=["status"])

            return (
                application,
                None,
                False,
            )

        candidates = list(
            CoverageApplication.objects
            .select_related("moderator")
            .select_for_update()
            .filter(
                player=locked_player,
                opportunity_type=CoverageApplication.OpportunityType.REPLACEMENT,
                status=CoverageApplication.Status.PENDING,
            )
            .order_by(
                "-chats_this_week",
                "applied_at",
                "id",
            )
        )

        winner = None

        for candidate in candidates:

            if not moderator_is_eligible(
                candidate.moderator
            ):
                candidate.status = CoverageApplication.Status.LOST
                candidate.save(update_fields=["status"])
                continue

            already_assigned = (
                CoverageSession.objects
                .filter(
                    moderator=candidate.moderator,
                    status__in=ACTIVE_COVERAGE_STATUSES,
                )
                .exists()
            )

            if already_assigned:
                candidate.status = CoverageApplication.Status.LOST
                candidate.save(update_fields=["status"])
                continue

            winner = candidate
            break

        if winner is None:

            application.refresh_from_db()

            return (
                application,
                None,
                False,
            )

        outgoing_moderator = replacement_session.moderator

        from coverage.services import create_report_compliance

        # A moderator-driven replacement enters HANDOVER while
        # the replacement assignment is being completed.
        replacement_session.status = CoverageSession.Status.HANDOVER
        replacement_session.signed_out_at = moment
        replacement_session.closure_reason = CoverageSession.ClosureReason.REPLACED
        replacement_session.replacement_moderator = winner.moderator

        replacement_session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "closure_reason",
                "replacement_moderator",
                "updated_at",
            ]
        )

        create_report_compliance(
            session=replacement_session,
            signed_out_at=replacement_session.signed_out_at,
        )

        # Self-application replacement winners receive an ACTIVE
        # assignment immediately. Coverage starts at the acceptance time.
        new_session = CoverageSession(
            player=locked_player,
            moderator=winner.moderator,
            operating_date=replacement_session.operating_date,
            session_type=replacement_session.session_type,
            signed_in_at=moment,
            sign_in_deadline_at=None,
            scheduled_close_at=(replacement_session.scheduled_close_at if replacement_session.scheduled_close_at and replacement_session.scheduled_close_at > moment else None),
            status=CoverageSession.Status.ACTIVE,
            notes=f"Replacement for coverage session {replacement_session.id}.",
        )

        new_session.full_clean()
        new_session.save()

        replacement_session.replacement_session = new_session
        replacement_session.save(
            update_fields=["replacement_session", "updated_at"]
        )

        # Disclose the player's login credentials to the incoming moderator.
        from players.models import CredentialDisclosure
        CredentialDisclosure.objects.create(
            moderator=winner.moderator,
            player=locked_player,
            coverage_session=new_session,
        )

        # [self_apply_new_player_disclosure] create the credential
        # disclosure for the self-applied moderator.
        try:
            from players.models import CredentialDisclosure
            CredentialDisclosure.objects.get_or_create(
                moderator=winner.moderator,
                player=locked_player,
                coverage_session=new_session,
                defaults={'disclosed_at': moment},
            )
        except Exception:
            pass

        winner.status = CoverageApplication.Status.WON
        winner.resulting_session = new_session

        winner.save(
            update_fields=[
                "status",
                "resulting_session",
            ]
        )

        CoverageApplication.objects.filter(
            player=locked_player,
            opportunity_type=CoverageApplication.OpportunityType.REPLACEMENT,
            status=CoverageApplication.Status.PENDING,
        ).exclude(
            pk=winner.pk,
        ).update(
            status=CoverageApplication.Status.LOST,
        )

        # ------------------------------------------------
        # Notify management after successful replacement.
        # ------------------------------------------------

        management_users = list(_management_users())

        incoming_name = (
            winner.moderator.get_full_name()
            or winner.moderator.username
        )

        outgoing_name = (
            outgoing_moderator.get_full_name()
            or outgoing_moderator.username
        )

        management_message = (
            f"{incoming_name} has been assigned to replace "
            f"{outgoing_name} for Player {locked_player.player_number}. "
            f"Replacement coverage session {new_session.session_code} "
            "has been created successfully."
        )

        for recipient in management_users:
            _notify(
                recipient,
                "Replacement Coverage Assigned",
                management_message,
                Notification.AlertLevel.IMPORTANT,
            )

        _email_users(
            management_users,
            "Replacement Coverage Assigned",
            (
                "Hello,\n\n"
                f"{management_message}\n\n"
                "Regards,\n\n"
                "Sansfrontieres Chat Moderation"
            ),
        )

        # Notify the outgoing moderator.
        _notify(
            outgoing_moderator,
            "Replacement Moderator Assigned",
            (
                f"Thank you for covering Player "
                f"{locked_player.player_number}. "
                f"{incoming_name} has successfully been assigned "
                "as your replacement. Your coverage session is now "
                "in handover and your End-of-Session Report must "
                "be completed."
            ),
            Notification.AlertLevel.IMPORTANT,
        )

        # Notify the incoming moderator.
        # Self-application replacement winners are already ACTIVE
        # and automatically signed in at the moment of award.
        _notify(
            winner.moderator,
            "Replacement Coverage Active",
            (
                f"You have successfully been assigned as the "
                f"replacement Moderator for Player "
                f"{locked_player.player_number}. "
                "You have been automatically signed in and your "
                "replacement coverage session is now ACTIVE. "
                "You may continue coverage immediately."
            ),
            Notification.AlertLevel.IMPORTANT,
        )

        return (
            winner,
            new_session,
            True,
        )


