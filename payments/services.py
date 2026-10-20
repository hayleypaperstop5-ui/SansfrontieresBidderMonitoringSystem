from django.utils import timezone
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction

from players.models import ChatRateTier, Player, PlayerChatRateTier
from accounts.models import User

from .models import PaymentRecord, PaymentSettings, PlayerPayrollLedger


from django.db import transaction
def get_applicable_rate_tier(chats_responded, operating_date):
    """
    Return the global ChatRateTier applicable to the supplied
    chat count and operating date.
    """

    if chats_responded < 0:
        raise ValidationError("Chats responded cannot be negative.")

    if not isinstance(operating_date, date):
        raise ValidationError("A valid operating date is required.")

    tiers = (
        ChatRateTier.objects
        .filter(
            active=True,
            minimum_chats__lte=chats_responded,
        )
        .filter(
            models.Q(maximum_chats__isnull=True)
            | models.Q(maximum_chats__gte=chats_responded)
        )
        .filter(
            models.Q(effective_from__isnull=True)
            | models.Q(effective_from__lte=operating_date)
        )
        .order_by(
            "-effective_from",
            "-minimum_chats",
            "-id",
        )
    )

    tier = tiers.first()

    if tier is None:
        raise ValidationError(
            "No active chat rate tier applies to this coverage session."
        )

    return tier


def get_applicable_player_chat_rate_tier(
    player,
    chats_responded,
    operating_date,
):
    """
    Return the applicable PlayerChatRateTier with fallback to the global
    ChatRateTier card.

    Priority:
      1. Per-player override (PlayerChatRateTier).
      2. Global ChatRateTier card (default for all players).
    """
    if chats_responded < 0:
        raise ValidationError("Chats responded cannot be negative.")

    override = (
        PlayerChatRateTier.objects
        .filter(
            player=player,
            active=True,
            minimum_chats__lte=chats_responded,
        )
        .filter(
            models.Q(maximum_chats__isnull=True)
            | models.Q(maximum_chats__gte=chats_responded)
        )
        .filter(
            models.Q(effective_from__isnull=True)
            | models.Q(effective_from__lte=operating_date)
        )
        .order_by(
            "-effective_from",
            "-minimum_chats",
            "-id",
        )
        .first()
    )
    if override is not None:
        return override

    return get_applicable_rate_tier(
        chats_responded=chats_responded,
        operating_date=operating_date,
    )


def calculate_gross_amount(chats_responded, rate_per_chat):
    """
    Calculate gross earnings using the flat applicable rate.
    """

    if chats_responded < 0:
        raise ValidationError("Chats responded cannot be negative.")

    rate = Decimal(rate_per_chat)

    if rate < 0:
        raise ValidationError("Rate per chat cannot be negative.")

    return (
        Decimal(chats_responded) * rate
    ).quantize(Decimal("0.01"))


def create_payment_record(coverage_session, chats_responded):
    """
    Create the unpaid chat ledger record for a completed coverage session.

    Payment amounts are calculated only during payroll processing after
    Player-level qualification and Moderator-level payable chats are known.
    """

    if coverage_session.moderator.role != "MODERATOR":
        raise ValidationError(
            "Only Moderator coverage sessions can generate payment records."
        )

    if chats_responded < 0:
        raise ValidationError("Chats responded cannot be negative.")

    if hasattr(coverage_session, "payment_record"):
        raise ValidationError(
            "A payment record already exists for this coverage session."
        )

    return PaymentRecord.objects.create(
        moderator=coverage_session.moderator,
        coverage_session=coverage_session,
        chats_responded=chats_responded,
    )
from datetime import timedelta
from django.db.models import Sum

from bonuses.models import BonusAward
from coverage.models import EndOfSessionReport

from .models import ModeratorPayment, ManagerPayment


def get_player_payment_threshold(operating_date):
    """
    Return the Player chat qualification threshold configured by the
    Director through PaymentSettings.
    """

    if not isinstance(operating_date, date):
        raise ValidationError("A valid operating date is required.")

    settings = (
        PaymentSettings.objects
        .order_by("-id")
        .first()
    )

    if settings is None:
        return 700

    return settings.minimum_chats_per_player


def get_payment_week_dates(payment_date):
    """
    Return the completed Monday-Sunday week paid on Thursday.

    Example:
        Thursday 2026-09-24 -> Monday 2026-09-14 through Sunday 2026-09-20.
    """

    current_week_start = payment_date - timedelta(days=payment_date.weekday())
    week_end = current_week_start - timedelta(days=1)
    week_start = week_end - timedelta(days=6)

    return week_start, week_end


def get_qualifying_player_chats(
    week_start,
    week_end,
    threshold=None,
):
    """
    Determine which Players have reached the payment threshold using
    accumulated unpaid chats across all Moderators.

    Only chats that have not already been consumed by payroll processing
    are considered. This allows chats below the threshold to carry forward
    until the Player reaches the configured threshold.

    The week dates are retained for API compatibility with the existing
    payroll functions. Historical unprocessed chats are intentionally
    included so that carry-forward works across payment weeks.
    """

    if threshold is None:
        threshold = get_player_payment_threshold(
            operating_date=week_end,
        )

    reports = (
        PaymentRecord.objects
        .select_related("coverage_session")
        .values(
            "coverage_session__player_id",
        )
        .annotate(
            total_chats=Sum(
                models.F("chats_responded")
                - models.F("payroll_processed_chats")
            )
        )
    )

    return {
        row["player_id"]: row["total_chats"]
        for row in reports
        if row["total_chats"] >= threshold
    }


def get_moderator_payable_chats(
    moderator,
    week_start,
    week_end,
    threshold=None,
):
    """
    Return the Moderator's currently payable accumulated chats.

    A Player qualifies when all Moderators combined have accumulated
    at least the configured threshold of unprocessed chats.

    Once the Player qualifies, this Moderator receives credit only for
    the Moderator's own unprocessed chats for that Player.
    """

    qualifying_players = get_qualifying_player_chats(
        week_start=week_start,
        week_end=week_end,
        threshold=threshold,
    )

    if not qualifying_players:
        return 0

    result = (
        PaymentRecord.objects
        .filter(
            moderator=moderator,
            coverage_session__player_id__in=qualifying_players.keys(),
        )
        .aggregate(
            total=Sum(
                models.F("chats_responded")
                - models.F("payroll_processed_chats")
            )
        )
    )

    return result["total"] or 0


def calculate_moderator_weekly_earnings(
    moderator,
    week_start,
    week_end,
    payment_method=ModeratorPayment.PaymentMethod.WEEKLY_PER_CHAT,
    monthly_base_amount=Decimal("0.00"),
):
    """
    Calculate Moderator earnings without creating a payment record.

    Weekly/per-chat:
        payable accumulated chats x applicable current chat-rate tier
        + bonuses.

    Monthly:
        monthly amount / 4 + weekly bonuses.

    Player qualification is based on the combined unprocessed chats
    received by each Player across all Moderators.
    """

    payable_chats = get_moderator_payable_chats(
        moderator=moderator,
        week_start=week_start,
        week_end=week_end,
    )

    bonus_total = (
        BonusAward.objects
        .filter(
            moderator=moderator,
            bonus_date__gte=week_start,
            bonus_date__lte=week_end,
        )
        .aggregate(total=Sum("bonus_amount"))
        ["total"]
        or Decimal("0.00")
    )

    chat_earnings = Decimal("0.00")
    rate_per_chat = Decimal("0.00")

    if payment_method == ModeratorPayment.PaymentMethod.WEEKLY_PER_CHAT:
        if payable_chats > 0:
            rate_tier = get_applicable_rate_tier(
                chats_responded=payable_chats,
                operating_date=week_end,
            )

            rate_per_chat = rate_tier.rate_per_chat

            chat_earnings = calculate_gross_amount(
                chats_responded=payable_chats,
                rate_per_chat=rate_per_chat,
            )

        earned_amount = chat_earnings + bonus_total

    else:
        weekly_base = (
            Decimal(monthly_base_amount) / Decimal("4")
        ).quantize(Decimal("0.01"))

        earned_amount = weekly_base + bonus_total

    return {
        "payable_chats": payable_chats,
        "rate_per_chat": rate_per_chat,
        "chat_earnings": chat_earnings,
        "bonus_earned": bonus_total,
        "monthly_base_amount": Decimal(monthly_base_amount),
        "earned_amount": earned_amount,
    }


def process_qualifying_player_chats(
    week_start,
    week_end,
    threshold=None,
):
    """
    Atomically consume all currently unpaid chats for Players who
    have reached the configured threshold.

    A Player qualifies using accumulated unpaid chats across all
    Moderators. Each Moderator receives credit only for that
    Moderator's own unpaid chats for the qualifying Player.

    An audit snapshot is created for every Player encountered,
    recording opening carry-forward, current-period chats, total
    available chats, qualified chats, processed chats, closing
    carry-forward, and remaining chats to qualification.
    """

    if threshold is None:
        threshold = get_player_payment_threshold(
            operating_date=week_end,
        )

    with transaction.atomic():
        records = list(
            PaymentRecord.objects
            .select_for_update()
            .select_related(
                "coverage_session",
                "moderator",
            )
            .filter(
                coverage_session__operating_date__lte=week_end,
                chats_responded__gt=models.F(
                    "payroll_processed_chats"
                ),
            )
            .order_by(
                "coverage_session__player_id",
                "coverage_session__operating_date",
                "id",
            )
        )

        player_records = {}

        for record in records:
            player_id = record.coverage_session.player_id
            player_records.setdefault(
                player_id,
                [],
            ).append(record)

        processed_players = {}
        moderator_totals = {}
        moderator_player_totals = {}
        processed_record_ids_by_moderator = {}

        for player_id, player_payment_records in player_records.items():

            total_available_chats = sum(
                (
                    record.chats_responded
                    - record.payroll_processed_chats
                    for record in player_payment_records
                ),
                0,
            )

            current_period_chats = sum(
                (
                    record.chats_responded
                    - record.payroll_processed_chats
                    for record in player_payment_records
                    if (
                        week_start
                        <= record.coverage_session.operating_date
                        <= week_end
                    )
                ),
                0,
            )

            opening_carried_forward = (
                total_available_chats
                - current_period_chats
            )

            if total_available_chats < threshold:
                PlayerPayrollLedger.objects.create(
                    player_id=player_id,
                    payment_week_start=week_start,
                    payment_week_end=week_end,
                    opening_carried_forward=max(
                        opening_carried_forward,
                        0,
                    ),
                    current_period_chats=current_period_chats,
                    total_available_chats=total_available_chats,
                    qualified_chats=0,
                    processed_chats=0,
                    closing_carried_forward=total_available_chats,
                    chats_remaining_to_qualification=(
                        threshold - total_available_chats
                    ),
                )
                continue

            moderator_breakdown = {}

            for record in player_payment_records:
                unprocessed = (
                    record.chats_responded
                    - record.payroll_processed_chats
                )

                if unprocessed <= 0:
                    continue

                record.payroll_processed_chats = (
                    record.chats_responded
                )

                record.save(
                    update_fields=[
                        "payroll_processed_chats",
                        "updated_at",
                    ]
                )

                moderator_id = record.moderator_id

                moderator_breakdown[moderator_id] = (
                    moderator_breakdown.get(
                        moderator_id,
                        0,
                    )
                    + unprocessed
                )

                moderator_totals[moderator_id] = (
                    moderator_totals.get(
                        moderator_id,
                        0,
                    )
                    + unprocessed
                )

                moderator_player_totals.setdefault(
                    moderator_id,
                    {},
                )[player_id] = (
                    moderator_player_totals
                    .setdefault(
                        moderator_id,
                        {},
                    )
                    .get(
                        player_id,
                        0,
                    )
                    + unprocessed
                )

            PlayerPayrollLedger.objects.create(
                player_id=player_id,
                payment_week_start=week_start,
                payment_week_end=week_end,
                opening_carried_forward=max(
                    opening_carried_forward,
                    0,
                ),
                current_period_chats=current_period_chats,
                total_available_chats=total_available_chats,
                qualified_chats=total_available_chats,
                processed_chats=total_available_chats,
                closing_carried_forward=0,
                chats_remaining_to_qualification=0,
            )

            processed_players[player_id] = {
                "total_chats": total_available_chats,
                "moderator_breakdown": moderator_breakdown,
            }

        return {
            "threshold": threshold,
            "processed_players": processed_players,
            "moderator_totals": moderator_totals,
            "moderator_player_totals": moderator_player_totals,
        }


def suggested_payroll_window(chosen_end=None):
    """
    Default payroll window:
      start = min(day after last PAID week_end, earliest unconsumed shift date)
              -> never overlaps a paid period
              -> never skips unpaid work sitting before the last paid window
      end   = chosen_end (default today)
    """
    from datetime import date as _date, timedelta
    from payments.models import ModeratorPayment, PaymentRecord

    chosen_end = chosen_end or _date.today()

    last_paid_end = (
        ModeratorPayment.objects
        .filter(status="PAID")
        .order_by("-payment_week_end")
        .values_list("payment_week_end", flat=True)
        .first()
    )

    earliest_unconsumed = (
        PaymentRecord.objects
        .filter(consumed_by__isnull=True, chats_responded__gt=0)
        .order_by("coverage_session__operating_date")
        .values_list("coverage_session__operating_date", flat=True)
        .first()
    )

    candidates = []
    if last_paid_end:
        candidates.append(last_paid_end + timedelta(days=1))
    if earliest_unconsumed:
        candidates.append(earliest_unconsumed)

    if candidates:
        start = min(candidates)
    else:
        start = chosen_end - timedelta(days=6)

    if start > chosen_end:
        start = chosen_end
    return start, chosen_end


def build_payroll_plan(
    payment_date,
    *,
    threshold=None,
    window_start=None,
    window_end=None,
):
    from datetime import date
    from django.core.exceptions import ValidationError
    from django.db import models
    from django.db.models import Sum
    from accounts.models import User
    from players.models import Player

    if not isinstance(payment_date, date):
        raise ValidationError("A valid payment date is required.")

    if window_start and window_end:
        week_start, week_end = window_start, window_end
    else:
        week_start, week_end = get_payment_week_dates(payment_date)

    settings = PaymentSettings.objects.order_by("-id").first()

    if settings is None:
        payment_method = ModeratorPayment.PaymentMethod.WEEKLY_PER_CHAT
        monthly_base_amount = Decimal("0.00")
        rate_method = ModeratorPayment.RateMethod.CHAT_TIER
    else:
        payment_method = settings.moderator_payment_method
        monthly_base_amount = settings.moderator_monthly_amount
        rate_method = settings.moderator_rate_method

    if threshold is None:
        threshold = get_player_payment_threshold(
            operating_date=week_end,
        )

    records = list(
        PaymentRecord.objects
        .select_related("coverage_session", "moderator")
        .filter(
            coverage_session__operating_date__lte=week_end,
            chats_responded__gt=models.F("payroll_processed_chats"),
        )
        .order_by(
                "coverage_session__player_id",
                "coverage_session__operating_date",
            "id",
        )
    )

    player_records = {}
    for record in records:
        player_id = record.coverage_session.player_id
        player_records.setdefault(player_id, []).append(record)

    player_rows = []
    qualifying_players = {}
    moderator_player_rows = {}
    moderator_ids = set()

    for player_id, player_payment_records in player_records.items():
        total_available_chats = sum(
            record.chats_responded - record.payroll_processed_chats
            for record in player_payment_records
        )

        current_period_chats = sum(
            record.chats_responded - record.payroll_processed_chats
            for record in player_payment_records
            if week_start <= record.coverage_session.operating_date <= week_end
        )

        opening_carried_forward = max(total_available_chats - current_period_chats, 0)
        qualified = total_available_chats >= threshold
        player = Player.objects.get(id=player_id)

        player_rows.append({
            "player_id": player_id,
            "player": player,
            "opening_cf": opening_carried_forward,
            "current": current_period_chats,
            "total": total_available_chats,
            "payable": total_available_chats if qualified else 0,
            "qualified": qualified,
            "remaining": max(threshold - total_available_chats, 0),
        })

        for record in player_payment_records:
            unprocessed = record.chats_responded - record.payroll_processed_chats
            if unprocessed <= 0:
                continue

            moderator_id = record.moderator_id
            moderator_ids.add(moderator_id)
            key = (moderator_id, player_id)

            row = moderator_player_rows.setdefault(
                key,
                {
                    "moderator_id": moderator_id,
                    "moderator": record.moderator,
                    "player_id": player_id,
                    "player": player,
                    "opening_cf": 0,
                    "current": 0,
                    "total": 0,
                    "payable": 0,
                },
            )

            row["total"] += unprocessed
            if week_start <= record.coverage_session.operating_date <= week_end:
                row["current"] += unprocessed

        if qualified:
            qualifying_players[player_id] = {
                "player": player,
                "total_chats": total_available_chats,
            }

    for (moderator_id, player_id), row in moderator_player_rows.items():
        moderator_player_records = [
            record for record in player_records[player_id]
            if record.moderator_id == moderator_id
        ]

        row["opening_cf"] = sum(
            record.chats_responded - record.payroll_processed_chats
            for record in moderator_player_records
            if record.coverage_session.operating_date < week_start
        )

        row["payable"] = row["total"] if player_id in qualifying_players else 0

    bonus_moderator_ids = set(
        BonusAward.objects
        .filter(bonus_date__gte=week_start, bonus_date__lte=week_end)
        .values_list("moderator_id", flat=True)
    )

    moderator_ids |= bonus_moderator_ids
    moderator_financials = {}

    total_payable_chats = 0
    total_chat_earnings = Decimal("0.00")
    total_bonuses = Decimal("0.00")
    total_earned = Decimal("0.00")

    for moderator_id in sorted(moderator_ids):
        moderator = User.objects.get(id=moderator_id, role=User.Role.MODERATOR)

        payable_chats = sum(
            row["payable"]
            for row in moderator_player_rows.values()
            if row["moderator_id"] == moderator_id
        )

        bonus_total = (
            BonusAward.objects
            .filter(
                moderator=moderator,
                bonus_date__gte=week_start,
                bonus_date__lte=week_end,
            )
            .aggregate(total=Sum("bonus_amount"))["total"]
            or Decimal("0.00")
        )

        rate_per_chat = Decimal("0.00")
        chat_tier_rate = Decimal("0.00")
        player_chat_rate_breakdown = {}
        chat_earnings = Decimal("0.00")

        if payment_method == ModeratorPayment.PaymentMethod.WEEKLY_PER_CHAT:
            if (
                rate_method in (
                    ModeratorPayment.RateMethod.CHAT_TIER,
                    ModeratorPayment.RateMethod.BOTH,
                )
                and payable_chats > 0
            ):
                chat_tier = get_applicable_rate_tier(
                    chats_responded=payable_chats,
                    operating_date=week_end,
                )
                chat_tier_rate = chat_tier.rate_per_chat
                rate_per_chat = chat_tier_rate

            if rate_method == ModeratorPayment.RateMethod.CHAT_TIER:
                if payable_chats > 0:
                    chat_earnings = calculate_gross_amount(
                        chats_responded=payable_chats,
                        rate_per_chat=chat_tier_rate,
                    )

            elif rate_method in (
                ModeratorPayment.RateMethod.PLAYER_CHAT_RATE,
                ModeratorPayment.RateMethod.BOTH,
            ):
                for key, row in sorted(moderator_player_rows.items()):
                    row_moderator_id, player_id = key
                    if row_moderator_id != moderator_id or player_id not in qualifying_players:
                        continue

                    player_total_chats = qualifying_players[player_id]["total_chats"]
                    player_tier = get_applicable_player_chat_rate_tier(
                        player=row["player"],
                        chats_responded=player_total_chats,
                        operating_date=week_end,
                    )

                    player_rate = Decimal(player_tier.rate_per_chat)

                    if rate_method == ModeratorPayment.RateMethod.PLAYER_CHAT_RATE:
                        player_earnings = calculate_gross_amount(
                            chats_responded=row["payable"],
                            rate_per_chat=player_rate,
                        )
                    else:
                        player_earnings = (
                            Decimal(row["payable"]) * chat_tier_rate * player_rate
                        ).quantize(Decimal("0.01"))

                    player_chat_rate_breakdown[str(player_id)] = {
                        "qualifying_chats": row["payable"],
                        "rate_per_chat": str(player_rate),
                        "chat_earnings": str(player_earnings),
                    }

                    chat_earnings += player_earnings

            else:
                raise ValidationError(f"Unsupported Moderator rate method: {rate_method}")

            chat_earnings = chat_earnings.quantize(Decimal("0.01"))
            earned_amount = chat_earnings + bonus_total

        else:
            weekly_base = (
                Decimal(monthly_base_amount) / Decimal("4")
            ).quantize(Decimal("0.01"))
            earned_amount = weekly_base + bonus_total

        moderator_financials[moderator_id] = {
            "moderator_id": moderator_id,
            "moderator": moderator,
            "payable_chats": payable_chats,
            "rate_per_chat": rate_per_chat,
            "chat_tier_rate": chat_tier_rate,
            "player_chat_rate_breakdown": player_chat_rate_breakdown,
            "chat_earnings": chat_earnings,
            "bonus_earned": bonus_total,
            "monthly_base_amount": Decimal(monthly_base_amount),
            "earned_amount": earned_amount,
        }

        total_payable_chats += payable_chats
        total_chat_earnings += chat_earnings
        total_bonuses += bonus_total
        total_earned += earned_amount

    review_rows = list(moderator_player_rows.values())
    review_rows.sort(
        key=lambda row: (
            row["moderator"].username.lower(),
            str(row["player"]).lower(),
        )
    )

    return {
        "payment_date": payment_date,
        "week_start": week_start,
        "week_end": week_end,
        "threshold": threshold,
        "payment_method": payment_method,
        "monthly_base_amount": monthly_base_amount,
        "rate_method": rate_method,
        "player_rows": player_rows,
        "review_rows": review_rows,
        "qualifying_players": qualifying_players,
        "moderator_financials": moderator_financials,
        "total_payable_chats": total_payable_chats,
        "total_chat_earnings": total_chat_earnings,
        "total_bonuses": total_bonuses,
        "total_earned": total_earned,
    }

def process_thursday_payroll(payment_date, *, window_start=None, window_end=None):
    from datetime import date
    from django.core.exceptions import ValidationError
    from django.db import models, transaction

    if not isinstance(payment_date, date):
        raise ValidationError("A valid payment date is required.")

    if window_start and window_end:
        week_start, week_end = window_start, window_end
    else:
        week_start, week_end = get_payment_week_dates(payment_date)

    with transaction.atomic():
        existing_payroll = ModeratorPayment.objects.select_for_update().filter(
            payment_week_start=week_start,
            payment_week_end=week_end,
        ).exists()

        if existing_payroll:
            raise ValidationError(
                f"Moderator payroll has already been processed for {week_start} to {week_end}."
            )

        plan = build_payroll_plan(
            payment_date=payment_date,
            window_start=week_start,
            window_end=week_end,
        )

        locked_records = list(
            PaymentRecord.objects.select_for_update()
            .select_related("coverage_session", "moderator")
            .filter(
                coverage_session__operating_date__lte=week_end,
                chats_responded__gt=models.F("payroll_processed_chats"),
            )
            .order_by(
                "coverage_session__player_id",
                "coverage_session__operating_date",
                "id",
            )
        )

        locked_by_player = {}
        for record in locked_records:
            player_id = record.coverage_session.player_id
            locked_by_player.setdefault(player_id, []).append(record)

        processed_players = {}
        moderator_totals = {}
        moderator_player_totals = {}
        processed_record_ids_by_moderator = {}

        for player_id, player_payment_records in locked_by_player.items():
            total_available_chats = sum(
                record.chats_responded - record.payroll_processed_chats
                for record in player_payment_records
            )

            current_period_chats = sum(
                record.chats_responded - record.payroll_processed_chats
                for record in player_payment_records
                if week_start <= record.coverage_session.operating_date <= week_end
            )

            opening_carried_forward = max(total_available_chats - current_period_chats, 0)

            planned_player = next(
                (
                    row for row in plan["player_rows"]
                    if row["player_id"] == player_id
                ),
                None,
            )

            if planned_player is None:
                raise ValidationError(
                    "Payroll changed between review calculation and processing."
                )

            if (
                planned_player["total"] != total_available_chats
                or planned_player["current"] != current_period_chats
                or planned_player["opening_cf"] != opening_carried_forward
            ):
                raise ValidationError(
                    "Payroll changed between review calculation and processing."
                )


            if total_available_chats < plan["threshold"]:
                PlayerPayrollLedger.objects.create(
                    player_id=player_id,
                    payment_week_start=week_start,
                    payment_week_end=week_end,
                    opening_carried_forward=opening_carried_forward,
                    current_period_chats=current_period_chats,
                    total_available_chats=total_available_chats,
                    qualified_chats=0,
                    processed_chats=0,
                    closing_carried_forward=total_available_chats,
                    chats_remaining_to_qualification=plan["threshold"] - total_available_chats,
                )
                continue

            moderator_breakdown = {}
            for record in player_payment_records:
                unprocessed = record.chats_responded - record.payroll_processed_chats
                if unprocessed <= 0:
                    continue

                record.payroll_processed_chats = record.chats_responded
                record.save(update_fields=["payroll_processed_chats", "updated_at"])

                moderator_id = record.moderator_id
                moderator_breakdown[moderator_id] = moderator_breakdown.get(moderator_id, 0) + unprocessed
                moderator_totals[moderator_id] = moderator_totals.get(moderator_id, 0) + unprocessed

                moderator_player_totals.setdefault(moderator_id, {})
                moderator_player_totals[moderator_id][player_id] = (
                    moderator_player_totals[moderator_id].get(player_id, 0) + unprocessed
                )

                processed_record_ids_by_moderator.setdefault(moderator_id, []).append(record.id)

            PlayerPayrollLedger.objects.create(
                player_id=player_id,
                payment_week_start=week_start,
                payment_week_end=week_end,
                opening_carried_forward=opening_carried_forward,
                current_period_chats=current_period_chats,
                total_available_chats=total_available_chats,
                qualified_chats=total_available_chats,
                processed_chats=total_available_chats,
                closing_carried_forward=0,
                chats_remaining_to_qualification=0,
            )

            processed_players[player_id] = {
                "total_chats": total_available_chats,
                "moderator_breakdown": moderator_breakdown,
            }

        planned_moderator_totals = {
            moderator_id: financial["payable_chats"]
            for moderator_id, financial in plan["moderator_financials"].items()
            if financial["payable_chats"] > 0
        }

        if moderator_totals != planned_moderator_totals:
            raise ValidationError("Payroll changed between review calculation and processing.")

        created_payments = []
        for moderator_id, financial in sorted(plan["moderator_financials"].items()):
            moderator = financial["moderator"]

            existing_payment = ModeratorPayment.objects.select_for_update().filter(
                moderator=moderator,
                payment_week_start=week_start,
                payment_week_end=week_end,
            ).first()

            if existing_payment is not None:
                raise ValidationError(
                    f"A Moderator payroll record already exists for {moderator.username}."
                )

            moderator_payment = ModeratorPayment.objects.create(
                moderator=moderator,
                payment_week_start=week_start,
                payment_week_end=week_end,
                payment_date=payment_date,
                payment_method=plan["payment_method"],
                payable_chats=financial["payable_chats"],
                payroll_processed_chats=financial["payable_chats"],
                rate_per_chat=financial["rate_per_chat"],
                rate_method=plan["rate_method"],
                chat_tier_rate=financial["chat_tier_rate"],
                player_chat_rate_breakdown=financial["player_chat_rate_breakdown"],
                generated_amount=financial["chat_earnings"],
                chat_earnings=financial["chat_earnings"],
                bonus_earned=financial["bonus_earned"],
                monthly_base_amount=financial["monthly_base_amount"],
                earned_amount=financial["earned_amount"],
                carried_forward=Decimal("0.00"),
                amount_paid=Decimal("0.00"),
                outstanding_amount=financial["earned_amount"],
                status=ModeratorPayment.Status.UNPAID,
            )

            # Link consumed PaymentRecords to this payment so the settlement
            # view can retrieve the exact source sessions unambiguously.
            record_ids = processed_record_ids_by_moderator.get(moderator.id, [])
            if record_ids:
                PaymentRecord.objects.filter(id__in=record_ids).update(
                    consumed_by=moderator_payment,
                )

            created_payments.append(moderator_id)

        # -----------------------------------------------------------
        # Notify moderators whose M-Pesa number is missing so they can
        # add it before the Director attempts to record their payment.
        # -----------------------------------------------------------
        from notifications.models import Notification as _Notif

        missing_mpesa_moderator_ids = set()
        for moderator_id, financial in plan["moderator_financials"].items():
            if financial["payable_chats"] <= 0:
                continue
            moderator = financial["moderator"]
            profile = getattr(moderator, "staff_profile", None)
            mpesa = (profile.mpesa_number or "").strip() if profile else ""
            if not mpesa:
                missing_mpesa_moderator_ids.add(moderator_id)

        for moderator_id in missing_mpesa_moderator_ids:
            try:
                moderator = User.objects.get(pk=moderator_id)
            except User.DoesNotExist:
                continue

            earned = Decimal("0.00")
            for mp in ModeratorPayment.objects.filter(
                moderator=moderator,
                payment_week_start=week_start,
                payment_week_end=week_end,
            ):
                earned += mp.earned_amount or Decimal("0.00")

            _Notif.objects.create(
                recipient=moderator,
                notification_type=_Notif.NotificationType.GENERAL,
                alert_level=_Notif.AlertLevel.CRITICAL,
                title="M-Pesa Number Missing",
                message=(
                    f"Your payroll for {week_start} to {week_end} was processed "
                    f"with earnings of KES {earned}, but your M-Pesa number is "
                    "missing from your profile. Please add it in "
                    "/dashboard/profile/ so management can process your payment."
                ),
            )

        return {
            "payment_date": payment_date,
            "week_start": week_start,
            "week_end": week_end,
            "threshold": plan["threshold"],
            "processed_players": processed_players,
            "moderator_totals": moderator_totals,
            "moderator_player_totals": moderator_player_totals,
            "rate_method": plan["rate_method"],
            "payments_created": len(created_payments),
            "payment_ids": created_payments,
            "total_payable_chats": plan["total_payable_chats"],
            "total_chat_earnings": plan["total_chat_earnings"],
            "total_bonuses": plan["total_bonuses"],
            "total_earned": plan["total_earned"],
        }

@transaction.atomic
def settle_moderator_payment(
    *,
    moderator_payment,
    amount_paid,
    payment_reference="",
    notes="",
):
    """
    Record a payment against an existing ModeratorPayment payroll record.

    The settlement amount is cumulative: amount_paid represents the new
    payment being made now, while ModeratorPayment.amount_paid stores the
    cumulative amount paid to date.
    """
    try:
        amount_paid = Decimal(str(amount_paid))
    except (TypeError, ValueError):
        raise ValidationError("Payment amount must be a valid number.")

    if amount_paid <= Decimal("0.00"):
        raise ValidationError("Payment amount must be greater than zero.")

    current_paid = moderator_payment.amount_paid or Decimal("0.00")
    earned_amount = moderator_payment.earned_amount or Decimal("0.00")

    new_total_paid = current_paid + amount_paid

    if new_total_paid > earned_amount:
        raise ValidationError(
            "Payment cannot exceed the Moderator's earned payroll amount."
        )

    outstanding_amount = earned_amount - new_total_paid

    if new_total_paid == Decimal("0.00"):
        status = moderator_payment.Status.UNPAID
    elif outstanding_amount == Decimal("0.00"):
        status = moderator_payment.Status.PAID
    else:
        status = moderator_payment.Status.PARTIALLY_PAID

    moderator_payment.amount_paid = new_total_paid
    moderator_payment.outstanding_amount = outstanding_amount
    moderator_payment.status = status
    moderator_payment.payment_reference = payment_reference.strip()
    moderator_payment.notes = notes.strip()

    moderator_payment.save(
        update_fields=[
            "amount_paid",
            "outstanding_amount",
            "status",
            "payment_reference",
            "notes",
            "updated_at",
        ]
    )

    return moderator_payment

@transaction.atomic
def record_payment(*, payment, director, mpesa_reference, amount):
    """
    Mark a ModeratorPayment as paid and record the M-Pesa reference.

    Rejects the payment if the moderator has no M-Pesa number on file,
    so funds cannot be recorded against an account that cannot receive them.

    Supports partial payments: if `amount` is less than the outstanding
    balance, the payment transitions to PARTIALLY_PAID and the
    outstanding balance is reduced. Otherwise, it becomes PAID.
    """
    if payment.status == ModeratorPayment.Status.PAID:
        raise ValidationError("This payment has already been recorded as paid.")

    # Require an M-Pesa number on the moderator's profile before payment.
    moderator_profile = getattr(payment.moderator, "staff_profile", None)
    moderator_mpesa = (moderator_profile.mpesa_number or "").strip() if moderator_profile else ""
    if not moderator_mpesa:
        raise ValidationError(
            f"{payment.moderator.get_full_name() or payment.moderator.username} "
            "has no M-Pesa number on file. Ask the moderator to add it in "
            "their profile before recording this payment."
        )

    if not mpesa_reference or not str(mpesa_reference).strip():
        raise ValidationError("An M-Pesa reference is required.")

    try:
        amount = Decimal(str(amount))
    except Exception:
        raise ValidationError("Invalid payment amount.")

    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")

    outstanding = payment.outstanding_amount or Decimal("0.00")
    if amount > outstanding:
        raise ValidationError(
            f"Payment amount ({amount}) exceeds outstanding balance ({outstanding})."
        )

    payment.paid_at = timezone.now()
    payment.paid_by = director
    payment.mpesa_reference = str(mpesa_reference).strip()
    payment.amount_paid = (payment.amount_paid or Decimal("0.00")) + amount

    if amount == outstanding:
        payment.status = ModeratorPayment.Status.PAID
        payment.outstanding_amount = Decimal("0.00")
    else:
        payment.status = ModeratorPayment.Status.PARTIALLY_PAID
        payment.outstanding_amount = outstanding - amount

    payment.save(update_fields=[
        "paid_at", "paid_by", "mpesa_reference", "amount_paid",
        "status", "outstanding_amount", "updated_at",
    ])

    # Notify the moderator that their payment was recorded.
    from notifications.models import Notification
    period = (
        f"{payment.payment_week_start.strftime('%d %b %Y')} - "
        f"{payment.payment_week_end.strftime('%d %b %Y')}"
    )
    pdf_url = f"/payments/payroll/settle/{payment.id}/pdf/"

    if payment.status == ModeratorPayment.Status.PAID:
        title = "Payment Received"
        message = (
            f"Your payment of KES {payment.amount_paid} for the period "
            f"{period} has been recorded. "
            f"M-Pesa reference: {payment.mpesa_reference}. "
            f"Download your statement: {pdf_url}"
        )
    else:
        title = "Partial Payment Received"
        message = (
            f"A partial payment of KES {amount} for the period {period} "
            f"has been recorded. Remaining outstanding: "
            f"KES {payment.outstanding_amount}. "
            f"M-Pesa reference: {payment.mpesa_reference}. "
            f"Download your statement: {pdf_url}"
        )

    Notification.objects.create(
        recipient=payment.moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=Notification.AlertLevel.IMPORTANT,
        title=title,
        message=message,
    )

    return payment

@transaction.atomic
def record_payment_group(*, moderator, director, mpesa_reference, amount):
    """
    Record a single payment covering all unpaid ModeratorPayment rows
    for a moderator.

    Splits sequentially: oldest week first. If `amount` doesn't cover
    all records, the oldest are paid in full and the next one is
    partially paid — remaining records stay untouched.

    Applies the same `mpesa_reference` to every record it touches, so
    the M-Pesa transaction can be traced back to multiple payroll rows.

    Returns a dict with the list of updated payments and any remainder.
    """
    if not mpesa_reference or not str(mpesa_reference).strip():
        raise ValidationError("An M-Pesa reference is required.")

    try:
        amount = Decimal(str(amount))
    except Exception:
        raise ValidationError("Invalid payment amount.")

    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")

    profile = getattr(moderator, "staff_profile", None)
    if not profile or not (profile.mpesa_number or "").strip():
        raise ValidationError(
            f"{moderator.get_full_name() or moderator.username} has no M-Pesa "
            "number on file. Ask the moderator to add it before recording payment."
        )

    # Load all unpaid records for this moderator, oldest first
    unpaid = list(
        ModeratorPayment.objects
        .select_for_update()
        .filter(
            moderator=moderator,
        )
        .exclude(status=ModeratorPayment.Status.PAID)
        .order_by("payment_week_start", "id")
    )

    if not unpaid:
        raise ValidationError(
            f"{moderator.get_full_name() or moderator.username} has no "
            "unpaid records to settle."
        )

    total_outstanding = sum(
        (mp.outstanding_amount or Decimal("0.00")) for mp in unpaid
    )

    if amount > total_outstanding:
        raise ValidationError(
            f"Amount ({amount}) exceeds total outstanding ({total_outstanding})."
        )

    mpesa_reference = str(mpesa_reference).strip()
    remaining = amount
    updated = []
    notification_list = []

    from notifications.models import Notification

    for mp in unpaid:
        if remaining <= 0:
            break

        record_outstanding = mp.outstanding_amount or Decimal("0.00")

        if remaining >= record_outstanding:
            # Pay this record in full
            applied = record_outstanding
            mp.amount_paid = (mp.amount_paid or Decimal("0.00")) + applied
            mp.outstanding_amount = Decimal("0.00")
            mp.status = ModeratorPayment.Status.PAID
        else:
            # Partial payment on this record
            applied = remaining
            mp.amount_paid = (mp.amount_paid or Decimal("0.00")) + applied
            mp.outstanding_amount = record_outstanding - applied
            mp.status = ModeratorPayment.Status.PARTIALLY_PAID

        mp.paid_at = timezone.now()
        mp.paid_by = director
        mp.mpesa_reference = mpesa_reference

        mp.save(update_fields=[
            "amount_paid",
            "outstanding_amount",
            "status",
            "paid_at",
            "paid_by",
            "mpesa_reference",
            "updated_at",
        ])

        updated.append(mp)
        remaining -= applied

        period = (
            f"{mp.payment_week_start.strftime('%d %b %Y')} - "
            f"{mp.payment_week_end.strftime('%d %b %Y')}"
        )
        pdf_url = f"/payments/payroll/settle/{mp.id}/pdf/"

        if mp.status == ModeratorPayment.Status.PAID:
            title = "Payment Received"
            msg = (
                f"Your payment of KES {applied} for the period {period} "
                f"has been recorded. M-Pesa reference: {mpesa_reference}. "
                f"Download your statement: {pdf_url}"
            )
        else:
            title = "Partial Payment Received"
            msg = (
                f"A partial payment of KES {applied} for the period {period} "
                f"has been recorded. Remaining outstanding: "
                f"KES {mp.outstanding_amount}. "
                f"M-Pesa reference: {mpesa_reference}. "
                f"Download your statement: {pdf_url}"
            )

        notification_list.append(Notification(
            recipient=moderator,
            notification_type=Notification.NotificationType.GENERAL,
            alert_level=Notification.AlertLevel.IMPORTANT,
            title=title,
            message=msg,
        ))

    if notification_list:
        Notification.objects.bulk_create(notification_list)

    return {
        "updated": updated,
        "total_outstanding_before": total_outstanding,
        "amount_applied": amount - remaining,
        "amount_remaining": remaining,
    }

def recalculate_unpaid_rates(*, moderator=None, apply=True):
    """
    Recalculate unpaid ModeratorPayment records using the current
    ChatRateTier card.

    Args:
        moderator: limit to one moderator (None = all unpaid records)
        apply: if True, write changes to DB; if False, preview only

    Returns:
        dict with:
            mode: "PREVIEW" | "APPLY"
            records: list of {id, moderator_username, week_start, week_end, payable_chats, old_rate, new_rate, old_earned, new_earned, changed}
            total_before: Decimal
            total_after: Decimal
            delta: Decimal
            changed_count: int
    """
    qs = (
        ModeratorPayment.objects
        .filter(
            status__in=(
                ModeratorPayment.Status.UNPAID,
                ModeratorPayment.Status.PARTIALLY_PAID,
            )
        )
        .select_related("moderator")
        .order_by("moderator__username", "payment_week_start")
    )

    if moderator is not None:
        qs = qs.filter(moderator=moderator)

    records = list(qs)

    total_before = Decimal("0.00")
    total_after = Decimal("0.00")
    result_records = []

    for mp in records:
        # Get the current rate from the global ChatRateTier card
        try:
            tier = get_applicable_rate_tier(
                chats_responded=mp.payable_chats,
                operating_date=mp.payment_week_end,
            )
            new_rate = tier.rate_per_chat
        except Exception:
            new_rate = mp.rate_per_chat or Decimal("0.00")

        old_earned = mp.earned_amount or Decimal("0.00")
        new_earned = (Decimal(mp.payable_chats) * new_rate).quantize(Decimal("0.01"))
        new_outstanding = (new_earned - (mp.amount_paid or Decimal("0.00"))).quantize(Decimal("0.01"))

        total_before += old_earned
        total_after += new_earned

        result_records.append({
            "id": mp.id,
            "moderator_username": mp.moderator.username,
            "moderator_id": mp.moderator_id,
            "week_start": mp.payment_week_start,
            "week_end": mp.payment_week_end,
            "payable_chats": mp.payable_chats,
            "old_rate": mp.rate_per_chat or Decimal("0.00"),
            "new_rate": new_rate,
            "old_earned": old_earned,
            "new_earned": new_earned,
            "new_outstanding": new_outstanding,
            "changed": old_earned != new_earned,
            "_mp": mp,  # hold reference for apply phase
        })

    changed = [r for r in result_records if r["changed"]]

    if apply and changed:
        from django.utils import timezone as _tz
        now = _tz.localtime()

        with transaction.atomic():
            for r in changed:
                mp = r["_mp"]
                existing_log = mp.rate_reconciliation or {}
                if not isinstance(existing_log, dict):
                    existing_log = {"entries": existing_log}
                entries = existing_log.get("entries", [])
                if not isinstance(entries, list):
                    entries = []
                entries.append({
                    "old_earned": str(r["old_earned"]),
                    "new_earned": str(r["new_earned"]),
                    "old_rate": str(r["old_rate"]),
                    "new_rate": str(r["new_rate"]),
                    "reason": "recalculated at current ChatRateTier",
                    "applied_at": now.isoformat(),
                })
                existing_log["entries"] = entries

                mp.earned_amount = r["new_earned"]
                mp.outstanding_amount = r["new_outstanding"]
                mp.rate_per_chat = r["new_rate"]
                mp.chat_earnings = r["new_earned"]
                mp.rate_reconciliation = existing_log

                if r["new_outstanding"] <= Decimal("0.00") and (mp.amount_paid or Decimal("0.00")) > Decimal("0.00"):
                    mp.outstanding_amount = Decimal("0.00")
                    mp.status = ModeratorPayment.Status.PAID
                elif (mp.amount_paid or Decimal("0.00")) > Decimal("0.00"):
                    mp.status = ModeratorPayment.Status.PARTIALLY_PAID

                mp.save(update_fields=[
                    "earned_amount",
                    "outstanding_amount",
                    "rate_per_chat",
                    "chat_earnings",
                    "rate_reconciliation",
                    "status",
                    "updated_at",
                ])

    # Strip the private _mp reference before returning
    for r in result_records:
        r.pop("_mp", None)

    return {
        "mode": "APPLY" if apply else "PREVIEW",
        "records": result_records,
        "total_before": total_before,
        "total_after": total_after,
        "delta": total_after - total_before,
        "changed_count": len(changed),
    }
