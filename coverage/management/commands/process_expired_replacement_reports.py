from django.core.management.base import BaseCommand
from coverage.services import process_expired_replacement_reports


class Command(BaseCommand):
    help = "Finalize staged force replacements whose 15-min report deadline expired."

    def handle(self, *args, **options):
        count = process_expired_replacement_reports()
        self.stdout.write(self.style.SUCCESS(f"Processed {count} expired replacement(s)."))
