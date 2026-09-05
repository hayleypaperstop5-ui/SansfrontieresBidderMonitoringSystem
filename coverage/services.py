from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from players.models import Player

from .models import CoverageSession
from .session_times import (
    get_operating_date,
    get_scheduled_close_at,
    get_session_type,
)


ACTIVE_STATUSES = (
    CoverageSession.Status.ACTIVE,
    CoverageSession.Status.REPLACEMENT_REQUESTED,
    CoverageSession.Status.HANDOVER,
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

    return session


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
        status__in=ACTIVE_STATUSES,
    ).exists():
        raise ValidationError(
            "The replacement Moderator already has an active Player coverage session."
        )

    session.status = CoverageSession.Status.COMPLETED
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

    new_session = CoverageSession(
        player=session.player,
        moderator=replacement_moderator,
        operating_date=session.operating_date,
        session_type=session.session_type,
        signed_in_at=moment,
        scheduled_close_at=session.scheduled_close_at,
        status=CoverageSession.Status.ACTIVE,
        notes=f"Replacement for coverage session {session.id}.",
    )

    new_session.full_clean()
    new_session.save()

    session.replacement_session = new_session
    session.save(update_fields=["replacement_session", "updated_at"])

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

    if session.status != CoverageSession.Status.ACTIVE:
        raise ValidationError(
            "Only an active coverage session can be signed out normally."
        )

    raise ValidationError(
        "You cannot sign out while covering this Player. "
        "Request a replacement first, and sign out once the replacement has been secured."
    )


@transaction.atomic
def close_expired_coverage_sessions(*, moment=None) -> int:
    if moment is None:
        moment = timezone.localtime()

    sessions = CoverageSession.objects.select_for_update().filter(
        status__in=ACTIVE_STATUSES,
        scheduled_close_at__isnull=False,
        scheduled_close_at__lte=moment,
    )

    closed_count = 0

    for session in sessions:
        session.status = CoverageSession.Status.COMPLETED
        session.signed_out_at = session.scheduled_close_at
        session.closure_reason = CoverageSession.ClosureReason.AUTOMATIC
        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "closure_reason",
                "updated_at",
            ]
        )
        closed_count += 1

    return closed_count


def get_uncovered_players(*, moment=None):
    if moment is None:
        moment = timezone.localtime()

    session_type = get_session_type(moment)
    operating_date = get_operating_date(moment, session_type)

    covered_player_ids = CoverageSession.objects.filter(
        operating_date=operating_date,
        session_type=session_type,
        status__in=ACTIVE_STATUSES,
    ).values_list("player_id", flat=True)

    return Player.objects.filter(
        status=Player.Status.ACTIVE,
    ).exclude(
        id__in=covered_player_ids,
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

    session.status = CoverageSession.Status.COMPLETED
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

    return session
