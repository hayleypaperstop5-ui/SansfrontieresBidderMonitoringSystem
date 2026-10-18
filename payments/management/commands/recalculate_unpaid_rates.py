"""
Management command to recalculate unpaid ModeratorPayment records using
the current ChatRateTier card.

By default this is PREVIEW ONLY — it shows what would change but does not
write to the database. Use --apply to actually apply the changes.

Usage:
    # Preview changes
    python manage.py recalculate_unpaid_rates

    # Apply changes (with audit log)
    python manage.py recalculate_unpaid_rates --apply

    # Recalculate for a single moderator
    python manage.py recalculate_unpaid_rates --moderator wakuradavid1990@gmail.com
"""
import json
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from payments.models import ModeratorPayment
from payments.services import get_applicable_player_chat_rate_tier
from players.models import Player


class Command(BaseCommand):
    help = "Recalculate unpaid ModeratorPayment earned amounts using current ChatRateTier card."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually apply the changes (default is preview only).",
        )
        parser.add_argument(
            "--moderator",
            default=None,
            help="Limit to a single moderator username.",
        )

    def handle(self, *args, **options):
        apply_mode = options["apply"]
        moderator_username = options["moderator"]

        qs = ModeratorPayment.objects.filter(
            status__in=(
                ModeratorPayment.Status.UNPAID,
                ModeratorPayment.Status.PARTIALLY_PAID,
            )
        ).select_related("moderator").order_by("moderator__username", "payment_week_start")

        if moderator_username:
            qs = qs.filter(moderator__username=moderator_username)

        records = list(qs)
        if not records:
            self.stdout.write(self.style.WARNING("No unpaid records found."))
            return

        mode_label = "APPLY" if apply_mode else "PREVIEW"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== Mode: {mode_label} — {len(records)} unpaid record(s) ==="
        ))
        self.stdout.write("")

        total_old = Decimal("0.00")
        total_new = Decimal("0.00")
        changes = []

        for mp in records:
            from payments.services import get_applicable_rate_tier

            # Rate is always based on the chats being paid for this record,
            # looked up against the global ChatRateTier card. This matches
            # the "higher chats = higher rate" design without requiring
            # per-player rate differentiation.
            try:
                tier = get_applicable_rate_tier(
                    chats_responded=mp.payable_chats,
                    operating_date=mp.payment_week_end,
                )
                new_rate = tier.rate_per_chat
                rate_basis = f"global (payable_chats={mp.payable_chats})"
            except Exception as exc:
                new_rate = mp.rate_per_chat or Decimal("0.00")
                rate_basis = f"stored fallback ({exc})"

            if new_rate is None:
                new_rate = Decimal("0.00")
                rate_basis = "unresolved (rate 0.00)"

            old_earned = mp.earned_amount or Decimal("0.00")
            old_rate = mp.rate_per_chat or Decimal("0.00")
            new_earned = (Decimal(mp.payable_chats) * new_rate).quantize(Decimal("0.01"))
            new_outstanding = (new_earned - (mp.amount_paid or Decimal("0.00"))).quantize(Decimal("0.01"))

            total_old += old_earned
            total_new += new_earned

            self.stdout.write(
                f"  #{mp.id} {mp.moderator.username} ({mp.payment_week_start} → {mp.payment_week_end})"
            )
            self.stdout.write(
                f"      {mp.payable_chats} chats: {old_rate} → {new_rate} "
                f"| earned {old_earned} → {new_earned} "
                f"| outstanding → {new_outstanding} "
                f"| basis: {rate_basis}"
            )

            if old_earned != new_earned:
                changes.append((mp, old_earned, new_earned, old_rate, new_rate, new_outstanding))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Total before: {total_old} | Total after: {total_new} | Delta: {total_new - total_old}"
        ))
        self.stdout.write(f"Records to change: {len(changes)}")

        if not apply_mode:
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                "PREVIEW mode. No changes applied. Re-run with --apply to write to DB."
            ))
            return

        # APPLY mode — write changes inside one transaction
        with transaction.atomic():
            now = timezone.localtime()
            for mp, old_earned, new_earned, old_rate, new_rate, new_outstanding in changes:
                existing_log = mp.rate_reconciliation or {}
                if not isinstance(existing_log, dict):
                    existing_log = {"entries": existing_log}
                entries = existing_log.get("entries", [])
                if not isinstance(entries, list):
                    entries = []
                entries.append({
                    "old_earned": str(old_earned),
                    "new_earned": str(new_earned),
                    "old_rate": str(old_rate),
                    "new_rate": str(new_rate),
                    "reason": "recalculated at current ChatRateTier",
                    "applied_at": now.isoformat(),
                })
                existing_log["entries"] = entries

                mp.earned_amount = new_earned
                mp.outstanding_amount = new_outstanding
                mp.rate_per_chat = new_rate
                mp.chat_earnings = new_earned  # keep chat_earnings in sync with earned_amount
                # Note: player_chat_rate_breakdown is preserved as historical record
                # of what rates applied when the payment was originally computed.
                # The PDF should display the CURRENT rate from rate_per_chat, not the
                # historical breakdown, to reflect the recalculated state.
                mp.rate_reconciliation = existing_log

                # If fully paid after recompute, mark PAID
                if new_outstanding <= Decimal("0.00") and (mp.amount_paid or Decimal("0.00")) > Decimal("0.00"):
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

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"APPLIED: {len(changes)} record(s) updated."
        ))
