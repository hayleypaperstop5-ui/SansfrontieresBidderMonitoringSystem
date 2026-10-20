from django.core.management.base import BaseCommand
from coverage.tasks import send_continuation_prompts_task


class Command(BaseCommand):
    help = "Send 08:45 continuation prompts to every ACTIVE coverage session."

    def handle(self, *args, **options):
        result = send_continuation_prompts_task()
        self.stdout.write(self.style.SUCCESS(f"send_continuation_prompts: {result}"))
