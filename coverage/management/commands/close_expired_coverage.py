from django.core.management.base import BaseCommand
from coverage.services import close_expired_coverage_sessions


class Command(BaseCommand):
    help = "Close expired coverage sessions and mark OPEN assignments as MISSED."

    def handle(self, *args, **options):
        count = close_expired_coverage_sessions()
        self.stdout.write(self.style.SUCCESS(f"close_expired_coverage: closed {count} session(s)"))
