"""
Recalculate unpaid ModeratorPayment records using the current ChatRateTier.

Preview by default. Use --apply to write changes.
"""
from django.core.management.base import BaseCommand

from accounts.models import User
from payments.services import recalculate_unpaid_rates as _recalc_service


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
        moderator = None
        if options["moderator"]:
            moderator = User.objects.filter(username=options["moderator"]).first()
            if not moderator:
                self.stdout.write(self.style.ERROR(
                    f"Moderator {options['moderator']!r} not found."
                ))
                return

        result = _recalc_service(moderator=moderator, apply=options["apply"])

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== Mode: {result['mode']} — {len(result['records'])} record(s) ==="
        ))
        self.stdout.write("")

        for r in result["records"]:
            marker = " *" if r["changed"] else ""
            self.stdout.write(
                f"  #{r['id']} {r['moderator_username']} "
                f"({r['week_start']} → {r['week_end']})"
            )
            self.stdout.write(
                f"      {r['payable_chats']} chats: {r['old_rate']} → {r['new_rate']} "
                f"| earned {r['old_earned']} → {r['new_earned']}{marker}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Total before: {result['total_before']} | "
            f"Total after: {result['total_after']} | "
            f"Delta: {result['delta']}"
        ))
        self.stdout.write(f"Records to change: {result['changed_count']}")

        if result["mode"] == "PREVIEW":
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                "PREVIEW mode. No changes applied. Re-run with --apply to write to DB."
            ))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(
                f"APPLIED: {result['changed_count']} record(s) updated."
            ))
