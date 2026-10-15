from datetime import time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from bonuses.services import evaluate_all_moderator_bonuses


QUALIFICATION_HOUR = 8
QUALIFICATION_MINUTE = 45


class Command(BaseCommand):
    help = (
        "Evaluate every Moderator's chats in the daily 24-hour "
        "bonus window ending at 8:45 AM."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-end",
            dest="window_end",
            help=(
                "Optional window end datetime. "
                "Format: YYYY-MM-DD HH:MM:SS"
            ),
        )

    def handle(self, *args, **options):
        window_end_text = options.get("window_end")

        if window_end_text:
            try:
                window_end = timezone.datetime.strptime(
                    window_end_text,
                    "%Y-%m-%d %H:%M:%S",
                )

                if timezone.is_naive(window_end):
                    window_end = timezone.make_aware(
                        window_end,
                        timezone.get_current_timezone(),
                    )

            except ValueError:
                self.stderr.write(
                    self.style.ERROR(
                        "Invalid --window-end format. "
                        "Use YYYY-MM-DD HH:MM:SS"
                    )
                )
                return

        else:
            now = timezone.localtime(timezone.now())
            today_845 = now.replace(
                hour=QUALIFICATION_HOUR,
                minute=QUALIFICATION_MINUTE,
                second=0,
                microsecond=0,
            )

            if now >= today_845:
                window_end = today_845
            else:
                window_end = today_845 - timedelta(days=1)

        bonus_date = timezone.localtime(window_end).date()
        window_start = window_end - timedelta(hours=24)

        self.stdout.write(
            f"Bonus evaluation window: "
            f"{window_start} -> {window_end}"
        )

        awards = evaluate_all_moderator_bonuses(
            window_end=window_end,
            bonus_date=bonus_date,
        )

        if not awards:
            self.stdout.write(
                self.style.WARNING(
                    "No Moderators qualified for a bonus."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(awards)} Moderator bonus award(s) found."
            )
        )

        for award in awards:
            self.stdout.write(
                f"Moderator ID {award.moderator_id}: "
                f"{award.chats_counted:,} chats / "
                f"{award.minimum_chats_snapshot:,} required - "
                f"KES {award.bonus_amount:,.2f}"
            )
