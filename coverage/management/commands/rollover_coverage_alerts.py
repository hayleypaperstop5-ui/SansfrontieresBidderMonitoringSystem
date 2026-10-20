from django.core.management.base import BaseCommand
from coverage.tasks import rollover_stale_coverage_alerts_task


class Command(BaseCommand):
    help = "Expire OPEN coverage alerts whose operating_date is in the past."

    def handle(self, *args, **options):
        result = rollover_stale_coverage_alerts_task()
        self.stdout.write(self.style.SUCCESS(f"rollover_coverage_alerts: {result}"))
