from datetime import date

from django.core.management.base import BaseCommand, CommandError

from bonuses.services import determine_daily_moderator_bonuses


class Command(BaseCommand):
    help = "Perform the official daily Moderator bonus determination at 9:45 AM."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="determination_date",
            help="Local determination date in YYYY-MM-DD format; defaults to today.",
        )

    def handle(self, *args, **options):
        raw_date = options.get("determination_date")
        try:
            determination_date = (
                date.fromisoformat(raw_date) if raw_date else None
            )
        except ValueError as exc:
            raise CommandError("--date must use YYYY-MM-DD format.") from exc

        awards = determine_daily_moderator_bonuses(
            determination_date=determination_date,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Daily bonus determination completed. Awards created/existing: {len(awards)}."
            )
        )