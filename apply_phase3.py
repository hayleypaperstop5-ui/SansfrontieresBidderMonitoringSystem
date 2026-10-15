import sys
import shutil
from decimal import Decimal
from pathlib import Path

ROOT = Path.cwd()

services_path = ROOT / "payments" / "services.py"
views_path = ROOT / "payments" / "views.py"
urls_path = ROOT / "payments" / "urls.py"
settings_path = ROOT / "templates" / "payments" / "payment_settings.html"
dashboard_path = ROOT / "templates" / "dashboard" / "director_dashboard.html"
templates_dir = ROOT / "templates" / "payments"

required = [
    services_path,
    views_path,
    urls_path,
    settings_path,
    dashboard_path,
    templates_dir,
]

print("=" * 78)
print("PHASE 3 - CONTROLLED PAYROLL REVIEW & PROCESSING")
print("=" * 78)

for path in required:
    if not path.exists():
        raise SystemExit(f"ABORTED: Required path not found: {path}")


def read(path):
    return path.read_text(encoding="utf-8-sig")


services = read(services_path)
views = read(views_path)
urls = read(urls_path)
settings_template = read(settings_path)
dashboard_template = read(dashboard_path)

# ---------------------------------------------------------------------------
# STRICT PRE-MODIFICATION VERIFICATION
# ---------------------------------------------------------------------------
checks = {
    "services.py process_thursday_payroll": (
        services.count("def process_thursday_payroll(payment_date):") == 1
    ),
    "services.py qualifying processor": (
        services.count("def process_qualifying_player_chats(") == 1
    ),
    "services.py settlement function": (
        services.count("def settle_moderator_payment(") == 1
    ),
    "services.py BOTH formula": (
        "Decimal(player_chats)" in services
        and "* chat_tier_rate" in services
        and "* player_rate" in services
    ),
    "views.py payment_settings": views.count("def payment_settings(request):") == 1,
    "urls.py payment settings": 'name="payment_settings"' in urls,
    "settings standalone HTML": (
        "<!DOCTYPE html>" in settings_template and "</html>" in settings_template
    ),
    "settings no template endblock assumption": (
        "{% endblock %}" not in settings_template
    ),
    "dashboard payroll action": (
        "payment_settings" in dashboard_template
        and ("Payroll" in dashboard_template or "payroll" in dashboard_template)
    ),
}

failed = [name for name, ok in checks.items() if not ok]

if failed:
    print("\nPRE-MODIFICATION VERIFICATION FAILED:")
    for item in failed:
        print(f"  - {item}")
    print("\nNO FILES WERE MODIFIED.")
    sys.exit(1)

phase3_markers = [
    "def build_payroll_plan(",
    "def payroll_review(request):",
    "def process_payroll_view(request):",
    "def payroll_results(request):",
]

already = [
    marker
    for marker in phase3_markers
    if marker in services or marker in views
]

if already:
    print("\nABORTED: Phase 3 implementation markers already exist:")
    for marker in already:
        print(f"  - {marker}")
    print("\nNO FILES WERE MODIFIED.")
    sys.exit(1)

review_template_path = templates_dir / "payroll_review.html"
results_template_path = templates_dir / "payroll_results.html"

if review_template_path.exists() or results_template_path.exists():
    print("\nABORTED: One or more Phase 3 target templates already exist.")
    print("No files were modified.")
    sys.exit(1)

print("\nPre-modification verification: PASSED")

# ---------------------------------------------------------------------------
# BACKUPS
# ---------------------------------------------------------------------------
backup_map = {}

for path in [
    services_path,
    views_path,
    urls_path,
    settings_path,
    dashboard_path,
]:
    backup = Path(str(path) + ".before-phase3-payroll-review.bak")

    if backup.exists():
        raise SystemExit(
            f"ABORTED: Backup already exists; refusing to overwrite:\n{backup}"
        )

    shutil.copy2(path, backup)
    backup_map[path] = backup

print("\nBackups created:")
for original, backup in backup_map.items():
    print(f"  {original}")
    print(f"    -> {backup}")

# ---------------------------------------------------------------------------
# 1. BUILD PAYROLL PLAN FUNCTION
# ---------------------------------------------------------------------------
plan_function = '''
def build_payroll_plan(
    payment_date,
    *,
    threshold=None,
):
    from datetime import date
    from django.core.exceptions import ValidationError
    from django.db import models
    from django.db.models import Sum
    from accounts.models import User
    from players.models import Player

    if not isinstance(payment_date, date):
        raise ValidationError("A valid payment date is required.")

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
'''

services_new = services.replace(
    "def process_thursday_payroll(payment_date):",
    plan_function + "\ndef process_thursday_payroll(payment_date):",
    1,
)

# ---------------------------------------------------------------------------
# 2. UPDATE PAYROLL PROCESSOR IN SERVICES.PY
# ---------------------------------------------------------------------------
processor_start = services_new.index("def process_thursday_payroll(payment_date):")
processor_end = services_new.index(
    "@transaction.atomic\ndef settle_moderator_payment(",
    processor_start,
)

new_processor = '''def process_thursday_payroll(payment_date):
    from datetime import date
    from django.core.exceptions import ValidationError
    from django.db import models, transaction

    if not isinstance(payment_date, date):
        raise ValidationError("A valid payment date is required.")

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

        plan = build_payroll_plan(payment_date=payment_date)

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

            ModeratorPayment.objects.create(
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
            created_payments.append(moderator_id)

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
'''

services_new = (
    services_new[:processor_start]
    + new_processor
    + "\n"
    + services_new[processor_end:]
)

services_path.write_text(services_new, encoding="utf-8")

# ---------------------------------------------------------------------------
# 3. UPDATE VIEWS.PY
# ---------------------------------------------------------------------------
views_import = (
    "from .services import build_payroll_plan, process_thursday_payroll\n"
)

views_new = views
if "from .services import" not in views_new:
    views_new = views_import + views_new

payroll_views = '''

@role_required(*RATE_MANAGEMENT_ROLES)
def payroll_review(request):
    from datetime import date as date_type

    plan = build_payroll_plan(payment_date=date_type.today())
    return render(request, "payments/payroll_review.html", {"plan": plan})


@role_required(*RATE_MANAGEMENT_ROLES)
def process_payroll_view(request):
    if request.method != "POST":
        return redirect("payments:payroll_review")

    from datetime import date as date_type

    try:
        result = process_thursday_payroll(payment_date=date_type.today())
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect("payments:payroll_review")

    request.session["payroll_result"] = {
        "payment_date": result["payment_date"].isoformat(),
        "week_start": result["week_start"].isoformat(),
        "week_end": result["week_end"].isoformat(),
        "threshold": result["threshold"],
        "payments_created": result["payments_created"],
        "total_payable_chats": result["total_payable_chats"],
        "total_chat_earnings": str(result["total_chat_earnings"]),
        "total_bonuses": str(result["total_bonuses"]),
        "total_earned": str(result["total_earned"]),
    }
    return redirect("payments:payroll_results")
'''

payment_settings_marker = "def payment_settings(request):"
if payment_settings_marker in views_new:
    views_new = views_new.replace(
        payment_settings_marker,
        payroll_views + "\n\n" + payment_settings_marker,
        1,
    )

views_path.write_text(views_new, encoding="utf-8")

print("\nFiles modified successfully.")
print("Phase 3 Script Complete.")
