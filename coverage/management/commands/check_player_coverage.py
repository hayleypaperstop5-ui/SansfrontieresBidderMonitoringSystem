from django.core.management.base import BaseCommand
from coverage.tasks import check_player_coverage_task


class Command(BaseCommand):
    help = 'Detect uncovered players and create coverage alerts.'

    def handle(self, *args, **options):
        result = check_player_coverage_task()
        self.stdout.write(self.style.SUCCESS(f'check_player_coverage: {result}'))
