from django.core.management.base import BaseCommand
from coverage.tasks import finalize_continuation_deadlines_task


class Command(BaseCommand):
    help = "Run 09:00 enforcement: sign out non-responders, continue responders."

    def handle(self, *args, **options):
        result = finalize_continuation_deadlines_task()
        self.stdout.write(self.style.SUCCESS(f"finalize_continuation_deadlines: {result}"))
