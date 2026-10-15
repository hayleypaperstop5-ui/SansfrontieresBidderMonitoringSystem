from datetime import datetime, time, date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from accounts.models import User
from coverage.models import EndOfSessionReport

from .models import BonusAward, ChatBonusTier


QUALIFYING_WINDOW_HOURS = 24


def get_applicable_bonus_tier(*, chats_counted, bonus_date, qualifying_window_hours=24):
    if chats_counted < 0:
        raise ValidationError("Chats counted cannot be negative.")

    if not bonus_date:
        raise ValidationError("A valid bonus date is required.")

    if qualifying_window_hours < 1:
        raise ValidationError("Qualifying window must be at least 1 hour.")

    tiers = (
        ChatBonusTier.objects
        .filter(
            active=True,
            qualifying_window_hours=qualifying_window_hours,
            minimum_chats__lte=chats_counted,
        )
        .filter(
            models.Q(maximum_chats__isnull=True)
            | models.Q(maximum_chats__gte=chats_counted)
        )
        .filter(
            models.Q(effective_from__isnull=True)
            | models.Q(effective_from__lte=bonus_date)
        )
        .order_by("-effective_from", "-minimum_chats", "-id")
    )

    return tiers.first()


def get_reports_within_window(
    *,
    moderator,
    window_end,
    window_hours=QUALIFYING_WINDOW_HOURS,
    player=None,
):
    if moderator.role != User.Role.MODERATOR:
        raise ValidationError(
            "Bonus qualification is only available for Moderators."
        )

    if window_hours < 1:
        raise ValidationError(
            "Qualifying window must be at least 1 hour."
        )

    window_start = window_end - timedelta(hours=window_hours)

    reports = EndOfSessionReport.objects.filter(
        moderator=moderator,
        submitted_at__gt=window_start,
        submitted_at__lte=window_end,
    )

    if player is not None:
        reports = reports.filter(coverage_session__player=player)

    return reports.order_by("submitted_at", "id")


def calculate_chats_within_window(
    *,
    moderator,
    window_end,
    window_hours=QUALIFYING_WINDOW_HOURS,
    player=None,
):
    reports = get_reports_within_window(
        moderator=moderator,
        window_end=window_end,
        window_hours=window_hours,
        player=player,
    )

    return sum(
        report.chats_responded or 0
        for report in reports
    )


def get_configured_bonus_tier(*, bonus_date):
    return (
        ChatBonusTier.objects
        .filter(
            active=True,
            qualifying_window_hours=QUALIFYING_WINDOW_HOURS,
        )
        .filter(
            models.Q(effective_from__isnull=True)
            | models.Q(effective_from__lte=bonus_date)
        )
        .order_by("-effective_from", "-id")
        .first()
    )


@transaction.atomic
def evaluate_moderator_bonus(
    *,
    moderator,
    window_end,
    bonus_date,
):
    if moderator.role != User.Role.MODERATOR:
        raise ValidationError(
            "Only Moderators can qualify for chat bonuses."
        )

    window_hours = QUALIFYING_WINDOW_HOURS
    window_start = window_end - timedelta(hours=window_hours)

    reports = get_reports_within_window(
        moderator=moderator,
        window_end=window_end,
        window_hours=window_hours,
    )

    player_reports_map = {}
    for report in reports:
        p = report.coverage_session.player
        if p not in player_reports_map:
            player_reports_map[p] = []
        player_reports_map[p].append(report)

    awards = []

    for p, p_reports in player_reports_map.items():
        chats_counted = sum(r.chats_responded or 0 for r in p_reports)

        if chats_counted <= 0:
            continue

        bonus_tier = get_applicable_bonus_tier(
            chats_counted=chats_counted,
            bonus_date=bonus_date,
            qualifying_window_hours=window_hours,
        )

        if bonus_tier is None:
            continue

        qualifying_report = p_reports[-1]

        existing_award = BonusAward.objects.filter(
            moderator=moderator,
            player=p,
            qualifying_window_start=window_start,
            qualifying_window_end=window_end,
        ).first()

        if existing_award is not None:
            awards.append(existing_award)
            continue

        award = BonusAward.objects.create(
            moderator=moderator,
            player=p,
            qualifying_report=qualifying_report,
            bonus_tier=bonus_tier,
            bonus_date=bonus_date,
            qualifying_window_start=window_start,
            qualifying_window_end=window_end,
            chats_counted=chats_counted,
            minimum_chats_snapshot=bonus_tier.minimum_chats,
            maximum_chats_snapshot=bonus_tier.maximum_chats,
            qualifying_window_hours_snapshot=bonus_tier.qualifying_window_hours,
            bonus_amount=Decimal(bonus_tier.bonus_amount),
        )
        awards.append(award)

    return awards


def evaluate_all_moderator_bonuses(
    *,
    window_end,
    bonus_date,
):
    moderators = User.objects.filter(
        role=User.Role.MODERATOR
    ).order_by("id")

    awards = []

    for moderator in moderators:
        mod_awards = evaluate_moderator_bonus(
            moderator=moderator,
            window_end=window_end,
            bonus_date=bonus_date,
        )

        if mod_awards:
            if isinstance(mod_awards, list):
                awards.extend(mod_awards)
            else:
                awards.append(mod_awards)

    return awards


def determine_daily_moderator_bonuses(*, determination_date=None):
    User = get_user_model()

    if determination_date is None:
        determination_date = timezone.localdate()

    if not isinstance(determination_date, date):
        raise ValidationError("A valid determination date is required.")

    local_tz = timezone.get_current_timezone()
    determination_time = time(9, 45)
    window_end = timezone.make_aware(
        datetime.combine(determination_date, determination_time),
        local_tz,
    )

    window_start = window_end - timedelta(hours=QUALIFYING_WINDOW_HOURS)

    moderators = User.objects.filter(
        role=User.Role.MODERATOR
    ).order_by("id")

    awards = []

    for moderator in moderators:
        reports = EndOfSessionReport.objects.filter(
            moderator=moderator,
            submitted_at__gt=window_start,
            submitted_at__lte=window_end,
        ).order_by("submitted_at", "id")

        player_reports_map = {}
        for report in reports:
            p = report.coverage_session.player
            if p not in player_reports_map:
                player_reports_map[p] = []
            player_reports_map[p].append(report)

        for p, p_reports in player_reports_map.items():
            chats_counted = sum(r.chats_responded or 0 for r in p_reports)

            if chats_counted <= 0:
                continue

            bonus_tier = get_applicable_bonus_tier(
                chats_counted=chats_counted,
                bonus_date=determination_date,
                qualifying_window_hours=QUALIFYING_WINDOW_HOURS,
            )

            if bonus_tier is None:
                continue

            qualifying_report = p_reports[-1]

            existing_award = BonusAward.objects.filter(
                moderator=moderator,
                player=p,
                qualifying_window_start=window_start,
                qualifying_window_end=window_end,
            ).first()

            if existing_award is not None:
                awards.append(existing_award)
                continue

            awards.append(
                BonusAward.objects.create(
                    moderator=moderator,
                    player=p,
                    qualifying_report=qualifying_report,
                    bonus_tier=bonus_tier,
                    bonus_date=determination_date,
                    qualifying_window_start=window_start,
                    qualifying_window_end=window_end,
                    chats_counted=chats_counted,
                    minimum_chats_snapshot=bonus_tier.minimum_chats,
                    maximum_chats_snapshot=bonus_tier.maximum_chats,
                    qualifying_window_hours_snapshot=bonus_tier.qualifying_window_hours,
                    bonus_amount=Decimal(bonus_tier.bonus_amount),
                    notes=(
                        "Official daily bonus determination at 09:45 local time; "
                        "evaluated per player."
                    ),
                )
            )

    return awards


def award_bonus_for_report(*, report, bonus_date=None):
    if not isinstance(report, EndOfSessionReport):
        raise ValidationError(
            "A valid End-of-Session Report is required."
        )

    if report.moderator.role != User.Role.MODERATOR:
        raise ValidationError(
            "Only Moderator reports can generate bonuses."
        )

    if report.submitted_at is None:
        raise ValidationError(
            "The report must have a submission timestamp."
        )

    if bonus_date is None:
        bonus_date = timezone.localdate(report.submitted_at)

    if not isinstance(bonus_date, date):
        raise ValidationError(
            "A valid bonus date is required."
        )

    window_hours = QUALIFYING_WINDOW_HOURS
    window_end = report.submitted_at
    window_start = (
        window_end - timedelta(hours=window_hours)
    )

    player = report.coverage_session.player

    reports = EndOfSessionReport.objects.filter(
        moderator=report.moderator,
        coverage_session__player=player,
        submitted_at__gt=window_start,
        submitted_at__lte=window_end,
    ).order_by("submitted_at", "id")

    chats_counted = sum(
        r.chats_responded or 0
        for r in reports
    )

    if chats_counted <= 0:
        return None

    bonus_tier = get_applicable_bonus_tier(
        chats_counted=chats_counted,
        bonus_date=bonus_date,
        qualifying_window_hours=window_hours,
    )

    if bonus_tier is None:
        return None

    existing_award = BonusAward.objects.filter(
        moderator=report.moderator,
        player=player,
        qualifying_window_start=window_start,
        qualifying_window_end=window_end,
    ).first()

    if existing_award is not None:
        return existing_award

    return BonusAward.objects.create(
        moderator=report.moderator,
        player=player,
        qualifying_report=report,
        bonus_tier=bonus_tier,
        bonus_date=bonus_date,
        qualifying_window_start=window_start,
        qualifying_window_end=window_end,
        chats_counted=chats_counted,
        minimum_chats_snapshot=bonus_tier.minimum_chats,
        maximum_chats_snapshot=bonus_tier.maximum_chats,
        qualifying_window_hours_snapshot=bonus_tier.qualifying_window_hours,
        bonus_amount=Decimal(bonus_tier.bonus_amount),
    )
