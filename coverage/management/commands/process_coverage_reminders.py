from django.core.management.base import BaseCommand
from coverage.tasks import process_coverage_reminders_task


class Command(BaseCommand):
    help = "Send due reminders for unresolved coverage alerts (every 15 min per alert)."

    def handle(self, *args, **options):
        result = process_coverage_reminders_task()
        self.stdout.write(
            self.style.SUCCESS(f"process_coverage_reminders: {result}")
        )